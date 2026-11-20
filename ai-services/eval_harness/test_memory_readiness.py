import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

from eval_harness.benchmark_runner import run_scenario_call
from eval_harness.test_support import VoiceLifecycleStub


def test_next_turn_does_not_wait_for_enrichment_and_final_artifacts_do():
    events = []
    sources = []

    class Runtime(VoiceLifecycleStub):
        async def run(self, request):
            sources.append(str(request.client_msg_id))
            events.append('response')
            return SimpleNamespace(agent_text='Dạ.', call_brief=None)

        def state_for(self, request):
            return {'profile': {}, 'tool_calls': [], 'memory_writes': []}

        async def record_playback(self, request):
            events.append('commit')

    async def wait(source_id):
        assert events.count('response') == 2
        events.append('enrichment')

    async def capture(ids):
        assert events.count('enrichment') == 2
        assert ids == sources
        return {source: [{'key': 'room_area_m2', 'value': 25, 'op': 'set'}] for source in ids}

    rows = asyncio.run(run_scenario_call(Runtime(), 'X', 'call_1', {'customer_turns': ['a', 'b']},
        date(2026, 10, 15), '0900000000', wait_for_jobs=wait, capture_writes=capture, delivery_mode='voice'))
    assert events == ['response', 'commit', 'response', 'commit', 'enrichment', 'enrichment']
    assert all(row['memory_writes'][0]['value'] == 25 for row in rows)
    assert all(row['memory_enrichment_status'] == 'completed' for row in rows)


def test_background_wait_is_timed_separately_from_essential_commit(monkeypatch):
    clock = [0.0]

    class Runtime(VoiceLifecycleStub):
        async def run(self, request):
            clock[0] += .125
            return SimpleNamespace(agent_text='Dạ.', call_brief=None)

        async def record_playback(self, request):
            clock[0] += .25

        def state_for(self, request):
            return {'profile': {}, 'tool_calls': []}

    async def wait(source_id):
        clock[0] += 4

    monkeypatch.setattr('eval_harness.benchmark_runner.time.perf_counter', lambda: clock[0])
    rows = asyncio.run(run_scenario_call(Runtime(), 'X', 'call_1', {'customer_turns': ['a']},
        date(2026, 10, 15), '0900000000', wait_for_jobs=wait, capture_writes=AsyncMock(return_value={}), delivery_mode='voice'))
    assert rows[0]['latency']['response_ms'] == 125
    assert rows[0]['latency']['essential_commit_ms'] == 250
    assert rows[0]['latency']['background_finalize_ms'] == 4000


def test_unsaved_working_state_stops_before_next_turn():
    import pytest
    from app.schemas.agent import MemoryUpdate
    for mode in ('text', 'voice'):
        called = []
        rows = []
        class Runtime(VoiceLifecycleStub):
            async def run(self, request):
                called.append(request.text)
                return SimpleNamespace(agent_text='Dạ.', call_brief=None,
                                       memory_update=MemoryUpdate(turn_saved=False, status='unavailable'))
            async def record_playback(self, request):
                return MemoryUpdate(turn_saved=False, status='unavailable')
            def state_for(self, request):
                return {'profile': {}, 'tool_calls': []}
        with pytest.raises(RuntimeError, match='essential_state_not_ready'):
            asyncio.run(run_scenario_call(Runtime(), 'X', 'call_1', {'customer_turns': ['a', 'b']},
                date(2026, 10, 15), '0900000000', rows_out=rows, delivery_mode=mode))
        assert called == ['a']
        assert rows[0]['memory_error'] == 'essential_state_not_ready'


def test_text_persistence_records_essential_commit_duration(monkeypatch):
    from app.agent.harness.agent_nodes import AgentNodes
    from app.schemas.agent import TextTurnRequest
    from uuid import uuid4
    clock = [0.0]
    async def commit(*args, **kwargs):
        clock[0] += .25
        return {'turn_no': 1, 'memory_writes': []}
    monkeypatch.setattr('time.perf_counter', lambda: clock[0])
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(), text='a',
        channel='hotline', channel_identity='0900000000', on=date(2026, 10, 15), input_mode='clean')
    nodes = AgentNodes(None, None, SimpleNamespace(commit_turn=commit), 5, 6)
    result = asyncio.run(nodes.persist_agent({'request': request, 'safe_text': 'a', 'agent_text': 'Dạ.'}))
    assert result['memory_commit_ms'] == 250
