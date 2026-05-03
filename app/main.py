"""FastAPI application entrypoint."""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db.postgres import get_postgres_client, PostgresClient
from app.db.qdrant import get_qdrant_client, QdrantWrapper
from app.models.schemas import AnalyzeResponse

logger = logging.getLogger(__name__)


# ── Lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect to DBs. Shutdown: close connections."""
    # Startup
    pg = get_postgres_client()
    qdrant = get_qdrant_client()
    await pg.connect()
    await qdrant.connect()
    logger.info("Application started.")
    yield
    # Shutdown
    await pg.disconnect()
    await qdrant.disconnect()
    logger.info("Application shut down.")


# ── FastAPI app ──────────────────────────────────────────────────────────

app = FastAPI(
    title="Missing Citation Detection API",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Health ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health(request: Request) -> dict:
    """Check availability of Qdrant and PostgreSQL."""
    pg: PostgresClient = request.app.state.pg if hasattr(request.app.state, "pg") else get_postgres_client()
    qdrant: QdrantWrapper = request.app.state.qdrant if hasattr(request.app.state, "qdrant") else get_qdrant_client()

    pg_ok = await pg.health()
    qdrant_ok = await qdrant.health()

    status = {
        "database": "ok" if pg_ok else "unavailable",
        "qdrant": "ok" if qdrant_ok else "unavailable",
    }

    if pg_ok and qdrant_ok:
        return JSONResponse(content=status, status_code=200)
    else:
        return JSONResponse(content=status, status_code=503)


# ── Analyze (stub – Этап 8) ──────────────────────────────────────────────

@app.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    debug: bool = False,
) -> AnalyzeResponse:
    """Analyze a PDF and return top-10 missing citations (stub)."""
    return AnalyzeResponse(
        missing_citations=[],
        debug={"claims": [], "candidates": []} if debug else None,
    )
