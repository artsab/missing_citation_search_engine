"""PostgreSQL async client wrapper (asyncpg)."""

import logging
from typing import Any

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Table creation DDL ──────────────────────────────────────────────────

CREATE_PAPERS_TABLE = """
CREATE TABLE IF NOT EXISTS papers (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    abstract TEXT,
    authors TEXT[] DEFAULT '{}',
    year INT,
    doi TEXT UNIQUE,
    source_pdf_path TEXT,
    ingested_at TIMESTAMP DEFAULT NOW(),
    chunk_count INT DEFAULT 0
);
"""

CREATE_INDEX_DOI = """
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers (doi);
"""

CREATE_INDEX_YEAR = """
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers (year);
"""


class PostgresClient:
    """Async PostgreSQL client with connection pool."""

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgresClient not connected. Call connect() first.")
        return self._pool

    async def connect(self) -> None:
        """Create connection pool and ensure tables exist."""
        logger.info("Connecting to PostgreSQL...")
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=2,
            max_size=10,
        )
        await self._create_tables()
        logger.info("PostgreSQL connected, tables ready.")

    async def disconnect(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL disconnected.")

    async def health(self) -> bool:
        """Check if PostgreSQL is reachable."""
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            logger.warning("PostgreSQL health check failed", exc_info=True)
            return False

    async def _create_tables(self) -> None:
        """Run DDL to create tables and indexes."""
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_PAPERS_TABLE)
            await conn.execute(CREATE_INDEX_DOI)
            await conn.execute(CREATE_INDEX_YEAR)

    # ── CRUD helpers ────────────────────────────────────────────────────

    async def insert_paper(self, paper: dict[str, Any]) -> None:
        """Insert or update a paper record."""
        query = """
        INSERT INTO papers (id, title, abstract, authors, year, doi, source_pdf_path, chunk_count)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (doi) DO UPDATE SET
            title = EXCLUDED.title,
            abstract = EXCLUDED.abstract,
            authors = EXCLUDED.authors,
            year = EXCLUDED.year,
            source_pdf_path = EXCLUDED.source_pdf_path,
            chunk_count = EXCLUDED.chunk_count,
            ingested_at = NOW()
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                query,
                paper["id"],
                paper["title"],
                paper.get("abstract"),
                paper.get("authors", []),
                paper.get("year"),
                paper.get("doi"),
                paper.get("source_pdf_path"),
                paper.get("chunk_count", 0),
            )

    async def paper_exists_by_doi(self, doi: str) -> bool:
        """Check if a paper with given DOI is already indexed."""
        if not doi:
            return False
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM papers WHERE doi = $1", doi
            )
            return row is not None

    async def get_paper_by_id(self, paper_id: str) -> dict | None:
        """Retrieve a single paper by its UUID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM papers WHERE id = $1", paper_id
            )
            return dict(row) if row else None


# ── Module-level singleton (late-init by lifespan) ──────────────────────

_pg_client: PostgresClient | None = None


def get_postgres_client() -> PostgresClient:
    """Return the global PostgresClient singleton."""
    global _pg_client
    if _pg_client is None:
        settings = get_settings()
        _pg_client = PostgresClient(dsn=settings.postgres_dsn)
    return _pg_client
