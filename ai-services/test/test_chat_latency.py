"""Offline latency contracts: remove repeated work without changing business evidence."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agent.harness.observability import capture_diagnostic_events, safe_diagnostic_event, trace_node
from app.agent.implementations.business_agent import BusinessOnlyMiddleware, BusinessTools
from app.schemas.agent import TextTurnRequest


def state():
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(), channel='hotline',
        channel_identity='0900000000', on=date(2026, 10, 15), text='Tìm quạt', input_mode='clean')
    return {'request': request, 'safe_text': request.text, 'identity_status': 'known',
            'customer_id': 'C1', 'tool_calls': [], 'profile': {}}


def test_tool_schemas_are_reused_but_invocations_keep_their_own_turn():
    async def run():
        states = [state(), state()]
        gateways = [SimpleNamespace(invoke=AsyncMock(return_value={'items': [], 'total': 0})) for _ in states]
        tools = [{t.name: t for t in BusinessTools(g, s, 3,
                  lambda: datetime.now(timezone.utc)).langchain_tools()} for g, s in zip(gateways, states)]
        assert all(tools[0][name].args_schema is tools[1][name].args_schema for name in tools[0])
        await tools[0]['catalog_search'].ainvoke({'query': 'quạt'})
        assert len(states[0]['tool_calls']) == 1 and states[1]['tool_calls'] == []
        await tools[1]['catalog_search'].ainvoke({'query': 'máy lọc'})
        assert states[0]['tool_calls'][0]['args']['query'] == 'quạt'
        assert states[1]['tool_calls'][0]['args']['query'] == 'máy lọc'
        assert all(g.invoke.await_count == 1 for g in gateways)
    asyncio.run(run())


def test_existing_node_timing_is_captured_without_payload():
    class Node:
        @trace_node('retrieve_context')
        async def run(self, turn):
            return {'ok': True}
    with capture_diagnostic_events() as events, patch('time.perf_counter', side_effect=[0, 1.25]):
        assert asyncio.run(Node().run({'private': '0900000000'})) == {'ok': True}
    assert events == [{'step': 'retrieve_context', 'event': 'completed', 'duration_ms': 1250}]
    assert safe_diagnostic_event('persist', 'completed', {'duration_ms': 12,
        'customer_text': '0900000000'}) == {'step': 'persist', 'event': 'completed', 'duration_ms': 12}


@pytest.mark.parametrize('duration', [-1, float('nan'), float('inf'), '0900000000', True])
def test_invalid_timing_cannot_enter_diagnostics(duration):
    assert safe_diagnostic_event('run_agent', 'model_timing', {'duration_ms': duration}) is None


@pytest.mark.parametrize('fail', [False, True])
def test_each_llm_request_records_duration_in_existing_diagnostics(fail):
    async def run():
        clock = [0.0]
        business = BusinessTools(None, state(), 3, lambda: datetime.now(timezone.utc))
        request = SimpleNamespace(tools=[], override=lambda **kwargs: request)
        response = object()
        async def handle(_):
            clock[0] += .125
            if fail:
                raise OSError('private')
            return response
        with capture_diagnostic_events() as events, patch('time.perf_counter', side_effect=lambda: clock[0]):
            if fail:
                with pytest.raises(OSError):
                    await BusinessOnlyMiddleware(business).awrap_model_call(request, handle)
            else:
                assert await BusinessOnlyMiddleware(business).awrap_model_call(request, handle) is response
        assert {'step': 'run_agent', 'event': 'model_timing', 'duration_ms': 125} in events
    asyncio.run(run())


def test_tool_network_time_is_captured_separately_from_model_time():
    async def run():
        clock = [0.0]
        async def invoke(name, args):
            clock[0] += .25
            return {'items': [], 'total': 0}
        business = BusinessTools(SimpleNamespace(invoke=invoke), state(), 3, lambda: datetime.now(timezone.utc))
        with capture_diagnostic_events() as events, patch('time.perf_counter', side_effect=lambda: clock[0]):
            await business.invoke('catalog.search', {'query': 'quạt'})
        assert {'step': 'call_tool', 'event': 'tool_timing', 'tool': 'catalog.search', 'duration_ms': 250} in events
    asyncio.run(run())


@pytest.mark.parametrize('fail', [False, True, 'cancel'])
def test_memory_projection_reads_overlap_and_finish_before_transaction_release(fail):
    from test_mcp_memory import TurnRepo
    from app.mcp_servers.mcp_memory.services.memory import read
    async def run():
        started = [asyncio.Event(), asyncio.Event()]
        finished = [False, False]
        released = []
        class Repo(TurnRepo):
            @asynccontextmanager
            async def transaction(self):
                try:
                    yield object()
                finally:
                    released.append(list(finished))
            async def order_links(self, *_):
                return []
        async def versions(index):
            started[index].set()
            try:
                await started[1-index].wait()
                if fail:
                    if fail is True and index == 0:
                        raise OSError('private')
                    await asyncio.Event().wait()
                return []
            finally:
                finished[index] = True
        projector = SimpleNamespace(list_fact_versions=lambda _: versions(0),
                                    list_episode_versions=lambda _: versions(1))
        if fail == 'cancel':
            task = asyncio.create_task(read(Repo(), 'C1', str(uuid4()), projector=projector))
            await asyncio.gather(*(event.wait() for event in started))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await read(Repo(), 'C1', str(uuid4()), projector=projector)
            assert ('error' in result) is fail
            if fail:
                assert result == {'error': 'memory_store_unavailable'}
        assert finished == [True, True] and released == [[True, True]]
    asyncio.run(run())


def test_new_timings_survive_the_existing_eval_sidecar_and_reject_payloads(tmp_path):
    import json
    from eval_harness.turn_diagnostics import TurnDiagnostics, verify_turn_diagnostics
    from app.agent.harness.observability import log_event
    current = state()
    row = {'run_id': 'offline', 'config': 'full', 'scenario_id': 'CASE', 'call': 'call_1',
           'turn': 1, 'agent_text': 'Dạ.', 'questions': [], 'claims': [], 'tool_calls': [], 'memory_writes': []}
    with capture_diagnostic_events() as events:
        log_event(current, 'run_agent', 'model_timing', duration_ms=125, private='0900000000')
        log_event(current, 'call_tool', 'tool_timing', tool='catalog.search', duration_ms=250)
    collector = TurnDiagnostics()
    collector.observe(current['request'], None, current, row, events)
    trace = tmp_path/'trace.jsonl'; trace.write_text(json.dumps(row)+'\n')
    refs = collector.write(trace)
    assert verify_turn_diagnostics(trace, refs) == refs
    data = trace.with_suffix('.events.json').read_text()
    assert '0900000000' not in data and 'duration_ms' in data
    assert json.loads(data)[0]['runtime_events'] == events
    assert safe_diagnostic_event('call_tool', 'tool_timing', {'duration_ms': 1, 'tool': {}}) is None


@pytest.mark.parametrize('fail', [False, True])
def test_read_only_prompt_fetch_overlaps_tool_preparation_and_preserves_errors(fail):
    import threading
    from langchain_core.messages import AIMessage
    from app.agent.harness.agent_nodes import AgentNodes
    started = threading.Event()
    release = threading.Event()
    def prompt(*_):
        started.set()
        assert release.wait(1), 'preparation never released prompt read'
        return 'offline prompt'
    async def prepare(_):
        assert await asyncio.to_thread(started.wait, .25), 'prompt fetch still waits for tool preparation'
        release.set()
        if fail:
            raise OSError('private')
        return False
    agent = SimpleNamespace(ainvoke=AsyncMock(return_value={'messages': [AIMessage(content='Dạ.')] }))
    async def run():
        nodes = AgentNodes(None, None, None, 3, 3)
        with patch('app.agent.harness.agent_nodes.text_prompt', side_effect=prompt), \
             patch.object(BusinessTools, 'prepare_consultation', prepare), \
             patch('app.agent.harness.agent_nodes.build_agent', return_value=agent):
            try:
                if fail:
                    with pytest.raises(OSError):
                        await nodes.run_agent(state())
                    agent.ainvoke.assert_not_awaited()
                else:
                    assert (await nodes.run_agent(state()))['agent_draft'] == 'Dạ.'
            finally:
                release.set()
    asyncio.run(run())
