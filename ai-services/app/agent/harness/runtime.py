
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
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.memory.store import MemoryStore
from app.agent.harness.observability import log_event
from app.agent.harness.context import load_context
from app.agent.harness.session_identity import identity_fingerprint, initialize_identity, _empty_identity, turn_fingerprint
from app.agent.harness.state import TurnState
from app.agent.harness.session_state import SessionState
from app.agent.harness.tracing import LangfuseTracing
from app.agent.mcp.gateway import ToolGateway
from app.constants import DEFAULT_MAX_TOOL_CALLS, DEFAULT_PROMPT_HISTORY_TURNS
from app.schemas.agent import (PrepareSessionRequest, PrepareSessionResponse,
                               TextTurnRequest, TextTurnResponse, TurnMemoryRequest,
                               MemoryUpdate, VoicePlaybackRequest)
from app.schemas.timeline import TimelineRequest, TimelinePage
from app.agent.harness.streaming import GuardedStream, active_stream, active_turn_progress


class AgentHarnessRuntime:

    def __init__(self, llm: BaseChatModel, tools: ToolGateway, memory: MemoryStore,
                 max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
                 prompt_history_turns: int = DEFAULT_PROMPT_HISTORY_TURNS,
                 clock: Callable[[], datetime] | None = None,
                 guardrails_enabled: bool = True,
                 tracing: LangfuseTracing | None = None,
                 turn_timeout_seconds: float = 90) -> None:
        self.memory = memory
        self.tools = tools
        self.tracing = tracing
        self.turn_timeout_seconds = turn_timeout_seconds
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
        self._session_access: dict[str, float] = {}
        self._cache_max_sessions = 128
        self._turn_progress = {}

    def _prune_cache(self, current_session):
        now = time.monotonic()
        for sid, touched in sorted(self._session_access.items(), key=lambda item: item[1]):
            lock = self._locks.get(sid)
            if (sid == current_session or lock and (lock.locked() or getattr(lock, '_waiters', None))
                    or any(key[0] == sid for key in self._playback_tasks)):
                continue
            if now - touched <= 900 and len(self._session_access) < self._cache_max_sessions:
                break
            self._session_access.pop(sid, None)
            for cache in (self._locks, self._session_states, self._session_identities,
                          self._session_tool_calls, self._preparations):
                cache.pop(sid, None)
            for key in [key for key in self._states if key[0] == sid]:
                for cache in (self._states, self._responses, self._playback_receipts):
                    cache.pop(key, None)
        if current_session not in self._session_access and len(self._session_access) >= self._cache_max_sessions:
            raise RuntimeError('runtime_busy')
        self._session_access[current_session] = now
        for key in list(self._states)[:-32]:
            if key not in self._playback_tasks:
                for cache in (self._states, self._responses, self._playback_receipts):
                    cache.pop(key, None)

    def _forget_customer(self, customer_id):
        for task, progress in list(self._turn_progress.items()):
            if task is not asyncio.current_task() and progress.get('state', {}).get('customer_id') == customer_id:
                stream = progress.get('stream')
                if stream:
                    stream.terminal({'event': 'error', 'code': 'customer_erased'})
                    stream.disconnect()
                task.cancel()
        sessions = {sid for sid, (_, identity) in self._session_identities.items()
                    if identity.get('customer_id') == customer_id}
        sessions.update(key[0] for key, state in self._states.items()
                        if state.get('customer_id') == customer_id)
        for sid in sessions:
            bound = self._session_identities.get(sid)
            if bound:
                self._session_identities[sid] = (bound[0], {
                    **_empty_identity(), 'erased_customer_id': customer_id})
            self._session_states.pop(sid, None)
            self._session_tool_calls.pop(sid, None)
            self._preparations.pop(sid, None)
        for key in list(self._states):
            if key[0] in sessions:
                self._states.pop(key, None)
                self._responses.pop(key, None)
                self._playback_receipts.pop(key, None)
                task = self._playback_tasks.pop(key, None)
                if task:
                    task.cancel()

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
            if (not state or key not in self._responses or state["request"].delivery_mode != "voice"
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
        if bound is None or (not bound[1].get('erased_customer_id') and bound[1]["identity_status"] != "known"
                             and turn.verified_customer_id):
            identity, calls = await initialize_identity(turn, self.tools)
            self._session_identities[session_id] = (fingerprint, identity)
        else:
            identity, calls = bound[1], []
        if (turn.verified_customer_id and identity.get("customer_id") != turn.verified_customer_id
                and identity.get('erased_customer_id') != turn.verified_customer_id):
            raise ValueError("Verified customer conflicts with session owner")
        return identity, calls

    async def prepare_session(self, request: PrepareSessionRequest) -> PrepareSessionResponse:
        started = time.perf_counter()
        turn = TextTurnRequest.model_construct(**request.model_dump(),
            client_msg_id=uuid4(), text="", input_mode="asr_transcript")
        session_id = str(request.session_id)
        self._prune_cache(session_id)
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
            if context.get('erased_customer_id'):
                self._forget_customer(context['erased_customer_id'])
                identity = self._session_identities[session_id][1]
                session = self._session_states.setdefault(session_id, SessionState(
                    None, request.on, getattr(self.memory, 'include_prior', True)))
            session.update(context)
            if context.get("tool_failed"):
                raise RuntimeError("session_preparation_failed")
            self._preparations[session_id] = (
                request.on, started, identity.get("customer_id"),
                deepcopy(context.get("tool_calls", [])))
            return PrepareSessionResponse(session_id=request.session_id,
                                           call_brief=context.get("call_brief"))

    def state_for(self, turn: TextTurnRequest) -> TurnState | None:
        return self._states.get((str(turn.session_id), str(turn.client_msg_id)))

    async def memory_update(self, request: TurnMemoryRequest) -> MemoryUpdate:
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
                if stream.state is None:
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
            stream.disconnect()

    async def run(self, turn: TextTurnRequest) -> TextTurnResponse:
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
        progress = {'stream': active_stream.get()}
        self._turn_progress[asyncio.current_task()] = progress
        token = active_turn_progress.set(progress)
        try:
            async with asyncio.timeout(self.turn_timeout_seconds):
                try:
                    async with asyncio.timeout(self.turn_timeout_seconds - min(3, self.turn_timeout_seconds / 10)):
                        return await self._run(turn)
                except TimeoutError:
                    state = progress.get('state')
                    if state is not None:
                        stream = active_stream.get()
                        state.update(agent_text=stream.published if stream else '',
                                     reply_error='turn_deadline_exceeded', verified_answer='')
                        state['memory_include_prior'] = getattr(self.memory, 'include_prior', True)
                        self._states[(str(turn.session_id), str(turn.client_msg_id))] = state
                        try:
                            await self.nodes.persist_agent(state)
                        except Exception as exc:
                            log_event(turn, 'persist', 'deadline_recovery_failed',
                                      error_type=type(exc).__name__)
                    raise RuntimeError('turn_deadline_exceeded') from None
        except TimeoutError:
            raise RuntimeError('turn_deadline_exceeded') from None
        finally:
            self._turn_progress.pop(asyncio.current_task(), None)
            active_turn_progress.reset(token)

    async def _run(self, turn: TextTurnRequest) -> TextTurnResponse:
        started = time.perf_counter()
        log_event(turn, "chat", "started", channel=turn.channel,
                  input_mode=turn.input_mode, on=turn.on.isoformat())
        session_id = str(turn.session_id)
        key = (session_id, str(turn.client_msg_id))
        self._prune_cache(session_id)
        stream = active_stream.get()
        async with self._locks[session_id]:
            fingerprint = identity_fingerprint(turn)
            bound = self._session_identities.get(session_id)
            if bound is not None and bound[0] != fingerprint:
                raise ValueError("Session channel identity mismatch")
            if key in self._states:
                original = self._states[key]['request']
                if turn_fingerprint(original, self._states[key]['memory_include_prior']) != turn_fingerprint(
                        turn, getattr(self.memory, 'include_prior', True)):
                    raise ValueError('Conflicting turn retry')
                if self._states[key].get('reply_error'):
                    raise RuntimeError(self._states[key]['reply_error'])
            if key in self._responses:
                from app.mcp_servers.mcp_memory.schemas import validate_read_response
                try:
                    context = validate_read_response(await self.memory.read_context(
                        session_id, bound[1].get('customer_id') if bound else None))
                except Exception:
                    context = {'error': 'memory_exception'}
                if context.get('error') == 'customer_erased' and bound:
                    self._forget_customer(bound[1]['customer_id'])
                elif 'error' in context:
                    self._session_states.pop(session_id, None)
                    self._session_tool_calls.pop(session_id, None)
                    self._preparations.pop(session_id, None)
                    raise RuntimeError('memory_unavailable')
                if key in self._responses:
                    log_event(turn, "chat", "cache_hit",
                              duration_ms=round((time.perf_counter() - started) * 1000))
                    return self._responses[key]
            for pending in list(self._playback_tasks):
                if pending[0] == session_id:
                    await self._finalize_playback(pending, 0, True)
            try:
                with (self.tracing.turn(turn) if self.tracing else nullcontext(None)) as trace:
                    identity, initial_calls = await self._identity_for(turn)
                    if getattr(self.memory, 'supports_durable_replay', False) is True:
                        replay = await self.memory.replay_turn(session_id, identity.get('customer_id'), key[1],
                            turn_fingerprint(turn, getattr(self.memory, 'include_prior', True)))
                        if replay.get('error') == 'customer_erased' and identity.get('customer_id'):
                            self._forget_customer(identity['customer_id'])
                            identity = self._session_identities[session_id][1]
                            replay = await self.memory.replay_turn(session_id, None, key[1],
                                turn_fingerprint(turn, getattr(self.memory, 'include_prior', True)))
                        if replay.get('error') == 'turn_retry_conflict':
                            raise ValueError('Conflicting turn retry')
                        if 'error' in replay:
                            raise RuntimeError('memory_unavailable')
                        if replay.get('found') is True:
                            if not replay.get('agent_text'):
                                raise RuntimeError('turn_recovery_required')
                            saved = {'request': turn, **identity, 'agent_text': replay['agent_text'],
                                'verified_answer': replay['agent_text'],
                                'memory_include_prior': getattr(self.memory, 'include_prior', True)}
                            self._states[key] = saved
                            handoff = next((call['result'] for call in replay.get('tool_observations', [])
                                if call.get('name') == 'handoff.transfer'
                                and call.get('result', {}).get('status') == 'queued'), {})
                            response = TextTurnResponse(client_msg_id=turn.client_msg_id,
                                session_id=turn.session_id, agent_text=replay['agent_text'],
                                needs_handoff=bool(handoff.get('ticket_id')),
                                handoff_ticket_id=handoff.get('ticket_id'),
                                memory_update=MemoryUpdate(turn_saved=True,
                                    status='pending' if identity.get('customer_id') else 'not_applicable'))
                            self._responses[key] = response
                            return response
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
                    prepared_calls = [{**call, 'customer_id': identity.get('customer_id'),
                        'session_id': session_id, 'source_turn_id': str(turn.client_msg_id)}
                        for call in prepared_calls]
                    config = {"configurable": {"thread_id": session_id},
                              "run_name": "process-chat-turn"}
                    if trace:
                        config["callbacks"] = [trace[0]]
                    prior_session_calls = deepcopy([
                        *self._session_tool_calls[session_id], *prepared_calls])
                    state: TurnState = await self.graph.ainvoke(
                        {**seed, "request": turn, **deepcopy(identity),
                         "received_at_monotonic": started,
                         'prepared_tool_calls': prepared_calls,
                         "session_tool_calls": prior_session_calls,
                         "tool_calls": initial_calls}, config=config,
                    )
                    if state.get('erased_customer_id'):
                        self._forget_customer(state['erased_customer_id'])
                        session = self._session_states.setdefault(session_id, SessionState(
                            None, turn.on, getattr(self.memory, 'include_prior', True)))
                    response_text = state['agent_text']
                    if stream is not None:
                        state['agent_text'] = (stream.published if state.get('reply_error') else
                                               await stream.finish(response_text, state))
                        response_text = state['agent_text'] or response_text
                    if stream is not None or state.get('reply_error'):
                        state.update(await self.nodes.persist_agent(state))
                    session.update(state)
                    if not state.get("tool_failed"):
                        self._session_tool_calls[session_id].extend(prepared_calls)
                    self._session_tool_calls[session_id].extend(
                        {**deepcopy(call), 'customer_id': state.get('customer_id'),
                         'session_id': session_id, 'source_turn_id': str(turn.client_msg_id)}
                        for call in state.get('tool_calls', []))
                    self._session_tool_calls[session_id] = self._session_tool_calls[session_id][-64:]
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
            state['memory_include_prior'] = getattr(self.memory, 'include_prior', True)
            self._states[key] = state
            if state.get('reply_error'):
                log_event(turn, "chat", "failed", level=logging.ERROR,
                          reason=state['reply_error'])
                raise RuntimeError(state['reply_error'])
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
            if turn.delivery_mode == "voice":
                self._playback_tasks[key] = asyncio.create_task(self._expire_playback(key))
            log_event(turn, "chat", "completed",
                      duration_ms=round((time.perf_counter() - started) * 1000),
                      tool_calls=state.get("tool_count", 0),
                      needs_handoff=response.needs_handoff,
                      memory_writes=len(state.get("memory_writes", [])))
            return response


DeepHarnessRuntime = AgentHarnessRuntime
