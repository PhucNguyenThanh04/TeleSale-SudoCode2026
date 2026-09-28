"""Text turn API boundary. Identity is resolved by backend, never by the model."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class TextTurnRequest(BaseModel):
    session_id: str
    customer_id: str | None = None
    channel: Literal["hotline", "chat_fanpage", "zalo_oa", "web_chat", "other"]
    call_date: date
    customer_text: str = Field(min_length=1)
    customer_input_mode: Literal["clean", "asr_transcript", "chat_teencode"] = "clean"


class TextTurnResponse(BaseModel):
    session_id: str
    agent_text: str
    needs_handoff: bool = False
    handoff_ticket_id: str | None = None
