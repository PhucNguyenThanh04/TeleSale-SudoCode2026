"""Three-arm experiment orchestration must not spend a fourth model run."""
import asyncio
import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval_harness.test_knowledge_auto_review import plan, repo, row


def test_three_arm_report_separates_answer_success_from_new_evidence():
    from eval_harness.knowledge_triplet import comparison_report
    p = plan(); before = [row()]; after = [row('Cần giữ nguyên hộp.')]
    approved = [{'case_id': 'condition', 'revision_id': 'revision', 'kind': 'faq',
                 'sources': p['cases'][0]['sources']}]
    report = comparison_report(p, before, before, after, approved, 'k1')
    assert report['gap_answer_accuracy']['full_k1']['passed'] == 1
    assert report['new_revision_used']['passed'] == 0
    after[0]['tool_calls'][0]['result'] = {'context': {'knowledge_release_id': 'k1'},
        'evidence': [{'chunk_id': 'KG-revision'}]}
    assert comparison_report(p, before, before, after, approved, 'k1')['new_revision_used']['passed'] == 1


def test_changed_artifact_is_rejected_before_resume(tmp_path):
    from eval_harness.knowledge_triplet import tree_hash
    (tmp_path/'input.json').write_text('original')
    before = tree_hash(tmp_path)
    (tmp_path/'input.json').write_text('changed')
    assert before != tree_hash(tmp_path)


@pytest.mark.parametrize('mode', ['complete', 'interrupted_publication', 'no_gaps', 'changed_k0', 'changed_k1', 'real_scoring', 'boot_replaced'])
def test_orchestration_runs_pair_then_only_full_k1_and_resumes_without_models(tmp_path, monkeypatch, mode):
    from eval_harness import knowledge_triplet as mod
    from unittest.mock import AsyncMock
    boot_check = AsyncMock()
    monkeypatch.setattr(mod, 'require_ready', boot_check)
    if mode == 'boot_replaced': monkeypatch.setenv('SYSTEM_BOOT_ID', 'original-boot')
    r = repo(); calls = []
    async def setup():
        await r.put('permissions', 'simulated-reviewer', {'permissions': ['knowledge_review']})
        await r.put('active', 'current', {'release_id': 'k0'})
        await r.put('releases', 'k0', {'id': 'k0', 'manifest': {'items': [{'id': 'old-revision'}],
            'index_kind': 'hybrid', 'source_hashes': {'PUBLIC': 'hash'}, 'content_hashes': {'PUBLIC': 'content'}}})
    asyncio.run(setup())
    async def identity(): return {'database': 'telesale'}
    r.database_identity = identity
    scenarios = tmp_path/'scenarios'; scenarios.mkdir()
    (scenarios/'case.json').write_text(json.dumps({'scenario_id': 'LOCAL', 'calls': {'call_1': {
        'customer_turns': [row()['user_text']]}}}))
    args = Namespace(scenarios=scenarios, btc_root=tmp_path/'btc', expected_database='telesale',
        agent='deep', seed=7, out_root=tmp_path/'runs', actor='simulated-reviewer', resume=None,
        delivery_mode='text', worker_timeout=2, approval_plan=tmp_path/'plan.json')
    args.approval_plan.write_text(json.dumps(plan()))
    settings = SimpleNamespace(app_env='test', agent_guardrails_enabled=True, knowledge_enabled=True,
        model_dump=lambda **kwargs: {'model': 'offline'})
    metadata = {'knowledge_release': {'release_id': 'k0', 'manifest_hash': 'hash0'},
        'database_identity': {'database': 'telesale'}, 'seed_digest': 'seed', 'source_digest': 'code'}
    if mode == 'real_scoring':
        metadata.update(seed_id='seed-7', model_id='offline', model_params={'temperature': 0}, tool_mode='mcp',
            guardrails={'enabled': True}, hardware={'cpu': 'offline'}, started_at_utc='2026-11-13T00:00:00Z')
    async def pair(**kwargs):
        assert kwargs['baseline_first'] is True
        calls.extend(['baseline', 'full_k0'])
        out = kwargs['out_root']/'pair'; out.mkdir(parents=True)
        import shutil
        shutil.copytree(scenarios, out/'scenarios')
        if mode == 'real_scoring':
            from eval_harness.btc_release import prepare_btc_release
            from eval_harness.test_official_pipeline import BTC
            prepare_btc_release(BTC, out/'btc-release')
        else:
            (out/'btc-release').mkdir()
        for name, config in [('full', 'full'), ('baseline', 'baseline_no_memory')]:
            trace = out/f'{name}.jsonl'
            value = row() | {'config': config, 'questions': [], 'claims': [],
                'customer_text': row()['user_text'], 'latency': {'total_ms': 10, 'ttft_ms': 10}}
            trace.write_text(json.dumps(value)+'\n')
            trace.with_suffix('.report.json').write_text(json.dumps({'run_id': value['run_id'], 'config': config,
                'database_identity': metadata['database_identity'], 'knowledge_release_id': 'k0'}))
            mod.write_extraction_sidecar(trace, out/f'{name}.extraction.jsonl')
        if mode == 'real_scoring':
            from eval_harness.official_pipeline import publish_pair
            publish_pair(out/'scenarios', out/'full.jsonl', out/'baseline.jsonl', out/'btc_score.json',
                dict(metadata, app_env='test', expected_database='telesale'), btc_root=out/'btc-release')
        else:
            (out/'full.manifest.json').write_text(json.dumps(metadata))
            (out/'btc_score.json').write_text(json.dumps({'system': {}, 'baseline': {}}))
        (out/'run.json').write_text(json.dumps({'status': 'validated', 'execution_health': 'healthy',
            'traces': {'full': 'full.jsonl', 'baseline_no_memory': 'baseline.jsonl'}}))
        return out
    async def review(*args, **kwargs):
        if mode == 'no_gaps': return {'approval_mode': 'simulated_pre_reviewed_plan', 'approved': [], 'skipped': []}
        return {'approval_mode': 'simulated_pre_reviewed_plan', 'approved': [{'case_id': 'condition',
            'revision_id': 'revision', 'kind': 'faq', 'sources': plan()['cases'][0]['sources']}], 'skipped': []}
    activations = []
    async def cmd(repo, actor, action, payload):
        if action == 'prepare_release':
            assert payload['revision_ids'] == ['old-revision', 'revision']
            return {'id': 'k1', 'manifest_hash': 'hash1', 'manifest': {
                'items': [{'id': 'old-revision'}, {'id': 'revision'}], 'index_kind': 'hybrid',
                'source_hashes': {'PUBLIC': 'hash', 'KG-revision': 'refs'},
                'content_hashes': {'PUBLIC': 'content', 'KG-revision': 'answer'}}}
        assert action == 'activate_release'
        await repo.put('active', 'current', {'release_id': 'k1'})
        activations.append('activated')
        if mode == 'interrupted_publication' and len(activations) == 1:
            raise RuntimeError('interrupted after activation')
    def single(config, scenarios, agent, seed, run_id, out, **kwargs):
        assert config == 'full' and kwargs['release']['release_id'] == 'k1'
        calls.append('full_k1'); path=out/'full.diagnostics_full.jsonl'
        value = row('Cần giữ nguyên hộp.') | {'questions': [], 'claims': [],
            'customer_text': row()['user_text'], 'latency': {'total_ms': 10, 'ttft_ms': 10}}
        path.write_text(json.dumps(value)+'\n')
        path.with_suffix('.report.json').write_text(json.dumps({'status': 'completed',
            'database_identity': {'database': 'telesale'}, 'knowledge_release_id': 'k1', 'safety_issues': [],
            'run_id': value['run_id'], 'config': 'full'}))
        return path
    def score(*args, **kwargs):
        args[3].write_text(json.dumps({'system': {}, 'baseline': {}})); return {}
    monkeypatch.setattr(mod, 'run_pair', pair); monkeypatch.setattr(mod, 'auto_review', review)
    monkeypatch.setattr(mod, 'load_scenarios', lambda *a, **kw: {'LOCAL': {'calls': {'call_1': {
        'customer_turns': [row()['user_text']]}}}})
    monkeypatch.setattr(mod, 'command', cmd); monkeypatch.setattr(mod, '_run_one', single)
    if mode != 'real_scoring': monkeypatch.setattr(mod, 'score_pair', score)
    monkeypatch.setattr(mod, 'source_snapshot_digest', lambda _: 'code')
    async def fingerprint(_): return 'seed'
    monkeypatch.setattr(mod, 'fingerprint_btc_source', fingerprint)
    monkeypatch.setattr(mod, 'database_url', lambda _: 'offline')
    if mode != 'real_scoring': monkeypatch.setattr(mod, 'audit_trace', lambda *a, **kw: {'errors': []})
    monkeypatch.setattr(mod, 'verify_report_turn_diagnostics', lambda _: {})
    monkeypatch.setattr(mod, 'trace_execution_health', lambda _: 'healthy')
    if mode != 'real_scoring': monkeypatch.setattr(mod, 'build_manifest', lambda **kw: {'config': 'full'})
    if mode == 'interrupted_publication':
        with pytest.raises(RuntimeError): asyncio.run(mod.run_experiment(args, r, r, settings))
        args.resume = next(args.out_root.iterdir())
        assert calls == ['baseline', 'full_k0']
    out = asyncio.run(mod.run_experiment(args, r, r, settings))
    if mode == 'no_gaps':
        assert calls == ['baseline', 'full_k0']
        assert json.loads((out/'experiment.json').read_text())['status'] == 'no_eligible_gaps'
        return
    assert calls == ['baseline', 'full_k0', 'full_k1']
    assert json.loads((out/'experiment.json').read_text())['status'] == 'complete'
    args.resume = out
    if mode == 'boot_replaced':
        boot_check.side_effect = ValueError('database boot replaced')
        with pytest.raises(ValueError): asyncio.run(mod.run_experiment(args, r, r, settings))
        assert calls == ['baseline', 'full_k0', 'full_k1']
        return
    if mode in {'changed_k0', 'changed_k1'}:
        target = out/'k0/pair/full.jsonl' if mode == 'changed_k0' else out/'k1/full.diagnostics_full.jsonl'
        target.write_text('changed')
        with pytest.raises(ValueError): asyncio.run(mod.run_experiment(args, r, r, settings))
        assert calls == ['baseline', 'full_k0', 'full_k1']
        return
    assert asyncio.run(mod.run_experiment(args, r, r, settings)) == out
    assert calls == ['baseline', 'full_k0', 'full_k1']


def test_release_extension_rejects_changed_base_or_dropped_revision():
    from copy import deepcopy
    from eval_harness.knowledge_triplet import check_release_extension
    before = {'manifest': {'index_kind': 'hybrid', 'items': [{'id': 'old'}],
        'source_hashes': {'BASE': 'source'}, 'content_hashes': {'BASE': 'body'}, 'config_hash': 'config'}}
    ready = {'manifest': {'index_kind': 'hybrid', 'items': [{'id': 'old'}, {'id': 'new'}],
        'source_hashes': {'BASE': 'source', 'KG-new': 'refs'},
        'content_hashes': {'BASE': 'body', 'KG-new': 'answer'}, 'config_hash': 'config'}}
    approved = [{'revision_id': 'new', 'kind': 'faq'}]
    check_release_extension(before, ready, approved)
    for field, value in [('source_hashes', {'BASE': 'changed', 'KG-new': 'refs'}),
                         ('items', [{'id': 'new'}]), ('config_hash', 'changed')]:
        changed = deepcopy(ready); changed['manifest'][field] = value
        with pytest.raises(ValueError): check_release_extension(before, changed, approved)
