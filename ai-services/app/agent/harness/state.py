"""Typed state for the production one-turn graph."""

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from app.schemas.agent import TextTurnRequest


class Decision(BaseModel):
    action: Literal["tool"]
    tool_name: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)


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
    scoped_facts: dict[str, dict[str, dict[str, Any]]]
    episodes: list[dict[str, Any]]
    remembered_order_ids: list[str]
    call_brief: dict[str, Any] | None
    turn_no: int
    decision: Decision
    tool_calls: list[dict[str, Any]]
    tool_count: int
    tool_failed: bool
    memory_failure: str
    memory_blocked: bool
    agent_text: str
    agent_draft: str
    verifier_events: list[dict[str, Any]]
    fact_candidates: list[dict[str, Any]]
    model_fact_candidates: list[dict[str, Any]]
    plan_envelopes: list[dict[str, Any]]
    needs_handoff: bool
    handoff_ticket_id: str | None
    memory_writes: list[dict[str, Any]]
