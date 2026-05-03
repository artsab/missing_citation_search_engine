"""Qdrant vector database client wrapper."""

import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from app.config import get_settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "papers"


class QdrantWrapper:
    """Wrapper around QdrantClient with collection management."""

    def __init__(self, url: str, vector_size: int):
        self._url = url
        self._vector_size = vector_size
        self._client: QdrantClient | None = None

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            raise RuntimeError("QdrantWrapper not connected. Call connect() first.")
        return self._client

    async def connect(self) -> None:
        """Initialize Qdrant client and ensure 'papers' collection exists."""
        logger.info("Connecting to Qdrant at %s ...", self._url)
        self._client = QdrantClient(url=self._url)
        await self._ensure_collection()
        logger.info("Qdrant connected, collection '%s' ready.", COLLECTION_NAME)

    async def disconnect(self) -> None:
        """Close the Qdrant client."""
        if self._client:
            self._client.close()
            self._client = None
            logger.info("Qdrant disconnected.")

    async def health(self) -> bool:
        """Check if Qdrant is reachable."""
        if self._client is None:
            return False
        try:
            self._client.get_collections()
            return True
        except Exception:
            logger.warning("Qdrant health check failed", exc_info=True)
            return False

    async def _ensure_collection(self) -> None:
        """Create the 'papers' collection if it doesn't exist."""
        collections = [
            c.name
            for c in self._client.get_collections().collections
        ]
        if COLLECTION_NAME in collections:
            logger.debug("Collection '%s' already exists.", COLLECTION_NAME)
            return

        logger.info("Creating collection '%s' (dim=%d, Cosine)...", COLLECTION_NAME, self._vector_size)
        self._client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=qdrant_models.VectorParams(
                size=self._vector_size,
                distance=qdrant_models.Distance.COSINE,
            ),
        )

    # ── Search / Upsert helpers ─────────────────────────────────────────

    def search(
        self,
        vector: list[float],
        *,
        chunk_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search for nearest neighbours, optionally filtered by chunk_type."""
        query_filter = None
        if chunk_type is not None:
            query_filter = qdrant_models.Filter(
                must=[
                    qdrant_models.FieldCondition(
                        key="chunk_type",
                        match=qdrant_models.MatchValue(value=chunk_type),
                    )
                ]
            )

        results = self._client.search(
            collection_name=COLLECTION_NAME,
            query_vector=vector,
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        )
        return [
            {"id": r.id, "score": r.score, **r.payload}
            for r in results
        ]

    def upsert_points(self, points: list[dict[str, Any]]) -> None:
        """Insert or update points in the collection."""
        qdrant_points = [
            qdrant_models.PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p["payload"],
            )
            for p in points
        ]
        self._client.upsert(
            collection_name=COLLECTION_NAME,
            points=qdrant_points,
        )


# ── Module-level singleton ──────────────────────────────────────────────

_qdrant_client: QdrantWrapper | None = None


def get_qdrant_client() -> QdrantWrapper:
    """Return the global QdrantWrapper singleton."""
    global _qdrant_client
    if _qdrant_client is None:
        settings = get_settings()
        _qdrant_client = QdrantWrapper(
            url=settings.qdrant_url,
            vector_size=settings.yaml.embedding.dimension,
        )
    return _qdrant_client
