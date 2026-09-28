"""Backend-owned customer sessions and text messages."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .common import Channel, Outcome


class SessionCreate(BaseModel):
    customer_id: str | None = None  # Remains unset until identity is resolved.
    channel: Channel
    call_date: date
    channel_identity: str | None = None


class SessionRecord(BaseModel):
    session_id: str
    customer_id: str | None = None
    channel: Channel
    call_date: date
    started_at: datetime
    finalized_at: datetime | None = None
    outcome: Outcome | None = None


class TextMessage(BaseModel):
    message_id: str
    session_id: str
    role: Literal["customer", "agent", "human_agent"]
    text: str = Field(min_length=1)
    created_at: datetime
