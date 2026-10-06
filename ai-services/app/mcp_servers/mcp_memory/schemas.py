"""Memory tool inputs."""

from uuid import UUID
from pydantic import BaseModel, Field


class ReadInput(BaseModel):
    customer_id: str | None = None
    session_id: UUID
    max_episodes: int = Field(default=5, ge=0, le=20)
    include_prior: bool = True


class WriteInput(BaseModel):
    action: str
    customer_id: str | None = None
    session_id: UUID
    data: dict
    operation_key: str | None = None
