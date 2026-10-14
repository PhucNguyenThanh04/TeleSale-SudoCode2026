"""HTTP contract for a text turn in a simulated trusted call channel."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, StringConstraints, model_validator

from app.schemas.common import Channel, PhoneNumber


class ChatRequest(BaseModel):
    client_msg_id: UUID | None = None
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    session_id: UUID | None = None
    caller_phone: PhoneNumber | None = None
    channel_identity: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    channel: Channel | None = None
    call_date: date | None = None
    customer_input_mode: Literal["clean", "asr_transcript", "chat_teencode"] = "clean"

    @model_validator(mode="after")
    def check_session_fields(self) -> "ChatRequest":
        if self.session_id is None:
            if self.channel is None or self.call_date is None:
                raise ValueError("Lượt đầu cần channel và call_date")
            if self.channel == "hotline" and not (self.caller_phone or self.channel_identity):
                raise ValueError("Hotline cần caller_phone hoặc channel_identity")
            if self.channel != "hotline" and not self.channel_identity:
                raise ValueError("Kênh chat cần channel_identity từ nguồn tin cậy")
        elif any(value is not None for value in (self.caller_phone, self.channel_identity,
                                                  self.channel, self.call_date)):
            raise ValueError("Lượt tiếp theo chỉ gửi session_id và text")
        return self


class ChatResponse(BaseModel):
    client_msg_id: UUID
    session_id: UUID
    agent_text: str
    identity_status: Literal["known", "unknown", "ambiguous"]
    needs_handoff: bool = False
    handoff_ticket_id: str | None = None
    call_brief: dict | None = None


class AITextTurnResponse(BaseModel):
    """Response from the text-turn AI service endpoint."""

    client_msg_id: UUID
    session_id: UUID
    agent_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    needs_handoff: bool = False
    handoff_ticket_id: str | None = None
    call_brief: dict | None = None
