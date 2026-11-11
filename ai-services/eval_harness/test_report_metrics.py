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


def test_voice_report_labels_response_and_ttft_proxy(tmp_path):
    from eval_harness.report_metrics import render_run
    (tmp_path / 'run.json').write_text(json.dumps({'status': 'validated', 'score': 'btc_score.json',
        'conversation_measurement': {'delivery_mode': 'voice', 'ttft_is_proxy': True}}))
    metric = {'latency': {'ttft': {'p50_ms': 125}, 'total': {'p50_ms': 125}}}
    (tmp_path / 'btc_score.json').write_text(json.dumps({'system': metric, 'baseline': metric}))
    output = render_run(tmp_path)
    assert 'Response p50 (ms)' in output
    assert 'TTFT proxy' in output
    assert 'ASR/TTS' in output


def test_text_report_does_not_relabel_completion_proxy_as_measured_ttft(tmp_path):
    from eval_harness.report_metrics import render_run
    (tmp_path / 'run.json').write_text(json.dumps({'status': 'validated', 'score': 'btc_score.json',
        'conversation_measurement': {'delivery_mode': 'text', 'ttft_is_proxy': True}}))
    metric = {'latency': {'ttft': {'p50_ms': 250}, 'total': {'p50_ms': 250}}}
    (tmp_path / 'btc_score.json').write_text(json.dumps({'system': metric, 'baseline': metric}))
    output = render_run(tmp_path)
    assert 'TTFT proxy' in output
    assert 'chưa đo token đầu tiên' in output
    assert 'Total p50 (ms)' in output


def test_nonstreaming_text_report_explains_btc_rule_7(tmp_path):
    from eval_harness.report_metrics import render_run
    from eval_harness.benchmark_runner import conversation_measurement
    (tmp_path / 'run.json').write_text(json.dumps({'status': 'validated', 'score': 'btc_score.json',
        'conversation_measurement': conversation_measurement('text')}))
    metric = {'latency': {'ttft': {'p50_ms': 250}, 'total': {'p50_ms': 250}}}
    (tmp_path / 'btc_score.json').write_text(json.dumps({'system': metric, 'baseline': metric}))
    output = render_run(tmp_path)
    assert '| TTFT p50 (ms)' in output
    assert 'quy tắc 7' in output
    assert 'TTFT proxy' not in output


@pytest.mark.parametrize('status', ['failed', 'running', 'invalid'])
def test_no_quality_table_for_incomplete_run(tmp_path, status):
    from eval_harness.report_metrics import render_run
    (tmp_path / 'run.json').write_text(json.dumps({'status': status}))
    with pytest.raises(ValueError, match='validated'):
        render_run(tmp_path)


def test_report_explains_quote_supported_mismatches_without_rewriting_btc_score(tmp_path):
    from eval_harness.report_metrics import render_run
    from eval_harness.test_claim_evidence import row
    (tmp_path / 'run.json').write_text(json.dumps({'status': 'validated', 'score': 'btc_score.json',
        'traces': {'full': 'full.jsonl'}}))
    scenarios = tmp_path / 'scenarios'
    scenarios.mkdir()
    (scenarios / 'case.json').write_text(json.dumps({'scenario_id': 'CASE', 'calls': {
        'call_1': {}, 'call_2': {'days_later': 3, 'success_if': {'args_match': {'sku': 'SKU-Y'}}}}}))
    rows = [{**row(field, value), 'scenario_id': 'CASE', 'call': 'call_2', 'turn': n}
            for n, (field, value) in enumerate([('price_vnd', 2990000), ('promo_active', True)], 1)]
    (tmp_path / 'full.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    examples = [{'scenario': 'CASE', 'call': 'call_2', 'turn': r['turn'],
                 'field': r['claims'][0]['field'], 'claimed': r['claims'][0]['value'],
                 'truth': 5200000 if r['turn'] == 1 else False} for r in rows]
    score = {'system': {'hallucination_rate': {'value': 12.5, 'wrong': 2, 'total_claims': 16,
                                            'examples': examples}}, 'baseline': {}}
    score_path = tmp_path / 'btc_score.json'
    score_path.write_text(json.dumps(score))
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    output = render_run(tmp_path)
    assert '12.5% (2/16)' in output
    assert 'khớp quote SKU-X' in output and 'SKU kỳ vọng SKU-Y' in output
    assert 'promo_active' in output and 'lệch ground truth' in output
    assert 'không tự chứng minh agent bịa' in output
    assert all(p.read_bytes() == content for p, content in before.items())
