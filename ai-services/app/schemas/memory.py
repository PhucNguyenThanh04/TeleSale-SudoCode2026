"""Typed memory records with provenance and supersession across sessions."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProfileFact(BaseModel):
    fact_id: str
    customer_id: str
    key: str
    value: Any
    source_session_id: str
    observed_at: datetime
    status: Literal["active", "superseded", "retracted"] = "active"
    supersedes_fact_id: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class Episode(BaseModel):
    session_id: str
    customer_id: str
    channel: Literal["hotline", "chat_fanpage", "zalo_oa", "web_chat", "other"]
    call_date: datetime
    summary: str
    outcome: Literal["hen_goi_lai", "chot_don", "tu_choi", "chuyen_may", "khac"]
    product_skus: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    finalized_at: datetime | None = None


class MemoryRead(BaseModel):
    customer_id: str
    include_episodes: bool = True
    max_episodes: int = Field(default=5, ge=0, le=50)


class MemoryReadResult(BaseModel):
    customer_id: str
    facts: list[ProfileFact] = Field(default_factory=list)
    episodes: list[Episode] = Field(default_factory=list)


class MemoryWrite(BaseModel):
    customer_id: str
    key: str
    value: Any
    op: Literal["set", "supersede", "delete"]
    source: str
    source_session_id: str
    observed_at: datetime
    supersedes_fact_id: str | None = None
