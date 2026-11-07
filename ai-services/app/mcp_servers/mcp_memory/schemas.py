"""Memory tool inputs."""

from uuid import UUID
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, ValidationError


class ReadInput(BaseModel):
    customer_id: str | None = None
    session_id: UUID
    max_episodes: int = Field(default=5, ge=0, le=20)
    include_prior: bool = True
    query: str = Field(default="", max_length=8000)


class ReadTurn(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    customer: str
    agent: str = ""
    source_turn_id: str | None = None


class ReadFact(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    value: str | int | float | bool | None
    key: str | None = None
    source_kind: Literal["customer", "tool", "agent"] | None = None
    source: str | None = None
    source_tool: str | None = None
    source_turn_id: str | None = None
    session_id: str | None = None
    evidence_quote: str | None = None
    on: str | None = None
    valid_until: str | None = None
    status: str = "active"


class ReadScopes(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    product: dict[str, dict[str, ReadFact]] = Field(default_factory=dict)
    room: dict[str, dict[str, ReadFact]] = Field(default_factory=dict)


class ReadEpisode(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    session_id: str
    schema_version: Literal[1] = 1
    summary: str = ""
    on: str | None = None
    topics: list[dict[str, Any]] = Field(default_factory=list)


class ReadResponse(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    schema_version: Literal[1] = 1
    history: list[ReadTurn]
    profile: dict[str, ReadFact]
    scoped_facts: ReadScopes = Field(default_factory=ReadScopes)
    episodes: list[ReadEpisode] = Field(default_factory=list)
    current_episode: ReadEpisode | None = None
    prior_session_ids: list[str] = Field(default_factory=list)
    owned_order_ids: list[str] = Field(default_factory=list)
    turn_count: int = Field(default=0, ge=0)


def validate_read_response(value: Any) -> dict:
    if isinstance(value, dict) and isinstance(value.get("error"), str):
        return value
    try:
        return ReadResponse.model_validate(value).model_dump(exclude_unset=True)
    except ValidationError:
        return {"error": "invalid_tool_result"}


class TurnStatusInput(BaseModel):
    customer_id: str | None = None
    session_id: UUID
    client_msg_id: UUID


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
