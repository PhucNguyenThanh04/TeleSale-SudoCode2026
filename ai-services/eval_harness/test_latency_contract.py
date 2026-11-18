import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from eval_harness.benchmark_runner import warm_up_configuration, WarmupGateway


def test_three_warmups_do_not_write_business_or_memory_data():
    inner = SimpleNamespace(invoke=AsyncMock(side_effect=AssertionError('live tool')))
    gateway=WarmupGateway(inner)
    for name in ('order.create','handoff.transfer','memory.write','crm.get_customer'):
        asyncio.run(gateway.invoke(name,{}))
    assert not inner.invoke.called
    from app.agent.harness.observability import log_event
    async def respond(request):
        log_event({}, "execution", "phase_result", phase="model_invocation", status="succeeded")
        log_event({}, "execution", "phase_result", phase="postprocess", status="succeeded")
        return SimpleNamespace(agent_text='Dạ, em nghe ạ.', call_brief=None)
    from eval_harness.test_support import VoiceLifecycleStub
    runtime=VoiceLifecycleStub()
    runtime.run=AsyncMock(side_effect=respond)
    result=asyncio.run(warm_up_configuration(runtime))
    assert result['turns']==3 and runtime.run.await_count==3
    requests=[c.args[0] for c in runtime.run.call_args_list]
    assert len({str(r.session_id) for r in requests})==3


def test_post_response_worker_time_is_excluded_from_latency(tmp_path, monkeypatch):
    import json
    from eval_harness.benchmark_runner import run_configuration
    from test_entrypoint_parity import Runtime
    clock=[0.0]
    runtime=Runtime()
    async def respond(request):
        clock[0]+=0.04
        return SimpleNamespace(agent_text='Dạ',call_brief=None)
    async def wait(source):
        clock[0]+=10
    runtime.run=respond
    monkeypatch.setattr('eval_harness.benchmark_runner.time.perf_counter',lambda:clock[0])
    asyncio.run(run_configuration(scenarios={'X':{'calls':{'call_1':{'customer_turns':['a','b']}}}},
        config='full',runtime=runtime,run_id='r',out=tmp_path/'trace',wait_for_jobs=wait,
        capture_writes=AsyncMock(return_value={})))
    rows=[json.loads(x) for x in (tmp_path/'trace').read_text().splitlines()]
    assert all(39 <= r['latency']['total_ms'] <= 40 for r in rows)
    assert all(r['latency']['ttft_ms']==r['latency']['total_ms'] for r in rows)


def test_warmup_runs_real_graph_and_memory_contract_without_service_writes(monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'test'))
    from test_deep_memory import FakeToolModel
    from langchain_core.messages import AIMessage
    from app.agent.harness.runtime import AgentHarnessRuntime
    from app.agent.memory.store import MCPMemoryStore

    inner=SimpleNamespace(invoke=AsyncMock(side_effect=AssertionError('external tool called')))
    gateway=WarmupGateway(inner)
    gateway.invoke=AsyncMock(wraps=gateway.invoke)
    runtime=AgentHarnessRuntime(FakeToolModel(replies=[AIMessage(content='Dạ, em nghe ạ.') for _ in range(3)]),
        gateway,MCPMemoryStore(gateway))
    result=asyncio.run(warm_up_configuration(runtime))
    assert result=={'turns':3,'scored':False,'execution_health':'healthy'}
    commits=[c for c in gateway.invoke.call_args_list if c.args[0]=='memory.write']
    assert len(commits)==3
    assert len({c.args[1]['session_id'] for c in commits})==3
    assert not inner.invoke.called
