"""Transcript eval exercises the same runtime lifecycle as the deployed voice API."""
import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval_harness.benchmark_runner import run_scenario_call


@pytest.mark.parametrize('agent_kind', ['deep', 'react'])
def test_real_runtime_prepares_and_commits_full_playback_before_next_turn(monkeypatch, agent_kind):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'test'))
    from langchain_core.messages import AIMessage
    from app.agent.harness.runtime import AgentHarnessRuntime
    from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel
    from eval_harness.turn_diagnostics import TurnDiagnostics

    monkeypatch.setenv('EVAL_DECISION_DIAGNOSTICS', '1')
    diagnostics = TurnDiagnostics()
    events = []
    memory = FakeMemory()

    class Runtime(AgentHarnessRuntime):
        async def prepare_session(self, request):
            events.append('prepare')
            assert not model.seen
            return await super().prepare_session(request)

        async def run(self, request):
            events.append('response')
            assert request.delivery_mode == 'voice'
            assert request.input_mode == 'asr_transcript'
            if request.text == 'tiếp':
                assert memory.turns[str(request.session_id)] == [
                    {'customer': 'chào', 'agent': 'Dạ, em nghe ạ.'}]
            response = await super().run(request)
            assert len(memory.turns.get(str(request.session_id), [])) == (request.text == 'tiếp')
            return response

        async def record_playback(self, request):
            events.append('playback')
            assert not request.interrupted
            assert request.played_chars == len('Dạ, em nghe ạ.')
            return await super().record_playback(request)

    model = FakeToolModel(replies=[AIMessage(content='Dạ, em nghe ạ.') for _ in range(2)])
    runtime = Runtime(model, FakeGateway(), memory, agent_kind=agent_kind)

    async def wait(source_id):
        events.append('worker')
        assert any(key[1] == source_id for key in memory.operations)

    async def run():
        rows = await run_scenario_call(runtime, 'X', 'call_1',
            {'customer_turns_asr': ['chào', 'tiếp']}, date(2026, 10, 15), '0984726714',
            wait_for_jobs=wait, diagnostics=diagnostics)
        assert not runtime._playback_tasks
        assert len(memory.operations) == 2
        return rows

    rows = asyncio.run(run())
    assert len(rows) == 2
    assert events == ['prepare', 'response', 'playback', 'response', 'playback', 'worker', 'worker']
    assert sum(e.get('event') == 'final_commit' for e in diagnostics.decisions) == 2
    assert all(stage['memory_write_status'] == 'ok' for stage in diagnostics.stages)


def test_phase_timings_exclude_prepare_playback_and_worker(monkeypatch):
    clock = [0.0]
    events = []

    class Runtime:
        async def prepare_session(self, request):
            events.append('prepare')
            clock[0] += 2

        async def run(self, request):
            events.append('response')
            clock[0] += .125
            return SimpleNamespace(agent_text='Dạ.', call_brief=None)

        def state_for(self, request):
            return {'profile': {}, 'scoped_facts': {}, 'tool_calls': []}

        async def record_playback(self, request):
            events.append('playback')
            clock[0] += 3

    async def wait(source):
        events.append('worker')
        clock[0] += 4

    monkeypatch.setattr('eval_harness.benchmark_runner.time.perf_counter', lambda: clock[0])
    rows = asyncio.run(run_scenario_call(Runtime(), 'X', 'call_1',
        {'customer_turns': ['chào', 'tiếp']}, date(2026, 10, 15), '0984726714', wait_for_jobs=wait))
    assert events == ['prepare', 'response', 'playback', 'response', 'playback', 'worker', 'worker']
    assert [row['latency']['prepare_ms'] for row in rows] == [2000, 0]
    for row in rows:
        assert row['latency']['response_ms'] == row['latency']['total_ms'] == 125
        assert row['latency']['memory_finalize_ms'] == 7000
        assert row['latency']['ttft_is_proxy'] is True


def test_prepare_failure_stops_before_model():
    class Runtime:
        async def prepare_session(self, request):
            raise RuntimeError('session_preparation_unavailable')

        async def run(self, request):
            pytest.fail('must not infer after failed preparation')

    with pytest.raises(RuntimeError, match='session_preparation_unavailable'):
        asyncio.run(run_scenario_call(Runtime(), 'X', 'call_1', {'customer_turns': ['chào']},
                                     date(2026, 10, 15), '0984726714'))


def test_playback_failure_keeps_response_and_stops_call(monkeypatch):
    clock = [0.0]
    rows = []

    class Runtime:
        async def prepare_session(self, request):
            pass

        async def run(self, request):
            clock[0] += .125
            return SimpleNamespace(agent_text='Dạ.', call_brief=None)

        def state_for(self, request):
            return {'profile': {}, 'scoped_facts': {}, 'tool_calls': []}

        async def record_playback(self, request):
            clock[0] += 3
            raise RuntimeError('private playback failure')

    monkeypatch.setattr('eval_harness.benchmark_runner.time.perf_counter', lambda: clock[0])
    with pytest.raises(RuntimeError, match='playback_failed'):
        asyncio.run(run_scenario_call(Runtime(), 'X', 'call_1',
            {'customer_turns': ['chào', 'tiếp']}, date(2026, 10, 15), '0984726714', rows_out=rows))
    assert len(rows) == 1
    assert rows[0]['agent_text'] == 'Dạ.'
    assert rows[0]['memory_error'] == 'playback_failed'
    assert rows[0]['latency']['response_ms'] == 125
    assert rows[0]['latency']['memory_finalize_ms'] == 3000


def test_empty_call_does_not_prepare():
    assert asyncio.run(run_scenario_call(object(), 'X', 'call_1', {'customer_turns': []},
                                        date(2026, 10, 15), '0984726714')) == []


def test_playback_uses_original_reply_before_trace_redaction():
    from eval_harness.test_support import VoiceLifecycleStub
    original = 'Số điện thoại 0984726714.'

    class Runtime(VoiceLifecycleStub):
        async def run(self, request):
            return SimpleNamespace(agent_text=original, call_brief=None)

        def state_for(self, request):
            return {'profile': {}, 'tool_calls': []}

        async def record_playback(self, request):
            assert request.played_chars == len(original)
            assert request.interrupted is False

    rows = asyncio.run(run_scenario_call(Runtime(), 'X', 'call_1', {'customer_turns': ['chào']},
                                        date(2026, 10, 15), '0984726714'))
    assert '0984726714' not in rows[0]['agent_text']


def test_preparation_identity_and_brief_match_the_call():
    from eval_harness.test_support import VoiceLifecycleStub
    prepared = []

    class Runtime(VoiceLifecycleStub):
        async def prepare_session(self, request):
            prepared.append(request)
            return SimpleNamespace(call_brief={'latency_ms': 750})

        async def run(self, request):
            assert request.session_id == prepared[-1].session_id
            assert request.channel == prepared[-1].channel == 'zalo_oa'
            assert request.channel_identity == prepared[-1].channel_identity == 'zalo-user'
            assert request.on == prepared[-1].on == date(2026, 10, 17)
            assert request.input_mode == 'chat_teencode'
            assert request.delivery_mode == 'voice'
            return SimpleNamespace(agent_text='Dạ.', call_brief={'latency_ms': 7})

        def state_for(self, request):
            return {'profile': {}, 'tool_calls': []}

    rows = asyncio.run(run_scenario_call(Runtime(), 'X', 'call_2',
        {'customer_turns': ['chào', 'tiếp'], 'channel': 'zalo_oa', 'channel_identity': 'zalo-user',
         'days_later': 2, 'input_mode': 'chat_teencode'}, date(2026, 10, 15), '0984726714'))
    assert len(prepared) == 1
    assert rows[0]['call_brief_latency_ms'] == 750
    assert rows[1].get('call_brief_latency_ms') is None
