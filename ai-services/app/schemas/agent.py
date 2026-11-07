"""HTTP contract for one text turn sent by the trusted backend."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Channel = Literal["hotline", "chat_fanpage", "zalo_oa", "web_chat", "other"]
InputMode = Literal["clean", "asr_transcript", "chat_teencode"]


class PrepareSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    channel: Channel
    channel_identity: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None
    on: date
    verified_customer_id: str | None = None
    verified_phone: str | None = None


class PrepareSessionResponse(BaseModel):
    session_id: UUID
    call_brief: dict | None = None


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


class MemoryChange(BaseModel):
    field: str
    action: Literal["added", "updated", "deleted"]
    value: str | int | bool | None = None
    source: Literal["customer", "tool"]
    scope_type: Literal["global", "room", "product"] = "global"
    scope_id: str = ""


class MemoryUpdate(BaseModel):
    turn_saved: bool = False
    status: Literal["pending", "completed", "failed", "not_applicable", "unavailable"] = "unavailable"
    changes: list[MemoryChange] = Field(default_factory=list)


class TurnMemoryRequest(PrepareSessionRequest):
    client_msg_id: UUID


class TurnMemoryResponse(BaseModel):
    session_id: UUID
    client_msg_id: UUID
    memory_update: MemoryUpdate


class TextTurnResponse(BaseModel):
    client_msg_id: UUID
    session_id: UUID
    agent_text: str = Field(min_length=1)
    needs_handoff: bool = False
    handoff_ticket_id: str | None = None
    call_brief: dict | None = None
    memory_update: MemoryUpdate = Field(default_factory=MemoryUpdate)


ChatResponse = TextTurnResponse
