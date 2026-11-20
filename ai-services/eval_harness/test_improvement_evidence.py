import json

import pytest

from eval_harness.test_m1_acceptance import saved_pair
from eval_harness.test_official_pipeline import BTC


def rounds(tmp_path):
    paths = [tmp_path / 'before', tmp_path / 'after']
    for index, path in enumerate(paths):
        path.mkdir()
        saved_pair(path)
        for config in ('full', 'baseline_no_memory'):
            target = path / (config + '.manifest.json')
            manifest = json.loads(target.read_text())
            manifest['knowledge_release'] = {'release_id': f'release-{index}', 'manifest_hash': f'hash-{index}'}
            manifest['started_at_utc'] = f'2026-11-0{index + 1}T00:00:00Z'
            target.write_text(json.dumps(manifest))
    return paths


def test_identical_results_are_not_evidence_of_improvement(tmp_path):
    from eval_harness.improvement_evidence import compare_runs
    before, after = rounds(tmp_path)
    result = compare_runs(before, after, btc_root=BTC)
    assert result['comparability_valid'] is True
    assert result['improvement_demonstrated'] is False
    assert result['delta_percentage_points']['task_success_rate'] == 0
    assert result['complete'] is False


@pytest.mark.parametrize('field', ['model_id', 'model_params', 'seed_digest', 'source_digest', 'guardrails', 'hardware'])
def test_changed_controls_cannot_be_presented_as_knowledge_improvement(tmp_path, field):
    from eval_harness.improvement_evidence import compare_runs
    before, after = rounds(tmp_path)
    for config in ('full', 'baseline_no_memory'):
        path = after / (config + '.manifest.json')
        manifest = json.loads(path.read_text())
        manifest[field] = {'changed': True} if field in {'model_params', 'guardrails', 'hardware'} else 'changed'
        path.write_text(json.dumps(manifest))
    result = compare_runs(before, after, btc_root=BTC)
    assert result['comparability_valid'] is False
    assert result['improvement_demonstrated'] is False
    assert field in result['incompatible_controls']
    assert result['delta_percentage_points'] == {}


def test_same_release_does_not_prove_a_knowledge_gap_change(tmp_path):
    from eval_harness.improvement_evidence import compare_runs
    before, after = rounds(tmp_path)
    for config in ('full', 'baseline_no_memory'):
        old = json.loads((before / (config + '.manifest.json')).read_text())
        path = after / (config + '.manifest.json')
        new = json.loads(path.read_text())
        new['knowledge_release'] = old['knowledge_release']
        path.write_text(json.dumps(new))
    result = compare_runs(before, after, btc_root=BTC)
    assert result['comparability_valid'] is False
    assert 'knowledge_release_unchanged' in result['incompatible_controls']


def test_reversed_rounds_cannot_be_claimed_as_forward_improvement(tmp_path):
    from eval_harness.improvement_evidence import compare_runs
    before, after = rounds(tmp_path)
    result = compare_runs(after, before, btc_root=BTC)
    assert result['comparability_valid'] is False
    assert 'round_chronology' in result['incompatible_controls']
