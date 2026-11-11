"""M1 chat evaluation must use text persistence, never simulated voice playback."""
import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval_harness.benchmark_runner import run_scenario_call


@pytest.mark.parametrize('agent_kind', ['deep', 'react'])
def test_text_eval_commits_through_real_runtime_before_next_turn(monkeypatch, agent_kind):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'test'))
    from langchain_core.messages import AIMessage
    from app.agent.harness.runtime import AgentHarnessRuntime
    from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel

    memory = FakeMemory()
    model = FakeToolModel(replies=[AIMessage(content='Dạ, em nghe ạ.') for _ in range(2)])

    prepared = []

    class Runtime(AgentHarnessRuntime):
        async def prepare_session(self, request):
            prepared.append(request)
            return await super().prepare_session(request)

        async def record_playback(self, request):
            pytest.fail('text replies need no playback acknowledgement')

        async def run(self, request):
            assert request.delivery_mode == 'text'
            if request.text == 'tiếp':
                assert memory.turns[str(request.session_id)] == [
                    {'customer': 'chào', 'agent': 'Dạ, em nghe ạ.'}]
            return await super().run(request)

    runtime = Runtime(model, FakeGateway(), memory, agent_kind=agent_kind)

    async def wait(source):
        assert any(key[1] == source for key in memory.operations)

    rows = asyncio.run(run_scenario_call(runtime, 'X', 'call_1',
        {'customer_turns': ['chào', 'tiếp']}, date(2026, 10, 15), '0984726714',
        delivery_mode='text', wait_for_jobs=wait))
    assert len(rows) == len(memory.operations) == 2
    assert len(prepared) == 1
    assert not runtime._playback_tasks
    assert rows[1]['latency']['prepare_ms'] == 0
    assert all(r['latency']['ttft_is_proxy'] is False for r in rows)
    assert all(r['latency']['ttft_ms'] == r['latency']['total_ms'] for r in rows)


def test_text_latency_includes_runtime_persistence_but_not_worker_wait(monkeypatch):
    clock = [0.0]

    class Runtime:
        async def prepare_session(self, request):
            clock[0] += .125
            return SimpleNamespace(call_brief={'latency_ms': 125})

        async def run(self, request):
            assert request.delivery_mode == 'text'
            clock[0] += .25
            return SimpleNamespace(agent_text='Dạ.', call_brief={'latency_ms': 125})

        def state_for(self, request):
            return {'profile': {}, 'tool_calls': []}

    async def wait(source):
        clock[0] += 2

    monkeypatch.setattr('eval_harness.benchmark_runner.time.perf_counter', lambda: clock[0])
    rows = asyncio.run(run_scenario_call(Runtime(), 'X', 'call_2',
        {'customer_turns': ['chào']}, date(2026, 10, 15), '0984726714',
        delivery_mode='text', wait_for_jobs=wait))
    assert rows[0]['latency']['total_ms'] == 250
    assert rows[0]['latency']['prepare_ms'] == 125
    assert rows[0]['latency']['memory_finalize_ms'] == 2000
    assert rows[0]['call_brief_latency_ms'] == 125


def test_unknown_delivery_mode_fails_before_runtime_access():
    with pytest.raises(ValueError, match='delivery_mode'):
        asyncio.run(run_scenario_call(object(), 'X', 'call_1',
            {'customer_turns': ['chào']}, date(2026, 10, 15), '0984726714',
            delivery_mode='unknown'))


def test_measurement_metadata_distinguishes_chat_from_voice():
    from eval_harness.benchmark_runner import conversation_measurement
    chat = conversation_measurement('text')
    voice = conversation_measurement('voice')
    assert chat['delivery_mode'] == 'text'
    assert 'including persistence' in chat['lifecycle'] and 'prepare_session' in chat['lifecycle']
    assert chat['ttft_is_proxy'] is False
    assert chat['ttft_basis'] == 'nonstreaming_total_btc_rule_7'
    assert voice['delivery_mode'] == 'voice'
    chat['excluded'].append('mutated')
    assert 'mutated' not in conversation_measurement('text')['excluded']


def test_coordinator_forwards_text_delivery_to_child_process(tmp_path, monkeypatch):
    import json
    from eval_harness.run_official import _run_one
    commands = []
    trace = tmp_path / 'full.diagnostics_full.jsonl'
    trace.write_text('')
    trace.with_suffix('.report.json').write_text(json.dumps({'status': 'completed'}))

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr('eval_harness.run_official.subprocess.run', run)
    result = _run_one('full', tmp_path, 'deep', 7, 'r', tmp_path,
        btc_root=tmp_path, expected_database='offline', release={'release_id': 'offline'}, delivery_mode='text')
    assert result == trace
    command = commands[0]
    assert command[command.index('--delivery-mode') + 1] == 'text'
