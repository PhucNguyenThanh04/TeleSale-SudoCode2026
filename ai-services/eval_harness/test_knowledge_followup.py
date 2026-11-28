import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize('failure', [None, RuntimeError, SystemExit])
def test_normal_cli_detects_after_pair_and_does_not_wait_or_run_c(tmp_path, monkeypatch, failure):
    from eval_harness import run_official as mod
    from eval_harness import knowledge_followup as followup
    (tmp_path/'run.json').write_text(json.dumps({'status': 'validated'}))
    monkeypatch.setattr('sys.argv', ['run_official', '--btc-root', str(tmp_path)])
    pair = AsyncMock(return_value=tmp_path)
    detect = AsyncMock(side_effect=failure(0)) if failure else AsyncMock(return_value=tmp_path/'review')
    monkeypatch.setattr(mod, 'run_pair', pair)
    monkeypatch.setattr(followup, 'detect_after_pair', detect)
    monkeypatch.setattr('eval_harness.report_metrics.render_run', lambda _: 'metrics')
    if failure:
        with pytest.raises(SystemExit) as stopped:
            mod.main()
        assert stopped.value.code == 1
    else:
        mod.main()
    assert json.loads((tmp_path/'run.json').read_text())['status'] == 'validated'
    pair.assert_awaited_once()
    detect.assert_awaited_once_with(tmp_path)


def test_disabled_detection_needs_no_reviewer_database(tmp_path, monkeypatch):
    from eval_harness import knowledge_followup as mod
    monkeypatch.setattr(mod, 'Settings', lambda: SimpleNamespace(knowledge_enabled=False))
    monkeypatch.setattr(mod, 'KnowledgeRepo', lambda _: pytest.fail('no DB connection'))
    assert asyncio.run(mod.detect_after_pair(tmp_path)) is None


def test_full_trace_cli_resumes_proposals_without_k1_evaluation(tmp_path, monkeypatch, capsys):
    from eval_harness import knowledge_followup as mod
    trace = tmp_path/'full.jsonl'
    settings = SimpleNamespace()
    detect = AsyncMock(return_value=(trace.with_suffix('.knowledge-gaps.json'), 'proposals_ready'))
    monkeypatch.setattr('sys.argv', ['knowledge_followup', '--full-trace', str(trace)])
    monkeypatch.setattr(mod, 'Settings', lambda: settings)
    monkeypatch.setattr(mod, 'detect_after_full', detect)
    monkeypatch.setattr(mod, 'KnowledgeRepo', lambda _: pytest.fail('K1 branch must not start'))
    mod.main()
    detect.assert_awaited_once_with(trace, settings)
    assert 'proposals_ready' in capsys.readouterr().out


def test_followup_refuses_missing_or_unpublished_proposals_without_running_models(tmp_path, monkeypatch):
    from eval_harness import knowledge_followup as mod
    from eval_harness import knowledge_triplet as core
    monkeypatch.setattr(core, 'run_experiment', AsyncMock(side_effect=AssertionError('no model run')))
    with pytest.raises(ValueError, match='proposals'):
        asyncio.run(mod.evaluate_published(tmp_path, None, None, None))
    review = mod.review_directory(tmp_path)
    review.mkdir()
    (review/'experiment.json').write_text(json.dumps({'workflow': mod.WORKFLOW,
        'arguments': {'actor': 'reviewer'}, 'proposals': {'proposed': [{}]}, 'k0_release_id': 'k0',
        'system_boot_id': None, 'status': 'proposals_ready'}))
    monkeypatch.setattr(mod, 'collect_review', AsyncMock(return_value=None))
    with pytest.raises(ValueError, match='Publish'):
        asyncio.run(mod.evaluate_published(tmp_path, None, None, None))


@pytest.mark.parametrize('release_pin', [None, '', 'chosen-k0'])
def test_pair_then_review_then_separate_full_file_runs_exactly_three_arms(tmp_path, monkeypatch, capsys, release_pin):
    from eval_harness.test_knowledge_triplet import test_orchestration_runs_pair_then_only_full_k1_and_resumes_without_models
    test_orchestration_runs_pair_then_only_full_k1_and_resumes_without_models(
        tmp_path, monkeypatch, 'complete', 'separate', release_pin=release_pin)
    output = capsys.readouterr().out
    assert 'run_knowledge_eval.py' in output and '--base-run' in output
    assert 'Resume in another terminal' not in output
    import shlex
    if release_pin is None:
        assert 'KNOWLEDGE_RELEASE_ID=' not in output
    else:
        assert 'KNOWLEDGE_RELEASE_ID='+shlex.quote(release_pin) in output


def test_followup_and_k1_scoring_use_the_recorded_external_btc_snapshot(tmp_path, monkeypatch):
    from eval_harness.test_knowledge_triplet import test_orchestration_runs_pair_then_only_full_k1_and_resumes_without_models
    test_orchestration_runs_pair_then_only_full_k1_and_resumes_without_models(
        tmp_path, monkeypatch, 'real_scoring', 'separate', external_snapshot=True)
