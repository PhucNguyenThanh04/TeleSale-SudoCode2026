"""HTTP contract for one text turn sent by the trusted backend."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Channel = Literal["hotline", "chat_fanpage", "zalo_oa", "web_chat", "other"]
InputMode = Literal["clean", "asr_transcript", "chat_teencode"]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_msg_id: UUID
    session_id: UUID | None = None
    channel: Channel
    channel_identity: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None
    on: date
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    input_mode: InputMode
    verified_customer_id: str | None = None
    verified_phone: str | None = None


class TextTurnRequest(ChatRequest):
    """Validated request inside the graph, always bound to a session."""

    session_id: UUID


class TextTurnResponse(BaseModel):
    client_msg_id: UUID
    session_id: UUID
    agent_text: str = Field(min_length=1)
    needs_handoff: bool = False
    handoff_ticket_id: str | None = None
    call_brief: dict | None = None


ChatResponse = TextTurnResponse
