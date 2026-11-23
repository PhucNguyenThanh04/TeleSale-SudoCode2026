from copy import deepcopy
from pathlib import Path

from eval_harness.semantic_eval import check_call


BTC = Path(__file__).resolve().parents[3] / 'BTC-Data-Vong1-TEAMS'


def row(*calls):
    return {'scenario_id': 'S', 'call': 'call_2', 'turn': 1, 'agent_text': 'Dạ.',
            'tool_calls': list(calls)}


def test_status_requires_the_expected_order_in_successful_result():
    spec = {'success_if': {'tool_called': 'order.status',
                          'args_match': {'order_id': 'generated_by_order.create'}}}
    prior = [row({'name': 'order.create', 'args': {},
                  'result': {'order_id': 'OD600001', 'status': 'created'}})]
    call = {'name': 'order.status', 'args': {'order_id': 'OD600001'}, 'result': {'orders': []}}
    assert check_call(spec, [row(call)], prior, btc_root=BTC)['status'] == 'fail'
    call['result']['orders'] = [{'order_id': 'OD999999'}]
    assert check_call(spec, [row(call)], prior, btc_root=BTC)['status'] == 'fail'
    call['result']['orders'] = [{'order_id': 'OD600001'}]
    assert check_call(spec, [row(call)], prior, btc_root=BTC)['status'] == 'pass'
    call['result']['error'] = 'unavailable'
    assert check_call(spec, [row(call)], prior, btc_root=BTC)['status'] == 'fail'


def test_orders_cannot_pass_by_splitting_or_adding_items():
    spec = {'success_if': {'tool_called': 'order.create'}, 'supplemental_checks': {
        'order_count': 1, 'order_lines': [
            {'sku': 'A', 'qty': 1, 'price_vnd': 100}, {'sku': 'A', 'qty': 1, 'price_vnd': 50}]}}
    call = {'name': 'order.create', 'args': {'payment': 'COD', 'lines': [
        {'sku': 'A', 'qty': 1, 'price_vnd': 100}, {'sku': 'A', 'qty': 1, 'price_vnd': 50}]},
        'result': {'order_id': 'OD1', 'status': 'created', 'total_vnd': 150}}
    assert check_call(spec, [row(call)], [], btc_root=BTC)['status'] == 'pass'
    split = deepcopy(call)
    call['args']['lines'] = [spec['supplemental_checks']['order_lines'][0]]
    split['args']['lines'] = [spec['supplemental_checks']['order_lines'][1]]
    split['result']['order_id'] = 'OD2'
    assert check_call(spec, [row(call, split)], [], btc_root=BTC)['status'] == 'fail'
    call['args']['lines'].append({'sku': 'B', 'qty': 1, 'price_vnd': 1})
    assert check_call(spec, [row(call)], [], btc_root=BTC)['status'] == 'fail'


def test_handoff_requires_full_schema_and_successful_receipt():
    spec = {'success_if': {'tool_called': 'handoff.transfer'}}
    call = {'name': 'handoff.transfer', 'args': {'brief': {'next_action': 'tư vấn'}},
            'result': {'error': 'brief_invalid'}}
    assert check_call(spec, [row(call)], [], btc_root=BTC)['status'] == 'fail'
    call['result'] = {'ticket_id': 'HT1', 'status': 'queued'}
    assert check_call(spec, [row(call)], [], btc_root=BTC)['status'] == 'fail'
    call['args']['brief'] = {'customer_phone': '[PII ĐÃ ẨN]', 'customer_name': '[TÊN ĐÃ ẨN]',
        'escalation_reason': 'cau_hoi_y_te', 'conversation_summary': 'Khách hỏi ảnh hưởng của thuốc đang uống.',
        'product_advised': 'A', 'price_quoted_vnd': 100, 'open_questions': ['Có an toàn không?'],
        'next_action': 'Chuyển chuyên viên', 'generated_at': '2026-10-20T10:00:00Z'}
    assert check_call(spec, [row(call)], [], btc_root=BTC)['status'] == 'pass'
    call['args']['brief']['escalation_reason'] = 'anything'
    assert check_call(spec, [row(call)], [], btc_root=BTC)['status'] == 'fail'


def test_keyword_success_does_not_replace_semantic_review():
    spec = {'success_if': {'tool_called': None, 'must_say_any': ['18kg']},
            'semantic_requirements': [{'id': 'weight_limit', 'requirement': 'Không cho bé 19kg dùng ghế 18kg.'}]}
    r = row()
    r['agent_text'] = 'Ghế 18kg nhưng bé 19kg vẫn dùng an toàn.'
    assert check_call(spec, [r], [], btc_root=BTC)['status'] == 'needs_review'


def test_evaluation_rejects_mixed_or_duplicate_traces_and_reports_missing_calls():
    import pytest
    from eval_harness.semantic_eval import evaluate
    scenarios = {'S': {'calls': {'call_1': {'success_if': {'tool_called': None}}}}}
    assert evaluate(scenarios, [], btc_root=BTC)['complete'] is False
    r = {**row(), 'call': 'call_1', 'config': 'full', 'run_id': 'r'}
    with pytest.raises(ValueError, match='Duplicate'):
        evaluate(scenarios, [r, r], btc_root=BTC)
    with pytest.raises(ValueError, match='Mixed'):
        evaluate(scenarios, [r, {**r, 'turn': 2, 'config': 'baseline_no_memory'}], btc_root=BTC)


def test_cli_binds_inputs_and_refuses_to_replace_saved_evidence(tmp_path):
    import json
    import os
    import subprocess
    import sys
    import hashlib
    scenarios = tmp_path / 'scenarios'
    scenarios.mkdir()
    (scenarios / 'S.json').write_text(json.dumps({'scenario_id': 'S', 'calls': {
        'call_1': {'customer_turns': ['Chào'], 'success_if': {'tool_called': None},
                   'semantic_requirements': [{'id': 'meaning', 'requirement': 'Trả lời đúng.', 'source_sections': ['FAQ-15']}]}}}))
    trace = tmp_path / 'trace.jsonl'
    trace.write_text(json.dumps({**row(), 'call': 'call_1'}) + '\n')
    output = tmp_path / 'semantic.json'
    command = [sys.executable, '-m', 'eval_harness.semantic_eval', '--scenarios', str(scenarios),
               '--trace', str(trace), '--btc-root', str(BTC), '--out', str(output)]
    env = {**os.environ, 'PYTHONPATH': 'ai-services:.'}
    subprocess.run(command, check=True, capture_output=True, env=env)
    data = json.loads(output.read_text())
    assert data['complete'] is False
    assert data['inputs']['trace_sha256'] == hashlib.sha256(trace.read_bytes()).hexdigest()
    before = output.read_bytes()
    assert subprocess.run(command, capture_output=True, env=env).returncode != 0
    assert output.read_bytes() == before


def test_paired_pipeline_publishes_supplemental_status_separately(tmp_path):
    import json
    from eval_harness.test_official_pipeline import _case
    from eval_harness.official_pipeline import publish_pair
    scenarios, traces, metadata = _case(tmp_path)
    case = json.loads((scenarios / 'case.json').read_text())
    case['calls']['call_1']['semantic_requirements'] = [
        {'id': 'safety', 'requirement': 'Không tư vấn sai.', 'source_sections': ['FAQ-15']}]
    (scenarios / 'case.json').write_text(json.dumps(case))
    result = publish_pair(scenarios, traces['full'], traces['baseline_no_memory'],
                          tmp_path / 'btc_score.json', metadata, btc_root=BTC)
    assert result['status'] == 'validated'
    supplemental = json.loads((tmp_path / 'supplemental_evaluation.json').read_text())
    assert supplemental['full']['complete'] is False
    assert supplemental['baseline_no_memory']['complete'] is False
    assert result['supplemental_evaluation']['path'] == 'supplemental_evaluation.json'
    assert json.loads((tmp_path / 'btc_score.json').read_text()) == result['score']
