
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
    private_delivery: dict[str, Any] | None
    identity_status: str
    customer_id: str | None
    erased_customer_id: str
    customer_phone: str | None
    customer_name: str | None
    honorific: str | None
    crm_sessions: list[dict[str, Any]]
    crm_orders: list[dict[str, Any]]
    received_at_monotonic: float
    owned_order_ids: list[str]
    history: list[dict[str, str]]
    customer_statements: list[dict[str, str]]
    context_source_complete: bool
    profile: dict[str, dict[str, Any]]
    scoped_facts: dict[str, dict[str, dict[str, Any]]]
    episodes: list[dict[str, Any]]
    current_episode: dict[str, Any] | None
    remembered_order_ids: list[str]
    call_brief: dict[str, Any] | None
    turn_no: int
    decision: Decision
    session_tool_calls: list[dict[str, Any]]
    prepared_tool_calls: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    tool_count: int
    tool_attempts: int
    tool_precondition_error: str
    tool_failed: bool
    memory_failure: str
    memory_blocked: bool
    memory_include_prior: bool
    memory_fact_ttl_days: int
    agent_text: str
    verified_answer: str
    agent_draft: str
    agent_continuation: Any
    selected_system_prompt: str
    reply_context: dict[str, Any]
    reply_error: str | None
    verifier_events: list[dict[str, Any]]
    policy_order_bindings: dict[int, str | None]
    knowledge_release_id: str
    needs_handoff: bool
    handoff_ticket_id: str | None
    memory_writes: list[dict[str, Any]]
    memory_commit_ms: float
