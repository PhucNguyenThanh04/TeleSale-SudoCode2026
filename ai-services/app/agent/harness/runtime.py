"""Run one graph turn with process-local idempotency and session locking."""

import asyncio
import logging
import re
import time
from collections import defaultdict
from contextlib import nullcontext
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Callable
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel

from app.agent.graph import build_graph
from app.agent.implementations import AgentKind
from app.agent.memory.store import MemoryStore
from app.agent.harness.observability import log_event
from app.agent.harness.context import load_context
from app.agent.harness.session_identity import identity_fingerprint, initialize_identity
from app.agent.harness.state import TurnState
from app.agent.harness.tracing import LangfuseTracing
from app.agent.mcp.gateway import ToolGateway
from app.constants import DEFAULT_MAX_TOOL_CALLS, DEFAULT_PROMPT_HISTORY_TURNS
from app.schemas.agent import (PrepareSessionRequest, PrepareSessionResponse,
                               TextTurnRequest, TextTurnResponse, TurnMemoryRequest,
                               MemoryUpdate)


class AgentHarnessRuntime:
    """Production runtime for the selected model/tool agent loop."""

    def __init__(self, llm: BaseChatModel, tools: ToolGateway, memory: MemoryStore,
                 max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
                 prompt_history_turns: int = DEFAULT_PROMPT_HISTORY_TURNS,
                 clock: Callable[[], datetime] | None = None,
                 guardrails_enabled: bool = True,
                 tracing: LangfuseTracing | None = None,
                 agent_kind: AgentKind = "deep") -> None:
        self.memory = memory
        self.tools = tools
        self.tracing = tracing
        if not guardrails_enabled:
            log_event(None, "verify", "answer_check_disabled", level=logging.WARNING,
                      reason="cấu hình tắt kiểm tra bổ sung; kiểm tra bằng chứng vẫn chạy")
        self.graph = build_graph(llm, tools, memory, max_tool_calls,
                                 prompt_history_turns, clock, guardrails_enabled,
                                 agent_kind)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._responses: dict[tuple[str, str], TextTurnResponse] = {}
        self._states: dict[tuple[str, str], TurnState] = {}
        self._session_identities: dict[str, tuple[str, dict]] = {}
        self._session_tool_calls: dict[str, list[dict]] = defaultdict(list)
        self._preparations: dict[str, tuple[date, float, str | None, list[dict]]] = {}
        self._clock = clock

    async def _identity_for(self, turn: TextTurnRequest) -> tuple[dict, list[dict]]:
        session_id = str(turn.session_id)
        fingerprint = identity_fingerprint(turn)
        bound = self._session_identities.get(session_id)
        if bound is not None and bound[0] != fingerprint:
            raise ValueError("Session channel identity mismatch")
        late_phone = (
            bound is not None and bound[1]["identity_status"] == "unknown"
            and turn.channel in {"chat_fanpage", "zalo_oa"}
            and bool(re.search(
                r"(?i)\b(?:sđt|sdt|số điện thoại|so dien thoai)\D{0,20}0\d{9}\b",
                turn.text or ""))
        )
        if bound is None or (bound[1]["identity_status"] != "known"
                             and (turn.verified_customer_id or late_phone)):
            identity, calls = await initialize_identity(turn, self.tools)
            self._session_identities[session_id] = (fingerprint, identity)
        else:
            identity, calls = bound[1], []
        if turn.verified_customer_id and identity.get("customer_id") != turn.verified_customer_id:
            raise ValueError("Verified customer conflicts with session owner")
        return identity, calls

    async def prepare_session(self, request: PrepareSessionRequest) -> PrepareSessionResponse:
        """Warm returning-customer reads without inference or a committed turn."""
        started = time.perf_counter()
        # Empty text is internal context input, never a fabricated customer turn.
        turn = TextTurnRequest.model_construct(**request.model_dump(),
            client_msg_id=uuid4(), text="", input_mode="asr_transcript")
        session_id = str(request.session_id)
        async with self._locks[session_id]:
            self._preparations.pop(session_id, None)
            identity, calls = await self._identity_for(turn)
            state = {"request": turn, **deepcopy(identity), "safe_text": "",
                     "received_at_monotonic": started, "tool_calls": calls,
                     "session_tool_calls": deepcopy(self._session_tool_calls[session_id])}
            context = await load_context(state, self.memory, self.tools,
                self._clock or (lambda: datetime.now(timezone.utc)))
            if context.get("tool_failed"):
                raise RuntimeError("session_preparation_failed")
            # Retain only reads, not profile snapshots: every real turn still
            # checks memory ownership/erasure and sees the latest committed history.
            self._preparations[session_id] = (
                request.on, started, identity.get("customer_id"),
                deepcopy(context.get("tool_calls", [])))
            return PrepareSessionResponse(session_id=request.session_id,
                                           call_brief=context.get("call_brief"))

    def state_for(self, turn: TextTurnRequest) -> TurnState | None:
        """Return the observed graph state for an in-process evaluation runner."""
        return self._states.get((str(turn.session_id), str(turn.client_msg_id)))

    async def memory_update(self, request: TurnMemoryRequest) -> MemoryUpdate:
        """Read the worker's durable result, independently of response generation."""
        from app.mcp_servers.mcp_shared.pii import mask_pii

        turn = TextTurnRequest.model_construct(**request.model_dump(), text="", input_mode="clean")
        async with self._locks[str(request.session_id)]:
            identity, _ = await self._identity_for(turn)
        try:
            result = await self.memory.read_turn_status(str(request.session_id),
                identity.get("customer_id"), str(request.client_msg_id))
            if not isinstance(result, dict) or "error" in result:
                return MemoryUpdate()
            update = MemoryUpdate.model_validate(result)
            if update.status != "completed":
                update.changes = []
            # Supplement the MCP's general PII mask with the bound customer's
            # known name, including short names not caught by the generic mask.
            name = identity.get("customer_name")
            for change in update.changes:
                if isinstance(change.value, str):
                    value = change.value
                    if name:
                        value = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)",
                                       "[TÊN ĐÃ ẨN]", value, flags=re.I)
                    change.value = mask_pii(value)
            return update
        except Exception:
            return MemoryUpdate()

    async def run(self, turn: TextTurnRequest) -> TextTurnResponse:
        from app.knowledge.context import selected_release, release_context
        if selected_release() or not getattr(self.tools, "transports", {}).get("knowledge"):
            return await self._run(turn)
        release = await self.tools.knowledge_release()
        with release_context(release['release_id']):
            return await self._run(turn)

    async def _run(self, turn: TextTurnRequest) -> TextTurnResponse:
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
                    identity, initial_calls = await self._identity_for(turn)
                    prepared = self._preparations.pop(session_id, None)
                    prepared_calls = []
                    if prepared:
                        prepared_on, prepared_at, prepared_customer, reads = prepared
                        if (prepared_on == turn.on and time.perf_counter() - prepared_at <= 30
                                and prepared_customer == identity.get("customer_id")):
                            prepared_calls = reads
                    config = {"configurable": {"thread_id": session_id},
                              "run_name": "process-chat-turn"}
                    if trace:
                        config["callbacks"] = [trace[0]]
                    # Pre-call reads are prior evidence, not tool attempts made
                    # for this utterance (which may change SKU, quantity or address).
                    prior_session_calls = deepcopy([
                        *self._session_tool_calls[session_id], *prepared_calls])
                    state: TurnState = await self.graph.ainvoke(
                        {"request": turn, **deepcopy(identity),
                         "received_at_monotonic": started,
                         "session_tool_calls": prior_session_calls,
                         "tool_calls": initial_calls}, config=config,
                    )
                    if not state.get("tool_failed"):
                        self._session_tool_calls[session_id].extend(prepared_calls)
                    self._session_tool_calls[session_id].extend(
                        {**deepcopy(call), 'customer_id': state.get('customer_id'),
                         'session_id': session_id, 'source_turn_id': str(turn.client_msg_id)}
                        for call in state.get('tool_calls', []))
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
                memory_update=MemoryUpdate(
                    turn_saved=not state.get("memory_blocked", False),
                    status=("unavailable" if state.get("memory_blocked") else
                            "pending" if state.get("customer_id") else "not_applicable")),
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
