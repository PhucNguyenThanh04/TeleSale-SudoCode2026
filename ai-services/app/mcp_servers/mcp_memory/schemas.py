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
    action: Literal["turn", "fact", "order", "seed_episode", "commit_turn", "claim_pending"]
    customer_id: str | None = None
    session_id: UUID
    data: dict
    operation_key: str | None = None

    @model_validator(mode="after")
    def validate_data(self):
        fields = {
            "turn": {"customer_text", "agent_text", "on", "channel"},
            "commit_turn": {"customer_text", "agent_text", "on", "channel", "client_msg_id", "facts"},
            "fact": {"key", "op", "source"},
            "order": {"order_id"},
            "seed_episode": {"on"},
            "claim_pending": set(),
        }[self.action]
        if not fields <= self.data.keys():
            raise ValueError("missing memory data fields")
        if self.action == "commit_turn":
            if not isinstance(self.data["facts"], list) or len(self.data["facts"]) > 20:
                raise ValueError("facts must be a list of at most 20 items")
        return self
