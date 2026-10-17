"""Run one graph turn with process-local idempotency and session locking."""

import asyncio
import logging
import time
from collections import defaultdict
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime
from typing import Callable

from langchain_core.language_models.chat_models import BaseChatModel

from app.agent.graph import build_graph
from app.agent.implementations import AgentKind
from app.agent.memory.store import MemoryStore
from app.agent.harness.observability import log_event
from app.agent.harness.session_identity import identity_fingerprint, initialize_identity
from app.agent.harness.state import TurnState
from app.agent.harness.tracing import LangfuseTracing
from app.agent.mcp.gateway import ToolGateway
from app.constants import DEFAULT_MAX_TOOL_CALLS, DEFAULT_PROMPT_HISTORY_TURNS
from app.schemas.agent import TextTurnRequest, TextTurnResponse


class AgentHarnessRuntime:
    """Production runtime for the selected model/tool agent loop."""

    def __init__(self, llm: BaseChatModel, tools: ToolGateway, memory: MemoryStore,
                 max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
                 prompt_history_turns: int = DEFAULT_PROMPT_HISTORY_TURNS,
                 clock: Callable[[], datetime] | None = None,
                 guardrails_enabled: bool = True,
                 tracing: LangfuseTracing | None = None,
                 agent_kind: AgentKind = "deep",
                 fact_extraction_mode: str = "fallback") -> None:
        self.memory = memory
        self.tools = tools
        self.tracing = tracing
        self.graph = build_graph(llm, tools, memory, max_tool_calls,
                                 prompt_history_turns, clock, guardrails_enabled,
                                 agent_kind, fact_extraction_mode)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._responses: dict[tuple[str, str], TextTurnResponse] = {}
        self._states: dict[tuple[str, str], TurnState] = {}
        self._session_identities: dict[str, tuple[str, dict]] = {}

    def state_for(self, turn: TextTurnRequest) -> TurnState | None:
        """Return the observed graph state for an in-process evaluation runner."""
        return self._states.get((str(turn.session_id), str(turn.client_msg_id)))

    async def run(self, turn: TextTurnRequest) -> TextTurnResponse:
        started = time.perf_counter()
        log_event(turn, "chat", "started", channel=turn.channel,
                  input_mode=turn.input_mode, on=turn.on.isoformat())
        session_id = str(turn.session_id)
        key = (session_id, str(turn.client_msg_id))
        async with self._locks[session_id]:
            fingerprint = identity_fingerprint(turn)
            bound = self._session_identities.get(session_id)
            if bound is not None and bound[0] != fingerprint:
                raise ValueError("Session channel identity mismatch")
            if key in self._responses:
                log_event(turn, "chat", "cache_hit",
                          duration_ms=round((time.perf_counter() - started) * 1000))
                return self._responses[key]
            try:
                with (self.tracing.turn(turn) if self.tracing else nullcontext(None)) as trace:
                    if bound is None or (bound[1]["identity_status"] != "known"
                                         and turn.verified_customer_id):
                        identity, initial_calls = await initialize_identity(turn, self.tools)
                        self._session_identities[session_id] = (fingerprint, identity)
                    else:
                        identity, initial_calls = bound[1], []
                    if (turn.verified_customer_id and identity.get("customer_id")
                            != turn.verified_customer_id):
                        raise ValueError("Verified customer conflicts with session owner")
                    config = {"configurable": {"thread_id": session_id},
                              "run_name": "process-chat-turn"}
                    if trace:
                        config["callbacks"] = [trace[0]]
                    state: TurnState = await self.graph.ainvoke(
                        {"request": turn, **deepcopy(identity),
                         "tool_calls": initial_calls}, config=config,
                    )
                    if trace:
                        trace_output = {"needs_handoff": state.get("needs_handoff", False),
                                        "tool_count": state.get("tool_count", 0),
                                        "memory_writes": len(state.get("memory_writes", []))}
                        if getattr(self.tracing, "capture_content", False):
                            trace_output["agent_text"] = state.get("agent_text", "")
                        trace[1].update(output=trace_output)
            except Exception as exc:
                log_event(turn, "chat", "failed", level=logging.ERROR,
                          duration_ms=round((time.perf_counter() - started) * 1000),
                          error_type=type(exc).__name__)
                raise
            response = TextTurnResponse(
                client_msg_id=turn.client_msg_id,
                session_id=turn.session_id,
                agent_text=state["agent_text"],
                needs_handoff=state.get("needs_handoff", False),
                handoff_ticket_id=state.get("handoff_ticket_id"),
                call_brief=state.get("call_brief"),
            )
            self._responses[key] = response
            self._states[key] = state
            log_event(turn, "chat", "completed",
                      duration_ms=round((time.perf_counter() - started) * 1000),
                      tool_calls=state.get("tool_count", 0),
                      needs_handoff=response.needs_handoff,
                      memory_writes=len(state.get("memory_writes", [])))
            return response


# Keep the old import working for existing callers while configuration chooses the agent.
DeepHarnessRuntime = AgentHarnessRuntime
