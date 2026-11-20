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


@pytest.mark.parametrize('mode', ['complete', 'interrupted_publication', 'interrupted_review', 'no_gaps',
    'changed_k0', 'changed_k1', 'changed_review', 'changed_catalog', 'real_scoring', 'boot_replaced'])
@pytest.mark.parametrize('automatic', [False, True])
def test_orchestration_runs_pair_then_only_full_k1_and_resumes_without_models(tmp_path, monkeypatch, mode, automatic, release_pin='', external_snapshot=False):
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
         seed=7, out_root=tmp_path/'runs', actor='simulated-reviewer', resume=None,
        delivery_mode='text', worker_timeout=2, approval_plan=tmp_path/'plan.json')
    args.approval_plan.write_text(json.dumps(plan()))
    separate = automatic == 'separate'
    manual = automatic in {'manual', 'separate'}
    args.manual_review = manual
    if automatic: args.approval_plan = None
    new_revision_id = 'revision'
    settings = SimpleNamespace(app_env='test', agent_guardrails_enabled=True, knowledge_enabled=True,
        knowledge_release_id=release_pin, model_dump=lambda **kwargs: {'model': 'offline'})
    metadata = {'knowledge_release': {'release_id': 'k0', 'manifest_hash': 'hash0'},
        'database_identity': {'database': 'telesale'}, 'seed_digest': 'seed', 'source_digest': 'code'}
    if separate: metadata['model_params'] = {'agent': 'deep', 'seed': 7}
    if mode == 'real_scoring':
        metadata.update(seed_id='seed-7', model_id='offline', model_params={'temperature': 0, 'seed': 7}, tool_mode='mcp',
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
            if manual:
                value['tool_calls'][0]['result'].update(retrieval_status='ok' if mode == 'no_gaps' else 'no_evidence',
                    context={'knowledge_release_id': 'k0', 'on': '2026-11-13'})
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
        run = {'status': 'validated', 'execution_health': 'healthy',
            'conversation_measurement': {'delivery_mode': 'text'},
            'traces': {'full': 'full.jsonl', 'baseline_no_memory': 'baseline.jsonl'}}
        if external_snapshot:
            snapshot = tmp_path / 'reused-btc-release'
            (out/'btc-release').rename(snapshot)
            run['btc_root'] = str(snapshot)
        (out/'run.json').write_text(json.dumps(run))
        return out
    reviews = []
    async def review(*args, **kwargs):
        reviews.append('review')
        if mode == 'interrupted_review' and len(reviews) == 1:
            raise RuntimeError('interrupted during proposal review')
        review_mode = mod.MODE if automatic else 'simulated_pre_reviewed_plan'
        if mode == 'no_gaps': return {'approval_mode': review_mode, 'approved': [], 'skipped': []}
        return {'approval_mode': review_mode, 'approved': [{'case_id': 'condition',
            'revision_id': 'revision', 'kind': 'faq', 'sources': plan()['cases'][0]['sources'],
            'locator': ['LOCAL', 'call_1', 1]}], 'skipped': []}
    activations = []
    async def cmd(repo, actor, action, payload):
        if action == 'prepare_release':
            assert set(payload['revision_ids']) == {'old-revision', new_revision_id}
            if manual:
                from app.knowledge.schemas import digest
                manifest = {'items': [{'id': 'old-revision'}, await repo.get('revisions', new_revision_id)],
                    'index_kind': 'hybrid', 'source_hashes': {'PUBLIC': 'hash'},
                    'content_hashes': {'PUBLIC': 'content'}}
                ready = {'id': 'k1', 'status': 'ready', 'base_release_id': 'k0',
                    'manifest': manifest, 'manifest_hash': digest(manifest)}
                await repo.put('releases', 'k1', ready)
                return ready
            return {'id': 'k1', 'manifest_hash': 'hash1', 'manifest': {
                'items': [{'id': 'old-revision'}, {'id': 'revision'}], 'index_kind': 'hybrid',
                'source_hashes': {'PUBLIC': 'hash', 'KG-revision': 'refs'},
                'content_hashes': {'PUBLIC': 'content', 'KG-revision': 'answer'}}}
        assert action == 'activate_release'
        await repo.put('active', 'current', {'release_id': 'k1'})
        activations.append('activated')
        if mode == 'interrupted_publication' and len(activations) == 1:
            raise RuntimeError('interrupted after activation')
    def single(config, scenarios, seed, run_id, out, **kwargs):
        assert config == 'full' and kwargs['release']['release_id'] == 'k1'
        if external_snapshot:
            assert kwargs['btc_root'] == tmp_path / 'reused-btc-release'
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
    monkeypatch.setattr(mod, 'review_proposals', review)
    if manual:
        monkeypatch.setattr(mod, 'build_feedback', lambda *a, **kw: [])
        if mode == 'early_publish':
            real_propose = mod.propose
            async def proposals_with_concurrent_reviewer(*args, **kwargs):
                nonlocal new_revision_id
                result = await real_propose(*args, **kwargs)
                from app.knowledge.services.lifecycle import command as review_command
                draft = (await r.rows('revisions'))[0]
                approved = await review_command(r, 'simulated-reviewer', 'approve', {
                    'id': draft['id'], 'content_hash': draft['content_hash'], 'approve_test': True,
                    'reason': 'Reviewer published while the proposal process was finishing.'})
                new_revision_id = approved['id']
                await cmd(r, 'human', 'prepare_release', {'revision_ids': ['old-revision', new_revision_id]})
                await cmd(r, 'human', 'activate_release', {'id': 'k1'})
                return result
            monkeypatch.setattr(mod, 'propose', proposals_with_concurrent_reviewer)
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
    if mode in {'interrupted_publication', 'interrupted_review'}:
        with pytest.raises(RuntimeError): asyncio.run(mod.run_experiment(args, r, r, settings))
        args.resume = next(args.out_root.iterdir())
        assert calls == ['baseline', 'full_k0']
    if separate:
        from eval_harness import knowledge_followup as followup
        k0_run = asyncio.run(pair(out_root=args.out_root/'normal-eval', baseline_first=True))
        out = asyncio.run(followup.prepare_review(k0_run, r, r, settings, actor='simulated-reviewer'))
        if external_snapshot:
            checkpoint = json.loads((out/'experiment.json').read_text())
            assert checkpoint['arguments']['btc_root'] == str(tmp_path / 'reused-btc-release')
    else:
        out = asyncio.run(mod.run_experiment(args, r, r, settings))
    if manual and mode == 'early_publish':
        assert calls == ['baseline', 'full_k0']
        assert json.loads((out/'experiment.json').read_text())['status'] == ('proposals_ready' if separate else 'awaiting_review')
        return
    if manual and mode != 'no_gaps':
        assert calls == ['baseline', 'full_k0'] and activations == []
        assert json.loads((out/'experiment.json').read_text())['status'] == ('proposals_ready' if separate else 'awaiting_review')
        args.resume = out
        if mode == 'changed_proposals':
            (out/'proposals.json').write_text('{}')
            with pytest.raises(ValueError, match='Proposal artifact changed'):
                asyncio.run(mod.run_experiment(args, r, r, settings))
            assert calls == ['baseline', 'full_k0']
            return
        if mode == 'locked':
            import fcntl
            with (out/'.resume.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with pytest.raises(ValueError, match='already running'):
                    asyncio.run(mod.run_experiment(args, r, r, settings))
            assert calls == ['baseline', 'full_k0']
            return
        if separate:
            with pytest.raises(ValueError, match='Publish'):
                asyncio.run(followup.evaluate_published(k0_run, r, r, settings))
        else:
            asyncio.run(mod.run_experiment(args, r, r, settings))
        assert calls == ['baseline', 'full_k0']
        assert asyncio.run(r.rows('decisions')) == []
        from app.knowledge.services.lifecycle import command as review_command
        draft = asyncio.run(r.rows('revisions'))[0]
        if mode == 'rejected':
            asyncio.run(review_command(r, 'simulated-reviewer', 'reject', {
                'id': draft['id'], 'content_hash': draft['content_hash'], 'reason': 'Not a knowledge issue.'}))
            asyncio.run(mod.run_experiment(args, r, r, settings))
            assert calls == ['baseline', 'full_k0'] and activations == []
            assert json.loads((out/'experiment.json').read_text())['status'] == 'awaiting_review'
            return
        approved = asyncio.run(review_command(r, 'simulated-reviewer', 'approve', {
            'id': draft['id'], 'content_hash': draft['content_hash'], 'approve_test': True,
            'reason': 'Reviewer checked source and regression test.'}))
        new_revision_id = approved['id']
        asyncio.run(cmd(r, 'human', 'prepare_release', {'revision_ids': ['old-revision', new_revision_id]}))
        asyncio.run(cmd(r, 'human', 'activate_release', {'id': 'k1'}))
        async def forbidden(*args, **kwargs): pytest.fail('manual runner cannot approve/prepare/activate')
        monkeypatch.setattr(mod, 'command', forbidden)
        out = asyncio.run(followup.evaluate_published(k0_run, r, r, settings) if separate else
                          mod.run_experiment(args, r, r, settings))
    if mode == 'no_gaps':
        assert calls == ['baseline', 'full_k0']
        assert json.loads((out/'experiment.json').read_text())['status'] == 'no_eligible_gaps'
        return
    assert calls == ['baseline', 'full_k0', 'full_k1']
    assert json.loads((out/'experiment.json').read_text())['status'] == 'complete'
    if automatic:
        assert not (out/'review-plan.json').exists()
        result = json.loads((out/'comparison.json').read_text())
        assert result['approval_mode'] == (mod.MANUAL_MODE if manual else mod.MODE)
        assert 'gap_answer_accuracy' not in result['gap_evidence']
        assert 'not measured' in (out/'comparison.md').read_text()
        if manual:
            assert result['review']['approved'][0]['approved_by'] == 'simulated-reviewer'
            assert result['review']['approved'][0]['decision']['reason'].startswith('Reviewer checked')
            assert 'manual review' in (out/'comparison.md').read_text()
    args.resume = out
    if mode == 'changed_catalog':
        r.source_rows['PUBLIC']['source_hash'] = 'b'*64
        with pytest.raises(ValueError): asyncio.run(mod.run_experiment(args, r, r, settings))
        assert calls == ['baseline', 'full_k0', 'full_k1']
        return
    if mode == 'changed_review':
        (out/'review.json').write_text('{}')
        with pytest.raises(ValueError, match='Review artifact changed'):
            asyncio.run(mod.run_experiment(args, r, r, settings))
        assert calls == ['baseline', 'full_k0', 'full_k1']
        return
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


@pytest.mark.parametrize('mode', ['complete', 'no_gaps', 'rejected', 'changed_proposals', 'locked', 'early_publish'])
def test_manual_orchestration_pauses_for_frontend_and_resumes_only_c(tmp_path, monkeypatch, mode, capsys):
    monkeypatch.setenv('SYSTEM_BOOT_ID', 'manual-boot')
    test_orchestration_runs_pair_then_only_full_k1_and_resumes_without_models(
        tmp_path, monkeypatch, mode, 'manual')
    output = capsys.readouterr().out
    if mode != 'no_gaps':
        assert 'KNOWLEDGE_ENABLED=true' in output and 'AGENT_GUARDRAILS_ENABLED=true' in output
        assert 'SYSTEM_BOOT_ID=manual-boot' in output and "KNOWLEDGE_RELEASE_ID=''" in output


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


def test_failed_pair_reports_its_cause_without_reading_missing_manifest(tmp_path, monkeypatch):
    from eval_harness import knowledge_triplet as mod
    from unittest.mock import AsyncMock
    r = repo()
    async def setup():
        await r.put('permissions', 'reviewer', {'permissions': ['knowledge_review']})
    asyncio.run(setup())
    r.database_identity = AsyncMock(return_value={'database': 'telesale'})
    args = Namespace(resume=None, approval_plan=None, scenarios=tmp_path/'scenarios', btc_root=tmp_path/'btc',
        expected_database='telesale',  seed=7, out_root=tmp_path/'runs', actor='reviewer',
        delivery_mode='text', worker_timeout=2)
    settings = SimpleNamespace(app_env='test', agent_guardrails_enabled=True, knowledge_enabled=True,
        model_dump=lambda **kw: {'model': 'offline'})
    pair = tmp_path/'failed-pair'; pair.mkdir()
    (pair/'run.json').write_text(json.dumps({'status': 'failed', 'phase': 'configuration',
        'error_code': 'configuration_execution_failed', 'service': None}))
    monkeypatch.delenv('SYSTEM_BOOT_ID', raising=False)
    monkeypatch.setattr(mod, 'run_pair', AsyncMock(return_value=pair))
    monkeypatch.setattr(mod, 'review_proposals', AsyncMock(side_effect=AssertionError('must not review failed K0')))
    with pytest.raises(mod.ExperimentError, match='configuration_execution_failed'):
        asyncio.run(mod.run_experiment(args, r, r, settings))
    checkpoint = json.loads(next(args.out_root.glob('*/experiment.json')).read_text())
    assert checkpoint['phase'] != 'k0_complete'
