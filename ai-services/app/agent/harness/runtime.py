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
from app.agent.harness.agent_nodes import AgentNodes, MEMORY_UNAVAILABLE
from app.agent.memory.store import MemoryStore
from app.agent.harness.observability import log_event
from app.agent.harness.context import load_context
from app.agent.harness.session_identity import identity_fingerprint, initialize_identity
from app.agent.harness.state import TurnState
from app.agent.harness.session_state import SessionState
from app.agent.harness.tracing import LangfuseTracing
from app.agent.mcp.gateway import ToolGateway
from app.constants import DEFAULT_MAX_TOOL_CALLS, DEFAULT_PROMPT_HISTORY_TURNS
from app.schemas.agent import (PrepareSessionRequest, PrepareSessionResponse,
                               TextTurnRequest, TextTurnResponse, TurnMemoryRequest,
                               MemoryUpdate, VoicePlaybackRequest)
from app.schemas.timeline import TimelineRequest, TimelinePage
from app.agent.harness.streaming import GuardedStream, active_stream


class AgentHarnessRuntime:
    """Deep Agent runtime with one streaming model/tool loop."""

    def __init__(self, llm: BaseChatModel, tools: ToolGateway, memory: MemoryStore,
                 max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
                 prompt_history_turns: int = DEFAULT_PROMPT_HISTORY_TURNS,
                 clock: Callable[[], datetime] | None = None,
                 guardrails_enabled: bool = True,
                 tracing: LangfuseTracing | None = None) -> None:
        self.memory = memory
        self.tools = tools
        self.tracing = tracing
        if not guardrails_enabled:
            log_event(None, "verify", "answer_check_disabled", level=logging.WARNING,
                      reason="cấu hình tắt kiểm tra bổ sung; kiểm tra bằng chứng vẫn chạy")
        self.nodes = AgentNodes(llm, tools, memory, max_tool_calls,
                                prompt_history_turns, clock)
        self.graph = build_graph(llm, tools, memory, max_tool_calls,
                                 prompt_history_turns, clock, guardrails_enabled,
                                 nodes=self.nodes)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._responses: dict[tuple[str, str], TextTurnResponse] = {}
        self._states: dict[tuple[str, str], TurnState] = {}
        self._session_states: dict[str, SessionState] = {}
        self._session_identities: dict[str, tuple[str, dict]] = {}
        self._session_tool_calls: dict[str, list[dict]] = defaultdict(list)
        self._preparations: dict[str, tuple[date, float, str | None, list[dict]]] = {}
        self._clock = clock
        self._playback_tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._playback_receipts: dict[tuple[str, str], tuple[int, bool]] = {}
        self._stream_tasks: dict[asyncio.Task, GuardedStream] = {}

    async def _finalize_playback(self, key, played_chars: int, interrupted: bool):
        if key in self._playback_receipts:
            if self._playback_receipts[key] != (played_chars, interrupted):
                raise ValueError("Conflicting playback receipt")
            return
        state = self._states[key]
        saved = {**state, "agent_text": state["agent_text"][:played_chars]}
        result = await self.nodes.persist_agent(saved)
        state.update(result)
        self._playback_receipts[key] = (played_chars, interrupted)
        task = self._playback_tasks.pop(key, None)
        if task and task is not asyncio.current_task():
            task.cancel()
        self._responses[key].memory_update = MemoryUpdate(
            turn_saved=not state.get("memory_blocked", False),
            status=("unavailable" if state.get("memory_blocked") else
                    "pending" if state.get("customer_id") else "not_applicable"))

    async def record_playback(self, request: VoicePlaybackRequest) -> MemoryUpdate:
        key = (str(request.session_id), str(request.client_msg_id))
        async with self._locks[key[0]]:
            state = self._states.get(key)
            if (not state or state["request"].delivery_mode != "voice"
                    or identity_fingerprint(request) != identity_fingerprint(state["request"])
                    or request.on != state["request"].on):
                raise ValueError("Playback identity or turn mismatch")
            if request.played_chars > len(state["agent_text"]):
                raise ValueError("Playback exceeds generated reply")
            await self._finalize_playback(key, request.played_chars, request.interrupted)
            return self._responses[key].memory_update

    async def _expire_playback(self, key):
        try:
            await asyncio.sleep(300)
            async with self._locks[key[0]]:
                await self._finalize_playback(key, 0, True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_event(None, "playback", "commit_failed", error_type=type(exc).__name__)

    async def close(self):
        streams = list(self._stream_tasks)
        for stream in list(self._stream_tasks.values()):
            stream.disconnect()
        if streams:
            await asyncio.gather(*streams, return_exceptions=True)
        tasks = list(self._playback_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for key in list(self._playback_tasks):
            async with self._locks[key[0]]:
                await self._finalize_playback(key, 0, True)

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
            session = self._session_states.setdefault(session_id, SessionState(
                identity.get('customer_id'), request.on, getattr(self.memory, 'include_prior', True)))
            seed = session.resume(identity.get('customer_id'), request, getattr(self.memory, 'include_prior', True))
            state = {**seed, "request": turn, **deepcopy(identity), "safe_text": "",
                     "received_at_monotonic": started, "tool_calls": calls,
                     "session_tool_calls": deepcopy(self._session_tool_calls[session_id])}
            context = await load_context(state, self.memory, self.tools,
                self._clock or (lambda: datetime.now(timezone.utc)))
            session.update(context)
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

    async def memory_timeline(self, request: TimelineRequest) -> TimelinePage:
        """Read public history only for an already bound session; never run inference."""
        session_id = str(request.session_id)
        if session_id not in self._session_identities:
            raise ValueError('Session has not been prepared')
        async with self._locks[session_id]:
            fingerprint, bound = self._session_identities[session_id]
            session = self._session_states.get(session_id)
            if (fingerprint != identity_fingerprint(request) or session is None
                    or session.on != request.on
                    or request.verified_customer_id and request.verified_customer_id != bound.get('customer_id')
                    or request.verified_phone and request.verified_phone != bound.get('customer_phone')):
                raise ValueError('Timeline session identity conflict')
            identity = deepcopy(bound)
        if (identity.get('identity_status') != 'known' or not identity.get('customer_id')
                or not getattr(self.memory, 'include_prior', True)):
            return TimelinePage(status='not_applicable', offset=request.offset, limit=request.limit)
        try:
            async with asyncio.timeout(3):
                result = await self.memory.read_timeline(session_id, identity['customer_id'], request.on.isoformat(),
                    offset=request.offset, limit=request.limit, crm_sessions=identity.get('crm_sessions', []))
            if not isinstance(result, dict) or 'error' in result:
                raise RuntimeError('Timeline unavailable')
            page = TimelinePage.model_validate(result)
            if page.offset != request.offset or page.limit != request.limit:
                raise RuntimeError('Timeline pagination changed')
            from app.mcp_servers.mcp_shared.pii import mask_pii
            for item in page.items:
                summary = item.summary
                name = identity.get('customer_name')
                if name:
                    summary = re.sub(r'(?<!\w)' + re.escape(name) + r'(?!\w)', '[TÊN ĐÃ ẨN]', summary, flags=re.I)
                item.summary = mask_pii(summary)
            return page
        except Exception:
            raise RuntimeError('Memory timeline unavailable') from None

    async def stream(self, turn: TextTurnRequest):
        if turn.delivery_mode != 'text':
            raise ValueError('Streaming requires text delivery')
        if not self.nodes.guardrails_enabled:
            raise ValueError('Streaming requires answer guardrails')
        stream = GuardedStream()

        async def produce():
            token = active_stream.set(stream)
            try:
                response = await self.run(turn)
                if stream.state is None:  # A checked cached response; never re-execute tools.
                    saved = self.state_for(turn)
                    if saved is not None and not saved.get('agent_text'):
                        stream.terminal({'event': 'error', 'code': 'turn_interrupted'})
                        return
                    await stream.finish(response.agent_text, saved or {})
                stream.terminal({'event': 'done', **response.model_dump(mode='json')})
            except Exception:
                stream.terminal({'event': 'error', 'code': 'turn_failed'})
            finally:
                active_stream.reset(token)

        task = asyncio.create_task(produce())
        self._stream_tasks[task] = stream
        task.add_done_callback(lambda finished: self._stream_tasks.pop(finished, None))
        try:
            async for event in stream.events():
                yield {'session_id': str(turn.session_id), 'client_msg_id': str(turn.client_msg_id), **event}
        finally:
            # Do not cancel an in-flight write on a transport disconnect.
            stream.disconnect()

    async def run(self, turn: TextTurnRequest) -> TextTurnResponse:
        """Collect the guarded text stream, or generate voice awaiting its receipt."""
        async def collect(text):
            return True

        token = None
        if turn.delivery_mode == 'text' and active_stream.get() is None:
            token = active_stream.set(GuardedStream(collect))
        try:
            return await self._run_with_release(turn)
        finally:
            if token is not None:
                active_stream.reset(token)

    async def _run_with_release(self, turn: TextTurnRequest) -> TextTurnResponse:
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
        stream = active_stream.get()
        async with self._locks[session_id]:
            fingerprint = identity_fingerprint(turn)
            bound = self._session_identities.get(session_id)
            if bound is not None and bound[0] != fingerprint:
                raise ValueError("Session channel identity mismatch")
            if key in self._responses:
                original = self._states[key]['request']
                if (self._states[key]['memory_include_prior'] != getattr(self.memory, 'include_prior', True)
                        or any(getattr(original, field) != getattr(turn, field)
                       for field in ('text', 'on', 'delivery_mode', 'verified_customer_id', 'verified_phone'))):
                    raise ValueError('Conflicting turn retry')
                from app.mcp_servers.mcp_memory.schemas import validate_read_response
                try:
                    context = validate_read_response(await self.memory.read_context(
                        session_id, bound[1].get('customer_id') if bound else None))
                except Exception:
                    context = {'error': 'memory_exception'}
                if 'error' in context:
                    self._session_states.pop(session_id, None)
                    self._session_tool_calls.pop(session_id, None)
                    self._preparations.pop(session_id, None)
                    return TextTurnResponse(client_msg_id=turn.client_msg_id, session_id=turn.session_id,
                        agent_text=MEMORY_UNAVAILABLE,
                        memory_update=MemoryUpdate(status='unavailable'))
                log_event(turn, "chat", "cache_hit",
                          duration_ms=round((time.perf_counter() - started) * 1000))
                return self._responses[key]
            # Never let the next turn use generated-but-unheard voice as history.
            for pending in list(self._playback_tasks):
                if pending[0] == session_id:
                    await self._finalize_playback(pending, 0, True)
            try:
                with (self.tracing.turn(turn) if self.tracing else nullcontext(None)) as trace:
                    identity, initial_calls = await self._identity_for(turn)
                    session = self._session_states.setdefault(session_id, SessionState(
                        identity.get('customer_id'), turn.on, getattr(self.memory, 'include_prior', True)))
                    seed = session.resume(identity.get('customer_id'), turn, getattr(self.memory, 'include_prior', True))
                    prepared = self._preparations.pop(session_id, None)
                    prepared_calls = []
                    if prepared:
                        prepared_on, prepared_at, prepared_customer, reads = prepared
                        if (prepared_on == turn.on and time.perf_counter() - prepared_at <= 30
                                and prepared_customer == identity.get("customer_id")):
                            prepared_calls = reads
                    # Attribute prepared evidence to its first real consumer, without
                    # adding another tool attempt or inventing a preparation turn.
                    prepared_calls = [{**call, 'customer_id': identity.get('customer_id'),
                        'session_id': session_id, 'source_turn_id': str(turn.client_msg_id)}
                        for call in prepared_calls]
                    config = {"configurable": {"thread_id": session_id},
                              "run_name": "process-chat-turn"}
                    if trace:
                        config["callbacks"] = [trace[0]]
                    # Pre-call reads are prior evidence, not tool attempts made
                    # for this utterance (which may change SKU, quantity or address).
                    prior_session_calls = deepcopy([
                        *self._session_tool_calls[session_id], *prepared_calls])
                    state: TurnState = await self.graph.ainvoke(
                        {**seed, "request": turn, **deepcopy(identity),
                         "received_at_monotonic": started,
                         'prepared_tool_calls': prepared_calls,
                         "session_tool_calls": prior_session_calls,
                         "tool_calls": initial_calls}, config=config,
                    )
                    response_text = state['agent_text']
                    if stream is not None:
                        state['agent_text'] = await stream.finish(response_text, state)
                        response_text = state['agent_text'] or response_text
                        state.update(await self.nodes.persist_agent(state))
                    session.update(state)
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
                agent_text=response_text,
                needs_handoff=state.get("needs_handoff", False),
                handoff_ticket_id=state.get("handoff_ticket_id"),
                call_brief=state.get("call_brief"),
                memory_update=MemoryUpdate(
                    turn_saved=turn.delivery_mode != "voice" and not state.get("memory_blocked", False),
                    status=("unavailable" if state.get("memory_blocked") else
                            "pending" if state.get("customer_id") else "not_applicable")),
            )
            self._responses[key] = response
            state['memory_include_prior'] = getattr(self.memory, 'include_prior', True)
            self._states[key] = state
            if turn.delivery_mode == "voice":
                self._playback_tasks[key] = asyncio.create_task(self._expire_playback(key))
            log_event(turn, "chat", "completed",
                      duration_ms=round((time.perf_counter() - started) * 1000),
                      tool_calls=state.get("tool_count", 0),
                      needs_handoff=response.needs_handoff,
                      memory_writes=len(state.get("memory_writes", [])))
            return response


# Existing integrations use this name for the same Deep Agent runtime.
DeepHarnessRuntime = AgentHarnessRuntime
