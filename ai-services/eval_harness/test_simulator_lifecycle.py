import asyncio
from datetime import date
import json
from types import SimpleNamespace

from eval_harness.benchmark_runner import run_scenario_call
from eval_harness.customer_simulator import CustomerSimulator
from eval_harness.test_customer_simulator import BTC, Observer, scenario
from eval_harness.test_support import VoiceLifecycleStub


class Runtime(VoiceLifecycleStub):
    def __init__(self):
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return SimpleNamespace(agent_text='Phòng chị rộng bao nhiêu mét vuông?', call_brief=None)

    def state_for(self, request):
        return {'profile': {}, 'scoped_facts': {}, 'tool_calls': [], 'memory_writes': []}


def test_dynamic_customer_reuses_harness_and_keeps_labels_out_of_agent_input():
    async def run():
        data = scenario(persona='khach_goi_lan_3_het_kien_nhan')
        observer = Observer()
        sim = CustomerSimulator(data, 'call_3', btc_root=BTC, seed=7,
                                prior_facts={'room_area_m2': 25}, observer=observer)
        runtime = Runtime()
        rows = await run_scenario_call(runtime, 'S', 'call_3', data['calls']['call_3'],
            date(2026, 10, 15), '0900000000', customer_simulator=sim)
        assert len(rows) == len(runtime.requests) == sim.log()['n_turns'] == 2
        assert sim.log()['outcome'] == 'tu_choi'
        sent = json.dumps([r.model_dump(mode='json') for r in runtime.requests], ensure_ascii=False)
        assert all(field not in sent for field in ('success_if', 'must_not_ask', 'ground_truth_facts', 'semantic_requirements'))
        assert observer.payloads[0]['success_if'] == data['calls']['call_3']['success_if']
        assert all(r['latency']['stream_completed'] for r in rows)
    asyncio.run(run())


def test_simulated_configuration_logs_all_calls_and_baseline_control():
    from eval_harness.simulator_runner import simulate_configuration
    async def run():
        data = {'scenario_id': 'S', 'customer_phone': '0900000000', 'persona': 'khach_hoi_nhieu_khong_mua', 'calls': {
            f'call_{i}': {'channel': 'hotline', 'call_date': f'2026-10-{19+i}',
                'customer_goal': 'Hỏi thông tin, chưa mua.', 'customer_turns': ['Chị hỏi thông tin.'],
                'facts_established': {}, 'must_carry_over': [], 'must_not_ask': [],
                'success_if': {'tool_called': None, 'must_say_any': ['Dạ']},
                'semantic_requirements': [{'id': 'meaning', 'requirement': 'Trả lời đúng.', 'source_sections': ['FAQ-15']}]}
            for i in (1, 2)}}
        runtime = Runtime()
        runtime.memory = SimpleNamespace(include_prior=True)
        async def respond(request):
            runtime.requests.append(request)
            return SimpleNamespace(agent_text='Dạ, em hỗ trợ thông tin này.', call_brief=None)
        runtime.run = respond
        result = await simulate_configuration(runtime, {'S': data}, btc_root=BTC, seed=7,
            config='baseline_no_memory', run_id='offline', observer=Observer())
        assert runtime.memory.include_prior is False
        assert len(result['trace']) == len(result['logs']) == 2
        assert all(log['task_success'] is True and log['n_turns'] == 1 for log in result['logs'])
        assert result['supplemental']['complete'] is False
        assert all(r['config'] == 'baseline_no_memory' for r in result['trace'])
    asyncio.run(run())


def test_three_seed_experiment_uses_safe_controls_and_saves_final_memory(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from eval_harness import simulator_runner
    from eval_harness.test_customer_simulator import Observer
    source = tmp_path / 'source'
    source.mkdir()
    case = {'scenario_id': 'S', 'customer_phone': '0900000000', 'persona': 'khach_hoi_nhieu_khong_mua',
        'calls': {'call_1': {'channel': 'hotline', 'customer_goal': 'Hỏi thông tin, chưa mua.',
            'customer_turns': ['Chị hỏi thông tin.'], 'facts_established': {},
            'must_carry_over': [], 'must_not_ask': [],
            'success_if': {'tool_called': None, 'must_say_any': ['Dạ']},
            'semantic_requirements': [{'id': 'meaning', 'requirement': 'Trả lời đúng.', 'source_sections': ['FAQ-15']}]}}}
    (source / 'case.json').write_text(json.dumps(case))
    class OfflineRuntime(Runtime):
        def __init__(self):
            super().__init__()
            self.memory = SimpleNamespace(include_prior=True)
            self.tools = object()
        async def run(self, request):
            self.requests.append(request)
            return SimpleNamespace(agent_text='Dạ, em hỗ trợ thông tin này.', call_brief=None)
    monkeypatch.setattr('app.agent.factory.build_runtime', lambda *a, **k: OfflineRuntime())
    monkeypatch.setattr('app.infarstructure.llm.build_llm', lambda *a, **k: object())
    monkeypatch.setattr(simulator_runner, 'LLMObserver', lambda model: Observer())
    monkeypatch.setattr('app.knowledge.context.capture_release', AsyncMock(return_value={'release_id': 'r', 'manifest_hash': 'h'}))
    monkeypatch.setattr('eval_harness.seed_fingerprint.fingerprint_btc_source', AsyncMock(return_value='seed'))
    monkeypatch.setattr('eval.trace_audit.source_snapshot_digest', lambda *a: 'source')
    identity = {'database': 'offline', 'host': '127.0.0.1', 'port': 5432, 'server_started_at': 'test'}
    preflight = AsyncMock(return_value=identity)
    reset = AsyncMock(return_value=identity)
    monkeypatch.setattr('eval_harness.benchmark_runner.preflight_runtime', preflight)
    monkeypatch.setattr('eval_harness.benchmark_runner.prepare_runtime_for_eval', reset)
    monkeypatch.setattr('eval_harness.benchmark_runner.warm_up_configuration', AsyncMock())
    monkeypatch.setattr('eval_harness.benchmark_runner.wait_for_distillation', AsyncMock())
    async def writes(dsn, ids):
        return {source_id: [{'key': 'budget_vnd', 'value': 100, 'op': 'set'}] for source_id in ids}
    monkeypatch.setattr('eval_harness.benchmark_runner.read_distillation_writes', writes)
    args = SimpleNamespace(out=tmp_path / 'experiment', scenarios=source, btc_root=BTC,
                           expected_database='offline', seeds=[7, 17, 27])
    summary = asyncio.run(simulator_runner.run_experiment(args))
    assert summary['status'] == 'completed' and len(summary['runs']) == 6
    assert reset.await_count == preflight.await_count == 6
    assert summary['semantic_review_complete'] is False
    for config in ('full', 'baseline_no_memory'):
        assert summary['repeatability'][config]['complete'] is True
        for seed in (7, 17, 27):
            path = args.out / f'seed-{seed}' / config / 'trace.jsonl'
            saved = json.loads(path.read_text())
            assert saved['memory_writes'][0]['value'] == 100


def test_simulator_cli_requires_explicit_live_opt_in(tmp_path):
    import os
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-m', 'eval_harness.simulator_runner',
        '--scenarios', str(tmp_path), '--btc-root', str(BTC), '--out', str(tmp_path / 'out'),
        '--expected-database', 'offline'], capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': 'ai-services:.'})
    assert result.returncode == 2 and '--allow-model-calls' in result.stderr
    assert not (tmp_path / 'out').exists()
