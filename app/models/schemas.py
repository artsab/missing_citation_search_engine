"""Pydantic models: API request/response, internal data structures."""

from typing import Literal

from pydantic import BaseModel, Field


# ── API Request / Response ─────────────────────────────────────────────

class Claim(BaseModel):
    """A single scientific claim extracted from a paper section."""
    text: str = Field(..., min_length=1, description="The claim text")
    type: Literal["method", "background", "result"] = Field(
        ..., description="Claim type"
    )
    section: str = Field(..., description="Source section name")


class Reference(BaseModel):
    """A bibliographic reference extracted from the paper."""
    title: str = Field(..., min_length=1)
    authors: list[str] | None = None
    year: int | None = None
    doi: str | None = None


class MissingCitation(BaseModel):
    """A recommended missing citation with explanation."""
    paper_title: str = Field(..., min_length=1)
    doi: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    related_claim: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)


class AnalyzeResponse(BaseModel):
    """Response for POST /analyze."""
    missing_citations: list[MissingCitation] = Field(default_factory=list)
    debug: dict | None = None


# ── Internal / DB models ───────────────────────────────────────────────

class PaperRecord(BaseModel):
    """PostgreSQL papers table row."""
    id: str
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    source_pdf_path: str | None = None
    chunk_count: int = 0


class ChunkPayload(BaseModel):
    """Payload stored in Qdrant for each chunk vector."""
    paper_id: str
    title: str
    chunk_text: str
    section: str = ""
    chunk_type: Literal["section", "paragraph"]
    year: int | None = None
    doi: str | None = None
    authors: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    """A candidate paper retrieved from Qdrant after deduplication."""
    paper_id: str
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    score: float = 0.0
