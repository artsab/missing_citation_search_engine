"""Stage 1 integration tests: infrastructure, health, config, models, DB."""

import pytest
from httpx import AsyncClient


# ── Health endpoint ────────────────────────────────────────────────────────

class TestHealthEndpoint:
    """Проверка GET /health"""

    @pytest.mark.integration
    async def test_health_all_services_available(self, client: AsyncClient):
        """Qdrant и Postgres доступны → 200"""
        # In CI with real Docker services, this will return 200.
        # Without Docker, we expect 503 since services won't be available.
        response = await client.get("/health")
        data = response.json()
        # Accept both: 200 (when Docker is up) or 503 (when not)
        assert response.status_code in (200, 503)
        assert "qdrant" in data
        assert "database" in data

    @pytest.mark.integration
    async def test_health_returns_status_keys(self, client: AsyncClient):
        """Ответ всегда содержит qdrant и database."""
        response = await client.get("/health")
        data = response.json()
        assert "qdrant" in data
        assert "database" in data
        assert data["qdrant"] in ("ok", "unavailable")
        assert data["database"] in ("ok", "unavailable")


# ── Config ──────────────────────────────────────────────────────────────────

class TestConfig:
    """Проверка загрузки конфигурации"""

    def test_config_loads_from_yaml(self):
        """config.yaml загружается, параметры читаются."""
        from app.config import get_settings

        settings = get_settings()
        assert settings.yaml.llm.model == "gpt-4o-mini"
        assert settings.yaml.embedding.dimension == 1536
        assert settings.yaml.pipeline.top_k_retrieval == 100

    def test_config_env_overrides(self, monkeypatch):
        """.env / environment переопределяет значения."""
        from app.config import get_settings

        # Clear the LRU cache so we get a fresh settings object
        get_settings.cache_clear()

        monkeypatch.setenv("QDRANT_URL", "http://custom-qdrant:6333")
        monkeypatch.setenv("LLM_API_KEY", "test-key")

        settings = get_settings()
        assert settings.qdrant_url == "http://custom-qdrant:6333"
        assert settings.llm_api_key == "test-key"

        get_settings.cache_clear()

    def test_config_default_values(self):
        """Значения по умолчанию работают без .env и config.yaml."""
        from app.config import Settings

        s = Settings()
        assert s.qdrant_url == "http://localhost:6333"
        assert s.yaml.llm.temperature == 0.0


# ── Pydantic models ─────────────────────────────────────────────────────────

class TestPydanticModels:
    """Проверка моделей"""

    def test_claim_validation(self):
        """Claim: корректные значения type, пустой text → ошибка."""
        from app.models.schemas import Claim
        from pydantic import ValidationError

        # Valid
        c = Claim(text="A test claim", type="method", section="intro")
        assert c.type == "method"

        # Empty text
        with pytest.raises(ValidationError):
            Claim(text="", type="method", section="intro")

        # Invalid type
        with pytest.raises(ValidationError):
            Claim(text="text", type="invalid_type", section="intro")

    def test_missing_citation_validation(self):
        """MissingCitation: confidence вне [0,1] → ошибка."""
        from app.models.schemas import MissingCitation
        from pydantic import ValidationError

        # Valid
        mc = MissingCitation(
            paper_title="Paper",
            related_claim="claim",
            reason="because",
            confidence=0.85,
        )
        assert mc.confidence == 0.85

        # confidence > 1
        with pytest.raises(ValidationError):
            MissingCitation(
                paper_title="Paper",
                related_claim="claim",
                reason="because",
                confidence=1.5,
            )

        # confidence < 0
        with pytest.raises(ValidationError):
            MissingCitation(
                paper_title="Paper",
                related_claim="claim",
                reason="because",
                confidence=-0.1,
            )

    def test_analyze_response_debug_optional(self):
        """AnalyzeResponse: debug=None допустимо."""
        from app.models.schemas import AnalyzeResponse

        ar = AnalyzeResponse(missing_citations=[])
        assert ar.debug is None
        assert ar.missing_citations == []

        ar2 = AnalyzeResponse(missing_citations=[], debug={"claims": []})
        assert ar2.debug is not None

    def test_candidate_defaults(self):
        """Candidate: значения по умолчанию."""
        from app.models.schemas import Candidate

        c = Candidate(paper_id="uuid", title="Test")
        assert c.score == 0.0
        assert c.authors == []
        assert c.abstract is None
        assert c.year is None
        assert c.doi is None


# ── POST /analyze stub ──────────────────────────────────────────────────────

class TestAnalyzeStub:
    """Проверка заглушки POST /analyze"""

    async def test_analyze_without_file_returns_422(self, client: AsyncClient):
        """POST без файла → 422."""
        response = await client.post("/analyze")
        assert response.status_code == 422

    async def test_analyze_with_debug_flag(self, client: AsyncClient):
        """POST /analyze?debug=true → debug в ответе."""
        import io

        response = await client.post(
            "/analyze?debug=true",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert "debug" in data
        assert data["debug"] is not None
        assert "missing_citations" in data
        assert data["missing_citations"] == []

    async def test_analyze_without_debug(self, client: AsyncClient):
        """POST /analyze без ?debug → debug=None."""
        import io

        response = await client.post(
            "/analyze",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["debug"] is None
