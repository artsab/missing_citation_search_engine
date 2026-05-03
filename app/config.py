"""Configuration loader: .env + config.yaml via pydantic-settings."""

import os
from pathlib import Path
from functools import lru_cache

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── YAML config model (in-file parameters) ────────────────────────────

class LLMConfig(BaseSettings):
    model: str = "gpt-4o-mini"
    temperature: float = 0.0
    max_tokens: int = 2048

    model_config = SettingsConfigDict(extra="ignore")


class EmbeddingConfig(BaseSettings):
    model: str = "text-embedding-3-small"
    dimension: int = 1536

    model_config = SettingsConfigDict(extra="ignore")


class PipelineConfig(BaseSettings):
    max_claims: int = 20
    top_k_retrieval: int = 100
    top_k_rerank: int = 20
    top_k_output: int = 10
    confidence_threshold: float = 0.6

    model_config = SettingsConfigDict(extra="ignore")


class ChunkingConfig(BaseSettings):
    paragraph_size: int = 500
    paragraph_overlap: int = 100

    model_config = SettingsConfigDict(extra="ignore")


class LoggingYamlConfig(BaseSettings):
    level: str = "INFO"
    format: str = "json"

    model_config = SettingsConfigDict(extra="ignore")


class YamlConfig(BaseSettings):
    """Mirrors config.yaml structure."""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    logging: LoggingYamlConfig = Field(default_factory=LoggingYamlConfig)

    model_config = SettingsConfigDict(extra="ignore")


# ── Env-secrets model (.env / environment) ────────────────────────────

class Settings(BaseSettings):
    """Application settings: secrets from .env, parameters from config.yaml."""

    # ── Secrets (.env) ──
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    embedding_api_key: str = Field(default="", alias="EMBEDDING_API_KEY")
    embedding_base_url: str = Field(default="https://api.openai.com/v1", alias="EMBEDDING_BASE_URL")
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    postgres_dsn: str = Field(
        default="postgresql://user:pass@localhost:5432/db",
        alias="POSTGRES_DSN",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="text", alias="LOG_FORMAT")

    # ── YAML config (loaded separately) ──
    yaml: YamlConfig = Field(default_factory=YamlConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# ── Helpers ────────────────────────────────────────────────────────────

def _load_yaml_config(yaml_path: str | None = None) -> YamlConfig:
    """Load config.yaml and return a YamlConfig instance."""
    if yaml_path is None:
        yaml_path = os.getenv("CONFIG_YAML_PATH", "config.yaml")

    path = Path(yaml_path)
    if not path.exists():
        return YamlConfig()

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return YamlConfig(**raw)


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings singleton (YAML loaded once)."""
    settings = Settings()
    settings.yaml = _load_yaml_config()
    return settings
