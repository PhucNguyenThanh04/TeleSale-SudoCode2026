"""Memory tool inputs."""

from uuid import UUID
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ReadInput(BaseModel):
    customer_id: str | None = None
    session_id: UUID
    max_episodes: int = Field(default=5, ge=0, le=20)
    include_prior: bool = True


class WriteInput(BaseModel):
    action: Literal["commit_turn"]
    customer_id: str | None = None
    session_id: UUID
    data: dict
    operation_key: str | None = None

    @model_validator(mode="after")
    def validate_data(self):
        fields = {"customer_text", "agent_text", "on", "channel", "client_msg_id"}
        if not fields <= self.data.keys():
            raise ValueError("missing memory data fields")
        if "facts" in self.data or "episode_delta" in self.data:
            raise ValueError("legacy memory proposals are unavailable")
        return self
