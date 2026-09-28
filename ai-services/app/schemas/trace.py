"""One JSONL row per agent turn, aligned with BTC trace_log.schema.json."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Question(BaseModel):
    slot: str
    type: Literal["open", "confirm"]
    text: str


class Claim(BaseModel):
    field: str
    value: Any
    text: str | None = None


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any]
    result: Any = None


class Latency(BaseModel):
    ttft_ms: int = Field(ge=0)
    total_ms: int = Field(ge=0)
    ttfa_ms: int | None = Field(default=None, ge=0)


class TraceMemoryWrite(BaseModel):
    customer_id: str
    key: str
    value: Any
    op: Literal["set", "supersede", "delete"]
    source: str


class AgentTraceLine(BaseModel):
    run_id: str
    config: Literal["full", "baseline_no_memory"]
    scenario_id: str
    call: Literal["call_1", "call_2", "call_3"]
    turn: int = Field(ge=1)
    customer_text: str
    agent_text: str
    questions: list[Question]
    claims: list[Claim]
    tool_calls: list[ToolCall]
    latency: Latency
    facts_used: list[str] = Field(default_factory=list)
    call_brief_latency_ms: int | None = Field(default=None, ge=0)
    memory_writes: list[TraceMemoryWrite] = Field(default_factory=list)
    customer_input_mode: Literal["clean", "asr_transcript", "chat_teencode"] = "clean"
