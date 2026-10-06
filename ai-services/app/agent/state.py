"""Typed state and model decisions for one chat turn."""

import json
import re
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from app.schemas.agent import TextTurnRequest


_FENCED_JSON = re.compile(
    r"\A```(?:json)?[ \t]*\r?\n(?P<body>[\s\S]*?)\r?\n```[ \t]*\Z",
    re.IGNORECASE,
)


class FactDraft(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value: str | int | float | bool
    op: Literal["set", "supersede", "delete"] = "set"


class Decision(BaseModel):
    action: Literal["respond", "tool"]
    needs_price: bool = False
    response: str = ""
    tool_name: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    memory_writes: list[FactDraft] = Field(default_factory=list)


def parse_decision(content: str) -> tuple[Decision, int, bool]:
    """Accept one enclosing JSON fence; validate the decision without memory drafts."""
    stripped = content.strip()
    fence = _FENCED_JSON.fullmatch(stripped)
    payload = json.loads(fence.group("body") if fence else stripped)
    if not isinstance(payload, dict):
        raise ValueError("model decision must be a JSON object")
    proposals = payload.pop("memory_writes", [])
    ignored = len(proposals) if isinstance(proposals, list) else 1
    if payload.get("action") == "respond" and payload.get("tool_args") is None:
        payload["tool_args"] = {}
    return Decision.model_validate(payload), ignored, fence is not None


class TurnState(TypedDict, total=False):
    request: TextTurnRequest
    safe_text: str
    identity_status: str
    customer_id: str | None
    customer_phone: str | None
    customer_name: str | None
    honorific: str | None
    crm_sessions: list[dict[str, Any]]
    received_at_monotonic: float
    owned_order_ids: list[str]
    history: list[dict[str, str]]
    profile: dict[str, dict[str, Any]]
    episodes: list[dict[str, Any]]
    remembered_order_ids: list[str]
    call_brief: dict[str, Any] | None
    turn_no: int
    decision: Decision
    tool_calls: list[dict[str, Any]]
    tool_count: int
    tool_failed: bool
    quote_sweep: dict[str, Any]
    agent_text: str
    needs_handoff: bool
    handoff_ticket_id: str | None
    memory_writes: list[dict[str, Any]]
