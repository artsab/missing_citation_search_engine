"""Shared fixtures for all test levels."""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for the FastAPI test app."""
    os.environ.setdefault("POSTGRES_DSN", "postgresql://user:pass@localhost:5432/db")
    os.environ.setdefault("QDRANT_URL", "http://localhost:6333")

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
