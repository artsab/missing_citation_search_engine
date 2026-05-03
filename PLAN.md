# PLAN: Система обнаружения пропущенных научных цитат

## Общий обзор этапов

| Этап | Название | Зависимость |
|------|----------|-------------|
| 1 | Инфраструктура и скелет проекта | — |
| 2 | PDF-парсер (marker wrapper) | Этап 1 |
| 3 | Ingestion Pipeline (чункер + эмбеддер + индексатор + CLI) | Этап 2 |
| 4 | LLM-инфраструктура (клиент + промпты + логирование) | Этап 1 |
| 5 | Extraction: Reference & Claim | Этапы 3, 4 |
| 6 | Retrieval + Filtering | Этапы 3, 5 |
| 7 | Re-ranking + LLM Judge + Explainer | Этапы 4, 6 |
| 8 | Orchestrator + POST /analyze + Debug | Этапы 5, 6, 7 |
| 9 | Тестирование (unit, интеграционное, E2E) | Этап 8 |

---

## Этап 1: Инфраструктура и скелет проекта

### Цель
Поднять Docker-окружение (Qdrant + PostgreSQL), создать структуру проекта, настроить конфигурацию и health check.

### Задачи
1. Создать `pyproject.toml` со всеми зависимостями (uv)
2. Написать `docker-compose.yml` (qdrant + postgres)
3. Создать структуру директорий согласно спецификации
4. Реализовать `app/config.py` — загрузка `.env` + `config.yaml`
5. Реализовать Pydantic-модели (`app/models/schemas.py`)
6. Реализовать `app/db/postgres.py` — asyncpg-клиент с созданием таблиц
7. Реализовать `app/db/qdrant.py` — обёртка Qdrant-клиента, создание коллекции `papers`
8. Собрать minimal FastAPI в `app/main.py`: `GET /health` (проверка Qdrant + PostgreSQL)

### Критерии готовности
- [ ] `docker compose up` поднимает все три сервиса без ошибок
- [ ] `GET /health` возвращает `200` при доступных Qdrant и PostgreSQL
- [ ] `GET /health` возвращает `503` при недоступности Qdrant или PostgreSQL
- [ ] `POST /analyze` (заглушка) возвращает `422` без файла
- [ ] Таблица `papers` создаётся автоматически при старте API
- [ ] Коллекция `papers` в Qdrant создаётся при старте API
- [ ] `.env.example` содержит все необходимые переменные с описанием

### Автоматические тесты
```python
# tests/integration/test_stage1_infra.py

class TestHealthEndpoint:
    """Проверка GET /health"""

    async def test_health_all_services_available(self, client):
        """Qdrant и Postgres доступны → 200"""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["qdrant"] == "ok"
        assert data["database"] == "ok"

    async def test_health_qdrant_unavailable(self, client_without_qdrant):
        """Qdrant недоступен → 503"""
        response = await client_without_qdrant.get("/health")
        assert response.status_code == 503

    async def test_health_postgres_unavailable(self, client_without_postgres):
        """Postgres недоступен → 503"""
        response = await client_without_postgres.get("/health")
        assert response.status_code == 503


class TestConfig:
    """Проверка загрузки конфигурации"""

    def test_config_loads_from_yaml(self):
        """config.yaml загружается, параметры читаются"""
        ...

    def test_config_env_overrides(self, monkeypatch):
        """.env переопределяет значения из config.yaml"""
        ...

    def test_config_required_secrets(self):
        """Отсутствие LLM_API_KEY → ошибка при запуске"""
        ...


class TestPydanticModels:
    """Проверка моделей"""

    def test_claim_validation(self):
        """Claim: корректные значения type, пустой text → ошибка"""
        ...

    def test_missing_citation_validation(self):
        """MissingCitation: confidence вне [0,1] → ошибка"""
        ...

    def test_analyze_response_debug_optional(self):
        """AnalyzeResponse: debug=None допустимо"""
        ...


class TestDatabaseTables:
    """Проверка создания таблиц"""

    async def test_papers_table_exists(self, db_pool):
        """Таблица papers существует с нужными колонками"""
        ...

    async def test_papers_doi_unique_constraint(self, db_pool):
        """UNIQUE constraint на doi работает"""
        ...


class TestQdrantCollection:
    """Проверка коллекции Qdrant"""

    async def test_collection_exists(self, qdrant_client):
        """Коллекция papers создана"""
        ...

    async def test_collection_vector_size(self, qdrant_client):
        """Размерность вектора = 1024"""
        ...

    async def test_collection_distance_metric(self, qdrant_client):
        """Метрика = Cosine"""
        ...
```

---

## Этап 2: PDF-парсер (marker wrapper)

### Цель
Реализовать конвертацию PDF → Markdown с извлечением метаданных через `marker`.

### Задачи
1. Изучить API `marker-pdf` (Python-библиотека)
2. Реализовать `app/ingestion/parser.py`:
   - `parse_pdf(path: str) -> ParsedDocument` — PDF → Markdown + метаданные
   - `ParsedDocument`: markdown, sections (список секций), title, abstract, authors, year, doi
3. Извлечение abstract: первая секция, если title содержит «аннотация» / «abstract»
4. Обработка ошибок: битый PDF → `ParseError`
5. Сохранить 2–3 тестовых PDF в `in_pdfs/`

### Критерии готовности
- [ ] Парсер корректно обрабатывает валидный научный PDF (markdown содержит секции)
- [ ] Из markdown извлекаются title, authors, abstract (если есть)
- [ ] Битый PDF → `ParseError` (не падает, не зависает)
- [ ] Парсер работает на CPU в Docker-контейнере (без GPU)

### Автоматические тесты
```python
# tests/unit/test_stage2_parser.py

class TestMarkerParser:
    """Юнит-тесты парсера с моком marker"""

    def test_parse_valid_pdf_returns_markdown(self, mock_marker, sample_pdf_path):
        """Валидный PDF → ParsedDocument с markdown и секциями"""
        doc = parse_pdf(sample_pdf_path)
        assert doc.markdown
        assert len(doc.sections) > 0
        assert doc.title

    def test_parse_extracts_title(self, mock_marker):
        """Заголовок извлекается корректно"""
        ...

    def test_parse_extracts_authors(self, mock_marker):
        """Авторы извлекаются списком"""
        ...

    def test_parse_extracts_abstract(self, mock_marker):
        """Abstract извлекается, если секция называется 'аннотация'"""
        ...

    def test_parse_corrupted_pdf_raises_parse_error(self, mock_marker, corrupt_pdf_path):
        """Битый PDF → ParseError"""
        with pytest.raises(ParseError):
            parse_pdf(corrupt_pdf_path)

    def test_parse_empty_pdf(self, mock_marker, empty_pdf_path):
        """Пустой PDF (без текста) → пустой markdown, но не ошибка"""
        ...


# tests/integration/test_stage2_parser_real.py

class TestMarkerParserIntegration:
    """Интеграционные тесты на реальных PDF (in_pdfs/)"""

    def test_parse_real_scientific_pdf(self, real_pdf_path):
        """Реальный научный PDF → парсится без ошибок, есть текст"""
        doc = parse_pdf(real_pdf_path)
        assert len(doc.markdown) > 200  # минимум символов
        assert doc.title

    def test_parse_all_test_pdfs(self, all_test_pdf_paths):
        """Все тестовые PDF в in_pdfs/ парсятся без ошибок"""
        for path in all_test_pdf_paths:
            doc = parse_pdf(path)
            assert doc.markdown
```

---

## Этап 3: Ingestion Pipeline (чункер + эмбеддер + индексатор + CLI)

### Цель
Реализовать полный пайплайн индексации: PDF → чанки → эмбеддинги → Qdrant + PostgreSQL.

### Задачи
1. Реализовать `app/ingestion/chunker.py`:
   - `chunk_document(doc: ParsedDocument) -> list[Chunk]`
   - Section-level: abstract целиком, каждая секция отдельно
   - Paragraph-level: 400–800 токенов, overlap 100
   - Каждый чанк: `{paper_id, title, chunk_text, section, chunk_type, year, doi, authors}`
2. Реализовать `app/ingestion/embedder.py`:
   - `encode(texts: list[str], instruction: str | None) -> np.ndarray`
   - Модель `intfloat/multilingual-e5-large-instruct`
   - LRU-кэш эмбеддингов in-memory по `text → embedding`
3. Реализовать `app/ingestion/indexer.py`:
   - `index_paper(doc: ParsedDocument)` — полный цикл: чанкинг → эмбеддинг → Qdrant + PostgreSQL
   - Сохранение метаданных в PostgreSQL (таблица `papers`)
   - Upsert векторов в Qdrant
4. Реализовать CLI `app/ingest_bulk.py`:
   - Рекурсивный обход `pdf/`
   - Параллельная обработка (ThreadPoolExecutor, 2–4 воркера)
   - Progress bar (tqdm)
   - Кэширование эмбеддингов на диск: `.cache/{paper_id}/embeddings.json`
   - Skip уже проиндексированных (проверка по DOI в PostgreSQL)

### Критерии готовности
- [ ] Чанкер создаёт ≥2 чанков на документ (section + paragraphs)
- [ ] Paragraph-чанки не превышают 800 токенов
- [ ] Эмбеддер возвращает вектор размерности 1024
- [ ] LRU-кэш корректно попадает в кэш при повторном запросе
- [ ] Индексатор сохраняет строку в PostgreSQL и N векторов в Qdrant
- [ ] Повторный запуск CLI не переиндексирует уже обработанные PDF (проверка по DOI)
- [ ] CLI обрабатывает 2500 PDF без падения (можно на 50 PDF проверить)
- [ ] Эмбеддинги кэшируются на диск и переиспользуются

### Автоматические тесты
```python
# tests/unit/test_stage3_chunker.py

class TestChunker:
    """Юнит-тесты чанкера"""

    def test_section_chunks_created(self, parsed_doc):
        """Каждая секция → отдельный section-level чанк"""
        chunks = chunk_document(parsed_doc)
        section_chunks = [c for c in chunks if c.chunk_type == "section"]
        assert len(section_chunks) >= len(parsed_doc.sections)

    def test_paragraph_chunks_created(self, parsed_doc):
        """Текст разбивается на paragraph-level чанки"""
        ...

    def test_paragraph_chunk_token_limit(self, parsed_doc, tokenizer):
        """Ни один paragraph-чанк не превышает 800 токенов"""
        ...

    def test_paragraph_overlap(self, parsed_doc):
        """Соседние paragraph-чанки имеют overlap ~100 токенов"""
        ...

    def test_chunk_contains_paper_id(self, parsed_doc):
        """Все чанки содержат paper_id исходного документа"""
        ...

    def test_chunk_contains_metadata(self, parsed_doc):
        """Чанки содержат title, year, doi, authors"""
        ...


# tests/unit/test_stage3_embedder.py

class TestEmbedder:
    """Юнит-тесты эмбеддера (с моком sentence-transformers)"""

    def test_embed_returns_correct_shape(self, mock_model):
        """5 текстов → (5, 1024)"""
        embeddings = encode(["text1", "text2", "text3", "text4", "text5"])
        assert embeddings.shape == (5, 1024)

    def test_embed_empty_list_returns_empty(self, mock_model):
        """Пустой список → (0, 1024)"""
        ...

    def test_embed_single_text(self, mock_model):
        """Один текст → (1, 1024)"""
        ...

    def test_lru_cache_hit(self, embedder_with_cache):
        """Повторный вызов с тем же текстом → кэш (меньше вызовов модели)"""
        ...


# tests/unit/test_stage3_indexer.py

class TestIndexer:
    """Юнит-тесты индексатора"""

    async def test_index_paper_stores_in_postgres(self, parsed_doc, mock_db, mock_qdrant):
        """После индексации запись в PostgreSQL создана"""
        await index_paper(parsed_doc)
        mock_db.insert_paper.assert_called_once()

    async def test_index_paper_stores_in_qdrant(self, parsed_doc, mock_db, mock_qdrant):
        """После индексации векторы в Qdrant загружены"""
        await index_paper(parsed_doc)
        mock_qdrant.upsert.assert_called()

    async def test_index_paper_upserts_correct_chunk_count(self, parsed_doc, mock_db, mock_qdrant):
        """Количество upsert-точек = количеству чанков"""
        ...


# tests/integration/test_stage3_ingestion.py

class TestIngestionIntegration:
    """Интеграционные тесты: реальный Qdrant + PostgreSQL"""

    async def test_full_ingestion_cycle(self, db_pool, qdrant_client, real_pdf_path):
        """Полный цикл: PDF → индексация → данные в БД и Qdrant"""
        ...

    async def test_ingestion_idempotent(self, db_pool, qdrant_client, real_pdf_path):
        """Повторная индексация того же PDF → не дублирует"""
        ...

    async def test_search_after_ingestion(self, db_pool, qdrant_client, real_pdf_path):
        """После индексации поиск возвращает этот документ"""
        ...


# tests/unit/test_stage3_cli.py

class TestIngestBulkCLI:
    """Тесты CLI (с моками)"""

    def test_cli_finds_all_pdfs(self, tmp_pdf_dir, mock_indexer):
        """CLI находит все PDF в директории"""
        ...

    def test_cli_skips_indexed_papers(self, tmp_pdf_dir, mock_indexer):
        """CLI пропускает PDF с DOI, который уже в PostgreSQL"""
        ...

    def test_cli_handles_parse_errors_gracefully(self, tmp_pdf_dir, mock_indexer):
        """Битый PDF в директории → CLI логирует ошибку, продолжает"""
        ...
```

---

## Этап 4: LLM-инфраструктура (клиент + промпты + логирование)

### Цель
Создать единый LLM-клиент для OpenAI-совместимых API, написать Jinja2-промпты, настроить структурированное логирование.

### Задачи
1. Реализовать `app/llm/response.py` — `LLMResponse` dataclass
2. Реализовать `app/llm/client.py` — `LLMClient`:
   - `generate(prompt, system_prompt, temperature, max_tokens) -> LLMResponse`
   - Автоматический retry (1 раз) при ошибках парсинга JSON
   - `parsed_json` — попытка распарсить `content` как JSON
   - Счётчики токенов (из response headers OpenAI)
3. Написать Jinja2-промпты в `app/prompts/`:
   - `reference_extraction.j2`
   - `claim_extraction.j2`
   - `judge.j2`
   - `explanation.j2`
4. Реализовать `app/logging_config.py` — structlog (JSON в prod, text в dev)
5. Реализовать `app/utils/logging.py` — context manager для `request_id`
6. Написать `tests/unit/fixtures/llm_responses.py` — JSON-фикстуры ответов LLM

### Критерии готовности
- [ ] `LLMClient.generate()` отправляет запрос к API и возвращает `LLMResponse`
- [ ] `LLMResponse.parsed_json` — корректно парсит JSON из ответа
- [ ] При JSON-parse-error — retry (1 раз), затем ошибка
- [ ] Промпты рендерятся через Jinja2 без ошибок
- [ ] Лог содержит `request_id`, уровень, timestamp, message
- [ ] В dev-режиме логи текстовые, читаемые

### Автоматические тесты
```python
# tests/unit/test_stage4_llm_client.py

class TestLLMClient:
    """Юнит-тесты LLMClient с моком httpx"""

    async def test_generate_returns_llm_response(self, mock_httpx, llm_client):
        """Успешный запрос → LLMResponse с content"""
        response = await llm_client.generate("Test prompt")
        assert isinstance(response, LLMResponse)
        assert response.content

    async def test_generate_parses_json(self, mock_httpx_json_response, llm_client):
        """Ответ в JSON → parsed_json заполнен"""
        ...

    async def test_generate_retry_on_json_parse_error(self, mock_httpx_bad_json_then_good, llm_client):
        """Первый ответ — не JSON, второй — JSON → retry, parsed_json есть"""
        ...

    async def test_generate_custom_temperature(self, mock_httpx, llm_client):
        """Параметр temperature передаётся в API"""
        ...

    async def test_generate_handles_api_error(self, mock_httpx_500, llm_client):
        """Ошибка API → исключение"""
        ...

    async def test_generate_counts_tokens(self, mock_httpx_with_usage, llm_client):
        """tokens_in/tokens_out извлекаются из ответа"""
        ...


# tests/unit/test_stage4_prompts.py

class TestPrompts:
    """Проверка рендеринга промптов"""

    def test_reference_extraction_renders(self, jinja_env):
        """Шаблон reference_extraction.j2 рендерится с markdown"""
        ...

    def test_claim_extraction_renders(self, jinja_env):
        """Шаблон claim_extraction.j2 рендерится с секцией"""
        ...

    def test_judge_renders(self, jinja_env):
        """Шаблон judge.j2 рендерится с claim + candidate"""
        ...

    def test_explanation_renders(self, jinja_env):
        """Шаблон explanation.j2 рендерится с reason"""
        ...


# tests/unit/test_stage4_logging.py

class TestLogging:
    """Проверка логирования"""

    def test_request_id_in_logs(self, log_output):
        """request_id присутствует в логах"""
        ...

    def test_json_format_in_production(self, monkeypatch, log_output):
        """В prod-режиме логи в JSON"""
        ...

    def test_text_format_in_development(self, monkeypatch, log_output):
        """В dev-режиме логи текстовые"""
        ...
```

---

## Этап 5: Extraction — Reference & Claim

### Цель
Реализовать извлечение списка литературы (references) и утверждений (claims) из markdown-текста через LLM.

### Задачи
1. Реализовать `app/pipeline/reference_extractor.py`:
   - `extract_references(markdown: str) -> list[Reference]`
   - LLM-вызов с промптом `reference_extraction.j2`
   - Парсинг JSON-ответа → список Reference
2. Реализовать `app/pipeline/claim_extractor.py`:
   - `extract_claims(sections: list[Section]) -> list[Claim]`
   - Для каждой секции (intro, related_work, methods) — отдельный LLM-вызов
   - Промпт `claim_extraction.j2`
   - Ограничение: 10–20 claims суммарно по всем секциям
   - Тип claim: method, background, result
3. Обработка ошибок парсинга LLM-ответа: retry, fallback

### Критерии готовности
- [ ] `extract_references` возвращает список Reference (title, authors, year, doi)
- [ ] `extract_claims` возвращает 10–20 claims с типами и секциями
- [ ] Claims распределены по секциям (не все из одной)
- [ ] Каждый claim — осмысленное утверждение (не пустое, не обрывок)
- [ ] При ошибке парсинга JSON от LLM — retry, затем исключение

### Автоматические тесты
```python
# tests/unit/test_stage5_reference_extractor.py

class TestReferenceExtractor:
    """Юнит-тесты reference extractor с моком LLMClient"""

    async def test_extract_references_from_markdown(self, mock_llm, markdown_with_refs):
        """Из markdown с библиографией → список Reference"""
        refs = await extract_references(markdown_with_refs)
        assert len(refs) > 0
        assert refs[0].title

    async def test_extract_no_references_returns_empty(self, mock_llm_empty, markdown_no_refs):
        """Статья без библиографии → []"""
        ...

    async def test_extract_handles_malformed_json(self, mock_llm_bad_json):
        """LLM вернул не JSON → исключение после retry"""
        ...

    async def test_extract_fills_all_fields_when_present(self, mock_llm, markdown_full_refs):
        """DOI, year, authors — заполняются, если есть в ответе LLM"""
        ...


# tests/unit/test_stage5_claim_extractor.py

class TestClaimExtractor:
    """Юнит-тесты claim extractor с моком LLMClient"""

    async def test_extract_claims_from_sections(self, mock_llm, sections_with_content):
        """Из секций → 10–20 claims"""
        claims = await extract_claims(sections_with_content)
        assert 10 <= len(claims) <= 20

    async def test_claims_have_types(self, mock_llm, sections):
        """Каждый claim имеет валидный type"""
        ...

    async def test_claims_have_sections(self, mock_llm, sections):
        """Каждый claim содержит section"""
        ...

    async def test_extract_handles_empty_sections(self, mock_llm, empty_sections):
        """Пустые секции → меньше claims, но не ошибка"""
        ...

    async def test_claims_are_unique_enough(self, mock_llm, sections):
        """Claims не дублируются (минимум 80% уникальных)"""
        ...


# tests/integration/test_stage5_extraction_real.py

class TestExtractionIntegration:
    """Интеграционные тесты с реальным LLM (опционально, за флагом)"""

    @pytest.mark.llm
    async def test_real_llm_reference_extraction(self, llm_client, real_markdown):
        """Реальный LLM извлекает references"""
        ...

    @pytest.mark.llm
    async def test_real_llm_claim_extraction(self, llm_client, real_sections):
        """Реальный LLM извлекает claims"""
        ...
```

---

## Этап 6: Retrieval + Filtering

### Цель
Реализовать двухуровневый поиск в Qdrant и фильтрацию уже процитированных статей.

### Задачи
1. Реализовать `app/pipeline/retriever.py`:
   - `retrieve(claims: list[Claim]) -> list[Candidate]`
   - Для каждого claim: эмбеддинг → поиск в Qdrant
   - Двухуровневый: section-level (top-50) → paragraph-level (top-50)
   - Дедупликация по `paper_id`, агрегация score (max/avg)
   - Итог: top-100 уникальных paper_id
2. Реализовать `app/utils/citations.py` — DOI exact match + fuzzy title match
3. Реализовать `app/pipeline/filter.py`:
   - `filter_candidates(candidates: list[Candidate], references: list[Reference]) -> list[Candidate]`
   - Точное совпадение DOI
   - Fuzzy-сопоставление названий через `rapidfuzz` (threshold=85)

### Критерии готовности
- [ ] Retrieval возвращает список Candidate с score
- [ ] Дедупликация: нет дублей по paper_id
- [ ] Фильтр удаляет точные совпадения по DOI
- [ ] Фильтр удаляет близкие совпадения по названию (fuzzy > 85%)
- [ ] Пустой claims → пустой результат retrieval
- [ ] Пустой список references → фильтр не удаляет ничего

### Автоматические тесты
```python
# tests/unit/test_stage6_retriever.py

class TestRetriever:
    """Юнит-тесты retriever с моком Qdrant"""

    async def test_retrieve_returns_candidates(self, mock_qdrant, sample_claims):
        """Claims → список Candidate"""
        candidates = await retrieve(sample_claims)
        assert len(candidates) > 0
        assert all(c.paper_id for c in candidates)

    async def test_retrieve_deduplicates_by_paper_id(self, mock_qdrant_same_paper, sample_claims):
        """Qdrant вернул один paper_id в нескольких чанках → один Candidate"""
        ...

    async def test_retrieve_respects_limit(self, mock_qdrant, sample_claims):
        """Результат ≤ top_k_retrieval (100)"""
        ...

    async def test_retrieve_empty_claims(self, mock_qdrant):
        """Пустой список claims → []"""
        ...

    async def test_retrieve_aggregation(self, mock_qdrant, sample_claims):
        """Несколько claims → score агрегирован (max)"""
        ...


# tests/unit/test_stage6_filter.py

class TestFilter:
    """Юнит-тесты фильтра"""

    def test_filter_by_doi_exact_match(self):
        """DOI совпадает → кандидат удалён"""
        ...

    def test_filter_by_title_fuzzy_match(self):
        """Название похоже на 86% → кандидат удалён"""
        ...

    def test_filter_by_title_fuzzy_no_match(self):
        """Название похоже на 70% → кандидат оставлен"""
        ...

    def test_filter_empty_references(self):
        """Нет references → все кандидаты оставлены"""
        ...

    def test_filter_all_candidates_removed(self):
        """Все кандидаты отфильтрованы → []"""
        ...

    def test_doi_none_skipped(self, candidates_without_doi):
        """DOI=None у reference или candidate → пропускаем"""
        ...


# tests/unit/test_stage6_citations_utils.py

class TestCitationsUtils:
    """Юнит-тесты утилит сравнения"""

    def test_doi_match_normalized(self):
        """DOI с разным регистром/префиксом → match"""
        ...

    def test_doi_no_match(self):
        """Разные DOI → no match"""
        ...

    def test_title_fuzzy_identical(self):
        """Идентичные названия → score 100"""
        ...

    def test_title_fuzzy_typo(self):
        """Опечатка в 1-2 буквы → score > 85"""
        ...

    def test_title_fuzzy_different(self):
        """Совсем разные названия → score < 50"""
        ...
```

---

## Этап 7: Re-ranking + LLM Judge + Explainer

### Цель
Реализовать cross-encoder реранкинг, LLM-оценку необходимости цитирования и генерацию объяснений.

### Задачи
1. Реализовать `app/pipeline/reranker.py`:
   - `rerank(claims: list[Claim], candidates: list[Candidate]) -> list[Candidate]`
   - Модель `DiTy/cross-encoder-russian-msmarco`
   - Пары `(claim.text, candidate.abstract)` → score
   - Оставить top-20
2. Реализовать `app/pipeline/judge.py`:
   - `judge(claims: list[Claim], candidates: list[Candidate]) -> list[JudgeDecision]`
   - LLM-вызов с `judge.j2`: claim + title + abstract + year + authors
   - `JudgeDecision`: `{candidate, should_cite, confidence, reason}`
   - Фильтрация: `should_cite == True` AND `confidence > 0.6`
3. Реализовать `app/pipeline/explainer.py`:
   - `explain(decisions: list[JudgeDecision]) -> list[CandidateWithExplanation]`
   - LLM-вызов с `explanation.j2`: claim + title + abstract + judge_reason
   - Добавление поля `reason` (2–4 предложения на русском)

### Критерии готовности
- [ ] Ререйнкер возвращает ≤20 кандидатов
- [ ] Cross-encoder отрабатывает без GPU (CPU, медленно — ок)
- [ ] Judge возвращает `should_cite` + `confidence` + `reason` для каждого
- [ ] Judge-фильтр оставляет только should_cite=True + confidence > 0.6
- [ ] Explainer генерирует 2–4 предложения на русском
- [ ] После judge не осталось кандидатов → пустой результат, не ошибка

### Автоматические тесты
```python
# tests/unit/test_stage7_reranker.py

class TestReranker:
    """Юнит-тесты реранкера с моком cross-encoder"""

    async def test_rerank_returns_top20(self, mock_cross_encoder, claims, candidates_100):
        """100 кандидатов → ≤20"""
        result = await rerank(claims, candidates_100)
        assert len(result) <= 20

    async def test_rerank_sorts_by_score(self, mock_cross_encoder, claims, candidates):
        """Результат отсортирован по убыванию score"""
        ...

    async def test_rerank_preserves_paper_id(self, mock_cross_encoder, claims, candidates):
        """paper_id не теряется при реранкинге"""
        ...


# tests/unit/test_stage7_judge.py

class TestJudge:
    """Юнит-тесты judge с моком LLMClient"""

    async def test_judge_returns_decisions(self, mock_llm, claims, candidates):
        """На каждого кандидата → JudgeDecision"""
        decisions = await judge(claims, candidates)
        assert len(decisions) == len(candidates)

    async def test_judge_filters_by_confidence(self, mock_llm, claims, candidates):
        """Конфиденс < 0.6 → кандидат отфильтрован"""
        ...

    async def test_judge_filters_by_should_cite(self, mock_llm, claims, candidates):
        """should_cite = False → кандидат отфильтрован"""
        ...

    async def test_judge_empty_candidates(self, mock_llm, claims):
        """Пустой список кандидатов → []"""
        ...


# tests/unit/test_stage7_explainer.py

class TestExplainer:
    """Юнит-тесты explainer с моком LLMClient"""

    async def test_explain_generates_reason(self, mock_llm, decisions):
        """Каждое решение получает reason (строка, 2+ предложения)"""
        result = await explain(decisions)
        assert all(r.reason for r in result)
        assert all(len(r.reason.split(".")) >= 2 for r in result)

    async def test_explain_in_russian(self, mock_llm_russian, decisions):
        """Reason на русском языке (содержит кириллицу)"""
        ...

    async def test_explain_empty_decisions(self, mock_llm):
        """Пустой список → []"""
        ...
```

---

## Этап 8: Orchestrator + POST /analyze + Debug

### Цель
Собрать полный пайплайн `POST /analyze`, добавить debug-режим и обработку всех ошибок согласно матрице из SPEC.

### Задачи
1. Реализовать `app/pipeline/orchestrator.py`:
   - `analyze_pdf(pdf_bytes: bytes, debug: bool) -> AnalyzeResponse`
   - Сборка всего pipeline: parse → references → claims → retrieve → filter → rerank → judge → explain → top-10
   - Debug-режим: сохраняет промежуточные результаты в `debug`
2. Реализовать endpoint `POST /analyze` в `app/main.py`
3. Обработка ошибок согласно матрице:
   - Битый PDF → 400
   - Неверный формат → 422
   - LLM JSON error (после retry) → 500
   - Qdrant/Postgres недоступны → 503
   - Пустой retrieval/фильтр/judge → 200, `missing_citations: []`
4. `request_id` в каждом запросе, прошитый во все логи

### Критерии готовности
- [ ] `POST /analyze` с валидным PDF → 200, `missing_citations` (0–10 шт.)
- [ ] `POST /analyze?debug=true` → ответ содержит `debug` с claims, candidates, judge_decisions
- [ ] `POST /analyze` без `?debug` → `debug` отсутствует в ответе
- [ ] Все коды ошибок соответствуют матрице
- [ ] Логи содержат `request_id` на всех этапах одного запроса
- [ ] Pipeline не падает на любом этапе — ошибки обрабатываются gracefully

### Автоматические тесты
```python
# tests/integration/test_stage8_api.py

class TestAnalyzeEndpoint:
    """Интеграционные тесты POST /analyze"""

    async def test_analyze_valid_pdf_returns_200(self, client, valid_pdf, mock_indexed_db):
        """Валидный PDF, проиндексированная база → 200 + missing_citations"""
        response = await client.post("/analyze", files={"file": valid_pdf})
        assert response.status_code == 200
        data = response.json()
        assert "missing_citations" in data
        assert isinstance(data["missing_citations"], list)
        assert len(data["missing_citations"]) <= 10

    async def test_analyze_debug_mode(self, client, valid_pdf, mock_indexed_db):
        """?debug=true → debug в ответе"""
        response = await client.post("/analyze?debug=true", files={"file": valid_pdf})
        assert response.status_code == 200
        data = response.json()
        assert "debug" in data
        assert "claims" in data["debug"]
        assert "candidates" in data["debug"]

    async def test_analyze_no_debug_by_default(self, client, valid_pdf, mock_indexed_db):
        """Без ?debug → debug=None/отсутствует"""
        ...

    async def test_analyze_corrupted_pdf_returns_400(self, client, corrupt_pdf):
        """Битый PDF → 400"""
        ...

    async def test_analyze_no_file_returns_422(self, client):
        """POST без файла → 422"""
        ...

    async def test_analyze_wrong_content_type_returns_422(self, client):
        """Не multipart → 422"""
        ...

    async def test_analyze_qdrant_unavailable_returns_503(self, client_no_qdrant, valid_pdf):
        """Qdrant недоступен → 503"""
        ...

    async def test_analyze_empty_database_returns_empty(self, client, valid_pdf, empty_db):
        """Пустая база → 200, missing_citations: []"""
        ...


class TestOrchestrator:
    """Юнит-тесты оркестратора с моками"""

    async def test_orchestrator_full_pipeline(self, mocker):
        """Полный пайплайн отрабатывает без ошибок"""
        ...

    async def test_orchestrator_top_10_limit(self, mocker):
        """Даже при 20 прошедших judge → возвращается ровно 10"""
        ...

    async def test_orchestrator_request_id_in_logs(self, mocker, log_capture):
        """Все логи в рамках одного вызова содержат одинаковый request_id"""
        ...
```

---

## Этап 9: Тестирование (unit, интеграционное, E2E)

### Цель
Полное покрытие системы тестами: юнит (моки), интеграционные (реальные сервисы), end-to-end.

### Задачи
1. Юнит-тесты (моки LLM, Qdrant, PostgreSQL):
   - Все модули `app/pipeline/`
   - Все модули `app/ingestion/`
   - `app/llm/client.py`
   - `app/utils/` (citations, text, logging)
   - Pydantic-модели
   - Конфигурация
2. Интеграционные тесты (реальные Qdrant + PostgreSQL):
   - Health check
   - Ingestion (парсер + чанкер + эмбеддер + индексатор)
   - Retrieval (с реальными эмбеддингами)
   - API: все HTTP-статусы
   - LLM (опционально, за `@pytest.mark.llm`)
3. E2E-тест:
   - CLI индексирует 10 PDF из `in_pdfs/`
   - `POST /analyze` принимает тестовый PDF
   - Возвращает непустой `missing_citations` (если в базе есть похожие)
   - Проверка формата ответа
4. Coverage report: `pytest --cov=app --cov-report=term`

### Критерии готовности
- [ ] Все юнит-тесты проходят без реальных зависимостей
- [ ] Все интеграционные тесты проходят с Docker (qdrant + postgres)
- [ ] E2E-тест проходит полный цикл от CLI до API-ответа
- [ ] Code coverage ≥ 80%
- [ ] `pytest` без маркеров (unit + integration) проходит в CI

### Автоматические тесты
```python
# tests/e2e/test_e2e.py

class TestEndToEnd:
    """Сквозной тест: индексация → анализ"""

    async def test_full_cycle(self, docker_services, test_pdfs_dir, sample_query_pdf):
        """
        1. Запустить ingest_bulk на in_pdfs/ (10 PDF)
        2. POST /analyze с тестовым PDF
        3. Проверить ответ: missing_citations, confidence, reason
        """
        # Arrange: проиндексировать тестовую базу
        result = subprocess.run([
            "python", "-m", "app.ingest_bulk", str(test_pdfs_dir)
        ], capture_output=True, text=True)
        assert result.returncode == 0

        # Act: анализировать новый PDF
        async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
            with open(sample_query_pdf, "rb") as f:
                response = await client.post(
                    "/analyze?debug=true",
                    files={"file": f}
                )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "missing_citations" in data
        assert "debug" in data

        for cit in data["missing_citations"]:
            assert cit["paper_title"]
            assert cit["reason"]
            assert 0 <= cit["confidence"] <= 1
            assert cit["related_claim"]
            assert isinstance(cit["authors"], list)


# tests/conftest.py (ключевые фикстуры)

@pytest.fixture(scope="session")
def docker_services():
    """Запуск docker-compose для тестов"""
    ...

@pytest.fixture
async def client():
    """HTTP-клиент для тестового FastAPI"""
    ...

@pytest.fixture
async def db_pool():
    """Connection pool к тестовому PostgreSQL"""
    ...

@pytest.fixture
async def qdrant_client():
    """Клиент тестового Qdrant"""
    ...
```

---

## Сводная таблица: этапы и ключевые метрики

| Этап | Расчётная длительность | Тестов | Ключевой риск |
|------|----------------------|--------|---------------|
| 1. Инфраструктура | 1–2 дня | 10+ | Не поднять Docker на CI |
| 2. PDF-парсер | 1–2 дня | 8+ | marker не парсит конкретные PDF |
| 3. Ingestion | 3–5 дней | 15+ | Эмбеддинг-модель требует много RAM на CPU |
| 4. LLM-инфра | 1–2 дня | 9+ | Формат ответа LLM нестабилен |
| 5. Extraction | 2–3 дня | 9+ | LLM hallucinates references |
| 6. Retrieval+Filter | 2–3 дня | 14+ | Qdrant-запросы медленные без оптимизации |
| 7. Re-rank+Judge | 2–3 дня | 10+ | Cross-encoder на CPU очень медленный |
| 8. Orchestrator | 2–3 дня | 11+ | Таймауты при долгой обработке |
| 9. Тестирование | 2–4 дня | финальное покрытие | Моки нереалистичны |

---

## Примечания по тестам

1. **Фикстуры LLM-ответов** хранить в `tests/unit/fixtures/llm_responses.py` — JSON-файлы с типовыми ответами для каждого промпта.
2. **Моки Qdrant** делать через `unittest.mock.AsyncMock` — не мокать `__init__`, мокать методы `.search()`, `.upsert()`.
3. **Моки PostgreSQL** — в юнит-тестах использовать `asyncpg` mock; в интеграционных — реальный контейнер.
4. **Cross-encoder в тестах:** в юнит-тестах — мок; в интеграционных — загружать модель один раз на сессию (`scope="session"`).
5. **E2E-тест** запускать отдельно (`@pytest.mark.e2e`), так как требует полного Docker-окружения и долгий.
6. **Маркеры pytest:**
   - `@pytest.mark.unit` — без зависимостей
   - `@pytest.mark.integration` — нужны Docker-сервисы
   - `@pytest.mark.llm` — нужен реальный LLM API (опционально)
   - `@pytest.mark.e2e` — полный цикл
   - `@pytest.mark.slow` — тесты >10 секунд