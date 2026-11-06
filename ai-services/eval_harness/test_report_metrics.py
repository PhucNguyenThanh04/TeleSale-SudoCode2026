import json
import pytest


def test_report_uses_saved_score_and_marks_unmeasured_fields(tmp_path):
    from eval_harness.report_metrics import render_run
    (tmp_path / 'run.json').write_text(json.dumps({'status': 'validated', 'score': 'btc_score.json',
        'execution_health': 'healthy', 'extraction_status': 'needs_review',
        'coverage': {'scenarios': 7, 'calls': 13, 'turns': 39}, 'latency_scale_sufficient': False}))
    metric = {'repeat_question_rate': {'value': 9.1, 'redundant': 1, 'total_questions': 11},
              'task_success_rate': {'value': 14.3, 'passed': 1, 'total': 7},
              'latency': {'ttft': {'p50_ms': 4205, 'p95_ms': 12067}}}
    (tmp_path / 'btc_score.json').write_text(json.dumps({'system': metric, 'baseline': metric,
        'comparison': {'meets_tsr_70pct': False}}))
    result = render_run(tmp_path)
    assert '9.1% (1/11)' in result
    assert '14.3% (1/7)' in result
    assert '12067' in result
    assert 'needs_review' in result
    assert 'WER/CER' in result and 'Chưa đo' in result
    assert '39' in result and '100' in result
    assert 'CHƯA ĐẠT' in result


@pytest.mark.parametrize('status', ['failed', 'running', 'invalid'])
def test_no_quality_table_for_incomplete_run(tmp_path, status):
    from eval_harness.report_metrics import render_run
    (tmp_path / 'run.json').write_text(json.dumps({'status': status}))
    with pytest.raises(ValueError, match='validated'):
        render_run(tmp_path)
