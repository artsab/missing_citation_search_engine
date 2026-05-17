# Этап 2: PDF-парсер (marker wrapper) — Детальный план

## Цель

Реализовать модуль `app/ingestion/parser.py`, который принимает PDF-файл (путь или байты) и возвращает структурированный `ParsedDocument` с markdown-текстом, секциями и метаданными. Базовая обёртка над `marker-pdf`.

## Исходное состояние проекта

**Что уже реализовано (Этап 1):**
- `app/config.py` — загрузка `.env` + `config.yaml` через pydantic-settings
- `app/models/schemas.py` — Pydantic-модели (Claim, Reference, MissingCitation, AnalyzeResponse, PaperRecord, ChunkPayload, Candidate)
- `app/db/postgres.py` — asyncpg-обёртка, создание таблицы `papers`
- `app/db/qdrant.py` — Qdrant-обёртка, создание коллекции `papers`, search/upsert
- `app/main.py` — FastAPI с lifespan, `/health`, заглушка `POST /analyze`
- `pyproject.toml` — зависимости включают `marker-pdf>=1.0`
- `docker-compose.yml`, `Dockerfile`, `.env.example`, `config.yaml`
- `tests/conftest.py`, `tests/integration/test_stage1_infra.py`

**Что НЕ сделано:**
- Нет `app/ingestion/parser.py`
- Нет модели `ParsedDocument`
- Нет `ParseError`
- Нет тестов для парсера

## Изучение marker-pdf API

### Версия
`marker-pdf==1.10.2` (уже установлен в `.venv`)

### Основной класс: `PdfConverter` (из `marker.converters.pdf`)

```python
from marker.converters.pdf import PdfConverter

converter = PdfConverter(
    artifact_dict={},       # модели surya (layout, detection, recognition, etc.)
    processor_list=None,    # список процессоров, default — полный набор
    renderer=None,          # по умолчанию MarkdownRenderer
    llm_service=None,       # LLM-сервис для улучшенной обработки
    config={'use_llm': False},
)

# Вызов: filepath (str) или BytesIO
rendered = converter(filepath)  # -> MarkdownOutput
```

### `MarkdownOutput` (из `marker.output`)

```python
class MarkdownOutput(BaseModel):
    markdown: str        # итоговый markdown-текст
    images: dict         # {image_name: PIL.Image}
    metadata: dict       # {
                         #   "table_of_contents": [...],  # оглавление
                         #   "page_stats": [...]          # статистика по страницам
                         # }
```

`metadata` **НЕ** содержит `title`, `authors`, `abstract` — их нужно извлекать из markdown эвристически.

### Важные детали

1. **marker — тяжёлая библиотека.** Первый вызов загружает модели surya (layout, detection, recognition — ~2–4 ГБ), работает медленно на CPU. Тестовый PDF в `in_pdfs/` занял >120 секунд на первом прогоне. В тестах парсер **нужно мокать** через `unittest.mock`, интеграционные тесты запускать только по явному флагу.

2. **Блоки marker** (из `marker.schema.BlockTypes`): есть `SectionHeader`, `Text`, `Reference`, `Table`, `Figure`, `Equation` и другие. В markdown-выводе секции представлены заголовками (##, ###), а блоки — текстом.

3. **Структура markdown:** `MarkdownRenderer` преобразует HTML-представление документа в markdown. Заголовки секций становятся markdown-заголовками (`#`, `##`, `###`).

---

## Задача 1: Создать модели данных (`ParsedDocument`, `ParseError`) в `app/ingestion/parser.py`

### 1.1 `ParsedDocument`

Pydantic-модель:

```python
from pydantic import BaseModel, Field

class Section(BaseModel):
    """Секция статьи."""
    heading: str              # заголовок секции (напр. "Введение")
    level: int                # уровень заголовка (1, 2, 3...)
    content: str              # текст секции (markdown)
    start_line: int           # номер строки начала в markdown

class ParsedDocument(BaseModel):
    """Результат парсинга PDF: структурированный markdown + метаданные."""
    markdown: str             # полный markdown-текст
    title: str = ""           # заголовок статьи
    abstract: str = ""        # аннотация (если есть)
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    sections: list[Section] = Field(default_factory=list)
```

**Поля:**
- `markdown` — полный текст из `MarkdownOutput.markdown`
- `title` — первый заголовок первого уровня в markdown
- `abstract` — содержимое секции с заголовком, содержащим "abstract" / "аннотация" / "реферат" (регистронезависимо)
- `authors` — извлекаются эвристически: строки между title и abstract, похожие на «И. О. Фамилия»
- `year` — год в диапазоне 1900–2099, найденный в первом абзаце или заголовке
- `doi` — DOI в тексте (regex: `10.\d{4,}/[^\s]+`)
- `sections` — список секций с заголовками и содержимым

### 1.2 `ParseError`

```python
class ParseError(Exception):
    """Ошибка парсинга PDF."""
    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error
```

---

## Задача 2: Реализовать `parse_pdf()` в `app/ingestion/parser.py`

### 2.1 Сигнатура

```python
def parse_pdf(path: str) -> ParsedDocument:
    """
    Конвертировать PDF в ParsedDocument с markdown и метаданными.

    Args:
        path: путь к PDF-файлу.

    Returns:
        ParsedDocument с markdown, секциями, title, abstract, authors, year, doi.

    Raises:
        ParseError: если PDF повреждён или marker не смог его обработать.
        FileNotFoundError: если файл не найден.
    """
```

### 2.2 Алгоритм

```
parse_pdf(path)
  ├─ проверить, что файл существует (FileNotFoundError)
  ├─ проверить, что файл не пустой (ParseError)
  │
  ├─ создать PdfConverter с use_llm=False (только CPU)
  ├─ при создании artifact_dict передать create_model_dict()
  ├─ вызвать converter(path)
  │
  ├─ если marker выбросил исключение → ParseError
  │
  ├─ markdown = rendered.markdown
  ├─ sections = extract_sections(markdown)
  ├─ title = extract_title(markdown)
  ├─ abstract = extract_abstract(markdown, sections)
  ├─ authors = extract_authors(markdown, title)
  ├─ year = extract_year(markdown)
  ├─ doi = extract_doi(markdown)
  │
  └─ вернуть ParsedDocument(...)
```

### 2.3 Вспомогательные функции извлечения

**Все приватные, внутри `parser.py`:**

#### `_create_converter() -> PdfConverter`
- Создаёт `PdfConverter` с `use_llm=False`
- Вызывает `create_model_dict()` для загрузки surya-моделей
- Конфигурация через `ConfigParser`

#### `_extract_sections(markdown: str) -> list[Section]`
- Ищет строки, начинающиеся с `#` (заголовки markdown)
- Группирует текст между заголовками одного уровня
- Различает уровни по количеству `#`
- Первая секция до первого заголовка — `""` (title area), игнорируется или помещается в начало первой секции

#### `_extract_title(markdown: str) -> str`
- Первый заголовок первого уровня (`# ...`) в markdown
- Если нет `#`, то первая непустая строка
- Убирает символы `#` и пробелы

#### `_extract_abstract(markdown: str, sections: list[Section]) -> str`
- Ищет секцию, у которой `heading.lower()` содержит `"abstract"`, `"аннотация"`, `"реферат"`
- Берёт `content` этой секции
- Если секции нет — возвращает текст первого абзаца (первые 3–5 строк до первого заголовка)
- Если текст пустой — `""`

#### `_extract_authors(markdown: str, title: str) -> list[str]`
- Ищет строки между title и abstract / первым заголовком
- Эвристика: строки, содержащие инициалы (паттерн: заглавная буква + точка + пробел + заглавная буква + точка)
- Альтернативно: строки с запятыми, похожие на перечисление имён

#### `_extract_year(markdown: str) -> int | None`
- Поиск в первых 500 символах четырёхзначного числа 19xx или 20xx
- Первое вхождение

#### `_extract_doi(markdown: str) -> str | None`
- Regex: `10.\d{4,}/[^\s]+`
- Убирает trailing точку/запятую/точку с запятой

### 2.4 Обработка ошибок

| Ситуация | Результат |
|----------|-----------|
| Файл не существует | `FileNotFoundError` (проросить) |
| Файл пустой (0 байт) | `ParseError("PDF file is empty")` |
| marker выбросил исключение при парсинге | `ParseError("Failed to parse PDF: {reason}", original_error=e)` |
| marker не выбросил исключение, но markdown пустой (менее 10 символов) | Не ошибка — возвращаем ParsedDocument с пустыми полями |
| Таймаут парсинга (>300 сек) | `ParseError("PDF parsing timed out")` |

### 2.5 Зависимости и импорты

```python
# Внешние
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.config.parser import ConfigParser

# Внутренние
from app.models.schemas import ...  # возможно, ничего не нужно
```

---

## Задача 3: Обработка edge-case'ов

1. **PDF без текста (только сканы изображений без OCR)** — marker всё равно попытается через surya OCR, но может вернуть очень мало текста. Не ошибка, `ParsedDocument.markdown` будет почти пустым.

2. **PDF с кириллицей** — marker поддерживает кириллицу через surya recognition. Должен работать.

3. **Очень большой PDF (100+ страниц)** — marker обработает, но может занять много времени. Ограничения по времени нет на уровне парсера.

4. **PDF с паролем / зашифрованный** — marker выбросит исключение → `ParseError`.

5. **Пустой markdown-вывод** — все поля `ParsedDocument` будут пустыми/нулевыми. Не ошибка.

6. **Кэширование моделей marker** — `create_model_dict()` загружается один раз. Можно вынести в `lru_cache` на уровне модуля.

---

## Задача 4: Кэширование моделей marker

```python
from functools import lru_cache

@lru_cache(maxsize=1)
def _get_models() -> dict:
    """Загрузить модели marker один раз (тяжёлая операция)."""
    return create_model_dict()
```

Конвертер создаётся заново при каждом вызове `parse_pdf()` (лёгкая операция), модели загружаются один раз.

---

## Задача 5: Написать юнит-тесты

Файл: `tests/unit/test_stage2_parser.py`

### 5.1 Класс `TestMarkerParser` (с моком `PdfConverter`)

**Фикстуры:**
- `mock_marker` — мокает `PdfConverter.__call__`, возвращает `MarkdownOutput` с заданным `markdown`
- `sample_pdf_path` — временный файл с фиктивным PDF
- `corrupt_pdf_path` — пустой файл (0 байт)
- `empty_pdf_path` — минимальный PDF-заголовок без содержательного текста (marker вернёт пустой markdown)

**Тесты:**

| # | Тест | Описание |
|---|------|----------|
| 1 | `test_parse_valid_pdf_returns_markdown` | Валидный PDF → ParsedDocument с markdown и секциями |
| 2 | `test_parse_extracts_title` | Заголовок извлекается из `# Заголовок` |
| 3 | `test_parse_extracts_title_from_first_line` | Если нет `#`, берётся первая строка |
| 4 | `test_parse_extracts_authors` | Авторы извлекаются списком из строки с инициалами |
| 5 | `test_parse_extracts_authors_english` | Авторы на английском тоже извлекаются |
| 6 | `test_parse_extracts_abstract` | Abstract из секции "Abstract" |
| 7 | `test_parse_extracts_abstract_russian` | Abstract из секции "Аннотация" |
| 8 | `test_parse_extracts_abstract_fallback` | Если нет секции abstract — первый абзац |
| 9 | `test_parse_extracts_year` | Год извлекается (19xx или 20xx) |
| 10 | `test_parse_extracts_doi` | DOI извлекается через regex |
| 11 | `test_parse_extracts_sections` | Секции с заголовками и содержимым |
| 12 | `test_parse_section_levels` | Уровни заголовков (##, ###) различаются |
| 13 | `test_parse_corrupted_pdf_raises_parse_error` | Битый/пустой PDF → ParseError |
| 14 | `test_parse_nonexistent_file_raises` | Несуществующий файл → FileNotFoundError |
| 15 | `test_parse_empty_pdf_returns_empty_document` | PDF без текста → ParsedDocument с пустыми полями, без ошибки |
| 16 | `test_parse_marker_exception_converts_to_parse_error` | marker выбросил исключение → ParseError с original_error |
| 17 | `test_parsed_document_serializable` | ParsedDocument сериализуется в JSON/dict |

### 5.2 Тестовые markdown-фикстуры

Создать `tests/unit/fixtures/markdown_samples.py`:

```python
SAMPLE_MARKDOWN_RUSSIAN = """\
# Методы обнаружения пропущенных цитат в научных статьях

И. О. Фамилия, П. С. Другой

## Аннотация

В данной работе рассматриваются современные методы обнаружения пропущенных научных цитат...

## Введение

Проблема обнаружения пропущенных цитирований является актуальной...

## Методы

Предлагаемый подход основан на комбинации...

## Результаты

Эксперименты показали, что предложенный метод...

DOI: 10.1234/5678.2024
"""

SAMPLE_MARKDOWN_ENGLISH = """\
# Citation Detection Methods

John Smith, Jane Doe

## Abstract

This paper presents a novel approach to detecting missing citations...

## Introduction

The problem of citation completeness has been studied extensively...

## Methods

We propose a hybrid approach combining...

## Results

Our experiments demonstrate...

DOI: 10.5678/9012.2024
"""

SAMPLE_MARKDOWN_MINIMAL = """\
# A Short Paper

## Abstract

Brief abstract text.
"""

SAMPLE_MARKDOWN_NO_HEADINGS = """\
This is a paper without proper markdown headings.
It just has plain text.

Authors: A. B. Ceedee, E. F. Gee
Year: 2023
"""
```

---

## Задача 6: Написать интеграционные тесты

Файл: `tests/integration/test_stage2_parser_real.py`

### 6.1 Класс `TestMarkerParserIntegration`

**Требуется:** реальный marker (тяжёлый, с загрузкой моделей). Пометить `@pytest.mark.slow` и `@pytest.mark.integration`.

**Использует:** PDF-файлы из `in_pdfs/`.

**Тесты:**

| # | Тест | Описание |
|---|------|----------|
| 1 | `test_parse_real_scientific_pdf` | Реальный научный PDF → ParsedDocument с markdown длиной > 200 |
| 2 | `test_parse_all_test_pdfs` | Все PDF из `in_pdfs/` парсятся без ошибок |
| 3 | `test_real_pdf_has_title` | У реального PDF извлекается title |
| 4 | `test_real_pdf_has_sections` | У реального PDF ≥ 1 секции |

---

## Задача 7: Структура файлов после Этапа 2

```
app/
├── ingestion/
│   ├── __init__.py           # было: пустой docstring
│   └── parser.py             # НОВЫЙ: parse_pdf(), ParsedDocument, Section, ParseError
│
├── models/
│   └── schemas.py            # БЕЗ ИЗМЕНЕНИЙ (не добавляем ParsedDocument сюда)
│                             # ParsedDocument — внутренняя модель ingestion, не API-модель

tests/
├── unit/
│   ├── __init__.py
│   ├── test_stage2_parser.py  # НОВЫЙ: юнит-тесты парсера с моком marker
│   └── fixtures/
│       └── markdown_samples.py  # НОВЫЙ: фикстуры markdown-текстов
│
├── integration/
│   ├── __init__.py
│   ├── test_stage1_infra.py   # существующий
│   └── test_stage2_parser_real.py  # НОВЫЙ: интеграционные тесты на реальных PDF

in_pdfs/
├── 01_Masagutov_s.pdf         # существующий (уже есть)
└── 01_Vyalov_7704kJ7.pdf      # существующий (уже есть)
```

---

## Задача 8: Порядок выполнения (checklist)

- [ ] 8.1 Создать `tests/unit/fixtures/` и `markdown_samples.py` с тестовыми markdown-строками
- [ ] 8.2 Создать `tests/unit/test_stage2_parser.py` — сначала тесты (TDD)
- [ ] 8.3 Реализовать `app/ingestion/parser.py`:
  - [ ] 8.3.1 Класс `Section` и `ParsedDocument`
  - [ ] 8.3.2 `ParseError`
  - [ ] 8.3.3 `_get_models()` с `@lru_cache`
  - [ ] 8.3.4 `_create_converter()` — создание PdfConverter
  - [ ] 8.3.5 `_extract_sections()` — извлечение секций по markdown-заголовкам
  - [ ] 8.3.6 `_extract_title()` — извлечение заголовка
  - [ ] 8.3.7 `_extract_abstract()` — извлечение аннотации
  - [ ] 8.3.8 `_extract_authors()` — извлечение авторов
  - [ ] 8.3.9 `_extract_year()` — извлечение года
  - [ ] 8.3.10 `_extract_doi()` — извлечение DOI
  - [ ] 8.3.11 `parse_pdf()` — главная функция, собирающая всё вместе
- [ ] 8.4 Запустить юнит-тесты, убедиться что проходят
- [ ] 8.5 Создать `tests/integration/test_stage2_parser_real.py`
- [ ] 8.6 Запустить интеграционные тесты (требуется Docker или локальный marker)
- [ ] 8.7 Убедиться, что `parse_pdf()` работает на PDF из `in_pdfs/`

---

## Критерии готовности (из PLAN.md)

- [ ] Парсер корректно обрабатывает валидный научный PDF (markdown содержит секции)
- [ ] Из markdown извлекаются title, authors, abstract (если есть)
- [ ] Битый PDF → `ParseError` (не падает, не зависает)
- [ ] Парсер работает на CPU в Docker-контейнере (без GPU)

## Дополнительные критерии

- [ ] Юнит-тесты проходят без реального marker (полный мок)
- [ ] Интеграционные тесты проходят на PDF из `in_pdfs/`
- [ ] `ParsedDocument` корректно сериализуется (`.model_dump()`)
- [ ] Обработаны все edge-case'ы: пустой PDF, PDF без заголовков, PDF без авторов, PDF без abstract
- [ ] Функции извлечения метаданных возвращают безопасные значения по умолчанию (пустая строка, None, []) при отсутствии данных

---

## Риски

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| marker очень медленный на CPU (>5 мин на PDF) | Средняя | Интеграционные тесты только на малых PDF и с флагом `slow`; в юнит-тестах мокаем |
| marker падает на кириллических PDF | Низкая | marker/surya поддерживают кириллицу; протестируем на реальных `in_pdfs/` |
| Невозможно извлечь авторов эвристически | Средняя | Авторы — не критичный компонент; при неудаче возвращаем `[]` |
| Модели marker занимают много RAM (3–4 ГБ) | Высокая | Кэшируем модели на уровне модуля (`@lru_cache`); в Docker выделяем достаточно памяти |
| marker не извлекает DOI из текста (нет в markdown) | Средняя | DOI извлекается из markdown через regex; если нет — None, не ошибка |

---

## Оценка времени

| Задача | Часы |
|--------|------|
| Создание фикстур markdown | 0.5 |
| Написание юнит-тестов | 2 |
| Реализация parser.py | 3 |
| Интеграционные тесты | 1 |
| Отладка на реальных PDF | 1 |
| **Итого** | **~7.5 часов (1–2 рабочих дня)** |
