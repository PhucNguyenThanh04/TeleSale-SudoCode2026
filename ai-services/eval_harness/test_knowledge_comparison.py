import pytest


def run(release='r0', value=50):
    return {'run_id': release, 'manifests': {'full': {'knowledge_release': {'release_id': release,
        'manifest_hash': release}, 'source_digest': 'code', 'btc_data_digest': 'dataset',
        'seed_digest': 'seed', 'model_id': 'model', 'model_params': {'seed': 7},
        'guardrails': {'enabled': True}, 'tool_mode': 'mcp', 'scorer_sha256': 'scorer'}},
        'score': {'system': {'task_success_rate': {'passed': 1, 'total': 2, 'value': value},
            'repeat_question_rate': {'redundant': 0, 'total_questions': 0, 'value': None}}}}


def test_compare_requires_fixed_dataset_and_reports_missing_denominator():
    from eval_harness.knowledge_comparison import compare_runs
    a, b = run(), run('r1', 75)
    result = compare_runs(a, b)
    assert result['metrics']['tsr']['delta_percentage_points'] == 25
    assert result['metrics']['rqr']['delta_percentage_points'] is None
    b['manifests']['full']['btc_data_digest'] = 'changed'
    with pytest.raises(ValueError, match='btc_data_digest'):
        compare_runs(a, b)


def test_compare_rejects_model_and_code_mutations():
    from eval_harness.knowledge_comparison import compare_runs
    for key in ('model_params', 'source_digest'):
        b = run('r1')
        b['manifests']['full'][key] = 'changed'
        with pytest.raises(ValueError, match=key):
            compare_runs(run(), b)


def test_pair_audit_rejects_release_mismatch():
    from eval.trace_audit import audit_pair
    a = {'config': 'full', 'run_id': 'run', 'knowledge_release': {'release_id': 'one'}}
    b = {'config': 'baseline_no_memory', 'run_id': 'run', 'knowledge_release': {'release_id': 'two'}}
    assert any('knowledge_release' in err for err in audit_pair(a, b))


def test_official_pipeline_imports_without_prior_path_mutation():
    import subprocess
    import sys
    from pathlib import Path
    service = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-c', 'import eval_harness.official_pipeline'],
                            cwd=service, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
