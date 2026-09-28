"""Knowledge retrieval metadata used to reject stale or internal documents."""

from datetime import date

from pydantic import BaseModel, Field


class KnowledgeSearch(BaseModel):
    query: str
    on: date
    max_results: int = Field(default=5, ge=1, le=20)


class KnowledgeHit(BaseModel):
    chunk_id: str
    document_id: str
    source: str
    text: str
    score: float = Field(ge=0)
    effective_from: date | None = None
    effective_until: date | None = None
    customer_visible: bool


class KnowledgeSearchResult(BaseModel):
    hits: list[KnowledgeHit] = Field(default_factory=list)
