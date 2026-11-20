import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from pydantic import TypeAdapter
from eval_harness.benchmark_runner import run_scenario_call, assert_trace_ready
from eval_harness.test_support import VoiceLifecycleStub


class Runtime(VoiceLifecycleStub, SimpleNamespace):
    pass


def test_runtime_failure_never_waits_for_nonexistent_memory_job():
    committed = []
    requests = []
    async def respond(request):
        requests.append(request)
        if len(requests) == 2:
            TypeAdapter(int).validate_python(None)
        committed.append(str(request.client_msg_id))
        return SimpleNamespace(agent_text='Dạ.', call_brief=None)
    runtime = Runtime(run=respond, state_for=lambda req: {
        'profile': {}, 'scoped_facts': {}, 'tool_calls': [], 'memory_writes': []})
    async def wait(source):
        if source not in committed:
            raise RuntimeError('missing turn for LangMem job')
    async def capture(sources):
        assert set(sources) <= set(committed)
        return {source: ([{'key': 'size', 'value': 41, 'op': 'set', 'customer_id': 'C'}]
                if len(committed) == 2 and source == committed[0] else []) for source in sources}
    capture = AsyncMock(side_effect=capture)
    wait = AsyncMock(side_effect=wait)
    rows = asyncio.run(run_scenario_call(runtime, 'LOCAL', 'call_1',
        {'customer_turns': ['Chào', 'Có giảm không?', 'Xác minh khách']}, date(2026, 11, 5),
        '0900000000', wait_for_jobs=wait, capture_writes=capture))
    assert rows[1]['agent_text'] == '[ERROR: ValidationError]'
    assert all('memory_error' not in row for row in rows)
    assert rows[0]['memory_writes'][0]['source'] == 'call_1#turn1'
    assert rows[0]['memory_writes'][0]['value'] == 41
    assert {c.args[0] for c in wait.call_args_list} == set(committed)
    assert capture.call_args.args[0] == committed
    with pytest.raises(RuntimeError, match='turn failed'):
        assert_trace_ready({'LOCAL': {'calls': {'call_1': {'customer_turns': ['a','b','c']}}}},
                           {('LOCAL','call_1'): rows})


def test_final_wait_failure_is_scoped_to_its_source_turn():
    requests = []
    async def respond(request):
        requests.append(str(request.client_msg_id))
        return SimpleNamespace(agent_text='Dạ.', call_brief=None)
    runtime = Runtime(run=respond, state_for=lambda req: {
        'profile': {}, 'tool_calls': [], 'memory_writes': []})
    counts = {}
    async def wait(source):
        counts[source] = counts.get(source, 0) + 1
        if source == requests[0]:
            raise TimeoutError('backfill timeout')
    async def capture(sources):
        return {source: [] for source in sources}
    rows = asyncio.run(run_scenario_call(runtime, 'LOCAL', 'call_1',
        {'customer_turns': ['Chào', 'Xác minh']}, date(2026, 11, 5), '0900000000',
        wait_for_jobs=wait, capture_writes=capture))
    assert rows[0]['memory_error'] == 'timeout'
    assert 'memory_error' not in rows[1]
    assert counts == {source: 1 for source in requests}


@pytest.mark.parametrize('failure', ['timeout', 'job_failed', 'capture_failed'])
def test_real_memory_errors_are_preserved_and_still_block_scoring(failure):
    sources = []
    async def respond(request):
        sources.append(str(request.client_msg_id))
        return SimpleNamespace(agent_text='Dạ.', call_brief=None)
    runtime = Runtime(run=respond, state_for=lambda req: {
        'profile': {}, 'tool_calls': [], 'memory_writes': []})
    async def wait(source):
        if source == sources[0] and failure != 'capture_failed':
            if failure == 'timeout':
                raise TimeoutError('worker timeout')
            raise RuntimeError('worker failed')
    async def capture(ids):
        if failure == 'capture_failed':
            assert ids == sources
            raise RuntimeError('capture failed')
        assert sources[0] not in ids
        return {source: [] for source in ids}
    rows = asyncio.run(run_scenario_call(runtime, 'LOCAL', 'call_1',
        {'customer_turns': ['Chào', 'Xác minh']}, date(2026, 11, 5), '0900000000',
        wait_for_jobs=wait, capture_writes=capture))
    assert rows[0]['memory_error'] == failure
    if failure == 'capture_failed':
        assert rows[1]['memory_error'] == 'capture_failed'
    else:
        assert 'memory_error' not in rows[1]
    with pytest.raises(RuntimeError, match='memory job failed'):
        assert_trace_ready({'LOCAL': {'calls': {'call_1': {'customer_turns': ['a','b']}}}},
                           {('LOCAL','call_1'): rows})


def test_all_runtime_failures_never_attempt_memory_capture():
    runtime = Runtime(run=AsyncMock(side_effect=ValueError('runtime error')))
    wait, capture = AsyncMock(), AsyncMock()
    rows = asyncio.run(run_scenario_call(runtime, 'LOCAL', 'call_1',
        {'customer_turns': ['Chào', 'Có giảm không?']}, date(2026, 11, 5), '0900000000',
        wait_for_jobs=wait, capture_writes=capture))
    assert all(r['agent_text'] == '[ERROR: ValueError]' for r in rows)
    assert all('memory_error' not in r for r in rows)
    wait.assert_not_called()
    capture.assert_not_called()
