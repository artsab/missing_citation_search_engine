# SPEC: Система обнаружения пропущенных научных цитат (Missing Citation Detection)

## 1. Обзор

Система принимает научную статью в формате PDF, анализирует её и возвращает **топ-10 релевантных статей из базы, которые отсутствуют в списке литературы, но должны быть процитированы**. Каждая рекомендация сопровождается развёрнутым объяснением.

Язык статей: **русский**.
Размер базы: **~2500 статей** (директория `pdf/`).

---

## 2. Архитектура

```
POST /analyze (PDF multipart)
        │
        ▼
   1. PDF → Markdown        (marker)
        │
        ▼
   2. Reference Extraction  (LLM: извлечь список литературы из md)
        │
        ▼
   3. Claim Extraction      (LLM: посекционно, 10–20 claims)
        │
        ▼
   4. Retrieval             (Qdrant: section-level → paragraph-level)
        │
        ▼
   5. Filtering             (удаление уже процитированных)
        │
        ▼
   6. Re-ranking            (LLM-based rerank через внешний API)
        │
        ▼
   7. LLM Judge             (should_cite + confidence + reason)
        │
        ▼
   8. Explanation           (LLM: развёрнутое объяснение для каждой)
        │
        ▼
   Top-10 missing citations
```

---

## 3. Стек

| Компонент | Выбор |
|-----------|-------|
| Язык | Python 3.13+ |
| API | FastAPI (синхронный) |
| PDF → Markdown | `marker` (лучший для научных статей, структурный вывод) |
| Векторная БД | Qdrant |
| Метаданные | PostgreSQL |
| Эмбеддинги | Внешний API (через `EmbeddingClient`, OpenAI-совместимый) |
| Cross-encoder / Rerank | Внешний API (LLM-based rerank через `LLMClient`) |
| LLM | OpenAI-совместимый API (единый `LLMClient`) |
| Конфигурация | `.env` (секреты) + `config.yaml` (параметры) |
| Инфраструктура | Docker Compose (api + qdrant + postgres) |
| Менеджер пакетов | uv |

---

## 4. Pipeline — пошагово

### 4.1 Ingestion (индексация базы)

**Запуск:** CLI-скрипт `python -m app.ingest_bulk /path/to/pdf/dir`

**Шаги:**
1. Поиск всех `.pdf` в директории
2. Парсинг через `marker` → Markdown с секциями, title, authors
3. Извлечение metadata: title, abstract, authors, year, doi
4. Разбиение на чанки (два уровня):
   - **Section-level**: abstract целиком, каждая секция отдельно
   - **Paragraph-level**: 400–800 токенов, overlap 100
5. Эмбеддинг каждого чанка через внешний Embedding API (OpenAI-совместимый)
6. Сохранение векторов в Qdrant (одна коллекция, поле `chunk_type: section | paragraph`)
7. Сохранение метаданных в PostgreSQL (таблица `papers`)

**Payload в Qdrant:**
```json
{
  "paper_id": "uuid",
  "title": "Название статьи",
  "chunk_text": "текст чанка",
  "section": "abstract | introduction | methods | ...",
  "chunk_type": "section | paragraph",
  "year": 2023,
  "doi": "10.xxx/yyy",
  "authors": ["Фамилия И.О.", "..."]
}
```

**Кэширование эмбеддингов:** на диске (`.cache/{paper_id}/embeddings.json`) при индексации.

**Qdrant коллекция:**
- Название: `papers`
- Размерность вектора: определяется моделью внешнего провайдера (см. config)
- Distance: Cosine

### 4.2 PDF → Markdown (входная статья)

1. Загрузка PDF через multipart в `POST /analyze`
2. Парсинг через `marker` → Markdown

### 4.3 Reference Extraction

1. Весь md-текст отправляется LLM
2. Prompt (`app/prompts/reference_extraction.j2`): «Извлеки библиографические записи в JSON: `[{title, authors, year, doi}]`»
3. Результат используется для filtering (шаг 4.5)

### 4.4 Claim Extraction

1. Текст статьи разбивается на секции (из marker-разбора)
2. Для каждой секции (intro, related_work, methods) — отдельный LLM-вызов
3. Prompt (`app/prompts/claim_extraction.j2`): «Extract atomic scientific claims. Каждый claim — утверждение, требующее цитирования.»
4. Ограничение: 10–20 claims суммарно
5. Каждый claim: `{text, type: "method" | "background" | "result", section}`
6. Claims кэшируются in-memory (LRU) по text → embedding

### 4.5 Retrieval

Для каждого claim:
1. Embedding claim через внешний Embedding API (с инструкцией в тексте запроса)
2. Поиск в Qdrant:
   - Сначала section-level (топ-50)
   - Затем paragraph-level (топ-50)
3. Аггрегация результатов: дедупликация по `paper_id`, объединение score
4. Итоговый список: top-100 уникальных paper_id

### 4.6 Filtering

Удаление статей, которые уже процитированы во входной статье:
1. Точное совпадение по DOI
2. Fuzzy-сопоставление по названию (через `rapidfuzz`)

### 4.7 Re-ranking (LLM-based)

- Ранжирование через LLM: для каждой пары `(claim, candidate_paper.abstract)` отправляется запрос к LLM с промптом `rerank.j2`
- LLM оценивает релевантность claim'а к abstract кандидата (score 0–1)
- Оставить top-20 кандидатов

### 4.8 LLM Judge

Для каждого кандидата:
- Prompt (`app/prompts/judge.j2`): подаются claim + title + abstract + год + авторы кандидата
- Модель оценивает `should_cite`, `confidence`, `reason`
- Критерии: foundational, introduces method, provides evidence
- Фильтр: `should_cite == true` AND `confidence > 0.6`

### 4.9 Explanation

Для каждого прошедшего кандидата:
- Prompt (`app/prompts/explanation.j2`): подаются claim, title, abstract, reason от Judge
- LLM генерирует развёрнутое объяснение на русском (2–4 предложения)

### 4.10 Финальный ответ

Топ-10 кандидатов, сортировка по confidence Judge (убывание).

```json
{
  "missing_citations": [
    {
      "paper_title": "Название статьи",
      "doi": "10.xxx/yyy",
      "year": 2023,
      "authors": ["Фамилия И.О.", "..."],
      "related_claim": "текст claim'а",
      "reason": "развёрнутое объяснение",
      "confidence": 0.85
    }
  ],
  "debug": {
    "claims": [...],
    "candidates": [...],
    "filtered": [...],
    "judge_decisions": [...]
  }
}
```

Поле `debug` присутствует только при `?debug=true`.

---

## 5. API

### `GET /health`
Проверка доступности Qdrant и PostgreSQL.

### `POST /analyze?debug=true`
**Content-Type:** `multipart/form-data`
**Поле:** `file` — PDF файл

**Ответ:**
- `200` — `{ missing_citations: [...] }`
- `400` — PDF не читается (marker ошибка)
- `422` — Неверный формат запроса
- `500` — Ошибка обработки
- `503` — Qdrant или PostgreSQL недоступны

---

## 6. Модели данных

### PostgreSQL

```sql
CREATE TABLE papers (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    abstract TEXT,
    authors TEXT[],
    year INT,
    doi TEXT UNIQUE,
    source_pdf_path TEXT,
    ingested_at TIMESTAMP DEFAULT NOW(),
    chunk_count INT DEFAULT 0
);
```

**Stateless API** — история анализов не хранится.

### Pydantic (app/models/schemas.py)

```python
class Claim(BaseModel):
    text: str
    type: Literal["method", "background", "result"]
    section: str

class Reference(BaseModel):
    title: str
    authors: list[str] | None
    year: int | None
    doi: str | None

class MissingCitation(BaseModel):
    paper_title: str
    doi: str | None
    year: int | None
    authors: list[str]
    related_claim: str
    reason: str
    confidence: float

class AnalyzeResponse(BaseModel):
    missing_citations: list[MissingCitation]
    debug: dict | None = None
```

---

## 7. Конфигурация

### `.env` (секреты)
```
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
EMBEDDING_API_KEY=sk-...
EMBEDDING_BASE_URL=https://api.openai.com/v1
QDRANT_URL=http://qdrant:6333
POSTGRES_DSN=postgresql://user:pass@postgres:5432/db
```

### `config.yaml`
```yaml
llm:
  model: gpt-4o-mini
  temperature: 0.0
  max_tokens: 2048

embedding:
  model: text-embedding-3-small

rerank:
  model: gpt-4o-mini

pipeline:
  max_claims: 20
  top_k_retrieval: 100
  top_k_rerank: 20
  top_k_output: 10
  confidence_threshold: 0.6

chunking:
  paragraph_size: 500
  paragraph_overlap: 100

logging:
  level: INFO
  format: json   # json | text
```

---

## 8. LLMClient

Единый клиент для OpenAI-совместимых API:

```python
@dataclass
class LLMResponse:
    content: str
    parsed_json: dict | None
    tokens_in: int
    tokens_out: int

class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str): ...
    
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> LLMResponse: ...
```

Prompt-шаблоны в `app/prompts/` (Jinja2):
- `claim_extraction.j2`
- `reference_extraction.j2`
- `judge.j2`
- `explanation.j2`
- `rerank.j2`

---

## 9. Обработка ошибок

| Ситуация | Ответ |
|----------|-------|
| Битый PDF (marker не смог) | 400 |
| LLM не вернула ожидаемый JSON | Retry ×1, затем 500 |
| Пустой retrieval | 200, `missing_citations: []` |
| Все кандидаты отфильтрованы | 200, `missing_citations: []` |
| Judge вернул невалидный JSON | Skip кандидата, retry с temperature=0 |
| Qdrant недоступен | 503 |
| PostgreSQL недоступен | 503 |

Каждый запрос получает `request_id` (UUID), прошитый во все логи.

---

## 10. Логирование

- `structlog` (JSON в prod, текстовый в dev)
- Уровни: DEBUG (каждый этап), INFO (ключевые шаги), ERROR (ошибки)
- `request_id` во всех записях одного запроса
- Дебаг-режим: `?debug=true` добавляет `debug` объект в ответ

---

## 11. Структура проекта

```
project/
├── app/
│   ├── main.py                  # FastAPI entrypoint
│   ├── config.py                # Загрузка .env + config.yaml
│   │
│   ├── ingestion/
│   │   ├── parser.py            # marker wrapper (PDF → MD + metadata)
│   │   ├── chunker.py           # Section-level + paragraph-level
│   │   ├── embedder.py          # Внешний Embedding API + LRU кэш
│   │   └── indexer.py           # Загрузка в Qdrant + PostgreSQL
│   │
│   ├── pipeline/
│   │   ├── claim_extractor.py   # LLM, посекционно
│   │   ├── reference_extractor.py # LLM, из md → structured refs
│   │   ├── retriever.py         # Qdrant: section + paragraph
│   │   ├── filter.py            # DOI exact + title fuzzy
│   │   ├── reranker.py          # LLM-based rerank
│   │   ├── judge.py             # LLM should_cite оценка
│   │   ├── explainer.py         # LLM развёрнутое объяснение
│   │   └── orchestrator.py      # Сборка pipeline для /analyze
│   │
│   ├── models/
│   │   └── schemas.py           # Pydantic модели
│   │
│   ├── llm/
│   │   ├── client.py            # LLMClient (OpenAI-совместимый)
│   │   └── response.py          # LLMResponse dataclass
│   │
│   ├── db/
│   │   ├── postgres.py          # PostgreSQL async client
│   │   └── qdrant.py            # Qdrant client wrapper
│   │
│   ├── prompts/                  # Jinja2 шаблоны
│   │   ├── claim_extraction.j2
│   │   ├── reference_extraction.j2
│   │   ├── judge.j2
│   │   ├── explanation.j2
│   │   └── rerank.j2
│   │
│   ├── utils/
│   │   ├── text.py              # Text helpers
│   │   ├── citations.py         # DOI/title matching
│   │   └── logging.py           # structlog setup + request_id
│   │
│   ├── ingest_bulk.py           # CLI: python -m app.ingest_bulk
│   │
│   └── logging_config.py        # Конфигурация structlog
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── in_pdfs/                      # Тестовые PDF (несколько файлов)
├── pdf/                          # 2500 PDF для базы
│
├── config.yaml
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── SPEC.md
```

---

## 12. Docker Compose

```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    depends_on: [qdrant, postgres]
    environment:
      - QDRANT_URL=http://qdrant:6333
      - POSTGRES_DSN=postgresql://user:pass@postgres:5432/db
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./.cache:/app/.cache

  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]
    volumes:
      - qdrant_data:/qdrant/storage

  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: db
    ports: ["5432:5432"]
    volumes:
      - pg_data:/var/lib/postgresql/data

volumes:
  qdrant_data:
  pg_data:
```

---

## 13. Зависимости (pyproject.toml)

```
marker-pdf>=1.0
fastapi
uvicorn
python-multipart
pydantic>=2
pydantic-settings
qdrant-client
asyncpg
sqlalchemy[asyncio]
pyyaml
jinja2
httpx
structlog
rapidfuzz
cachetools
pytest
pytest-asyncio
```

---

## 14. Порядок реализации

| Шаг | Что |
|-----|-----|
| 1 | Docker Compose: Qdrant + Postgres. Конфиги, health check |
| 2 | PDF → Markdown: marker-парсер |
| 3 | Chunker + Embedder + Indexer (Qdrant + PostgreSQL) |
| 4 | CLI `python -m app.ingest_bulk` — индексация 2500 PDF |
| 5 | FastAPI скелет, Pydantic модели |
| 6 | LLMClient + промпты |
| 7 | Claim Extraction |
| 8 | Reference Extraction |
| 9 | Retrieval (двухуровневый) |
| 10 | Filter (dedup) |
| 11 | LLM-based rerank |
| 12 | LLM Judge |
| 13 | LLM Explanation |
| 14 | Orchestrator — сборка `POST /analyze` |
| 15 | Debug режим, логирование |
| 16 | Unit-тесты (с моками) |
| 17 | Интеграционные тесты |
| 18 | E2E тест |

---

## 15. Критерии готовности

- [ ] CLI индексирует 2500 PDF из `pdf/`
- [ ] `POST /analyze` принимает PDF и возвращает топ-10 пропущенных цитат
- [ ] Находит 3–10 релевантных missing citations на статью
- [ ] Не предлагает уже процитированные работы
- [ ] Каждая рекомендация содержит развёрнутое объяснение
- [ ] `?debug=true` показывает claims, candidates, judge_decisions
- [ ] Все ошибки обрабатываются согласно матрице
- [ ] Unit + integration + e2e тесты проходят
