"""Frozen retrieved evidence must answer its topic without borrowing other policies."""
import json
from pathlib import Path
from app.agent.harness.session_nodes import safe_followup_reply
from test_commerce_evidence import state

RUN = Path(__file__).resolve().parents[1] / 'eval_harness/results/knowledge-k0-current/20261111T170857Z-b5ed4233'


def test_general_seal_policy_can_be_explained_without_claiming_order_eligibility():
    rows = [json.loads(line) for line in (RUN / 'full.diagnostics_full.jsonl').read_text().splitlines()]
    row = next(r for r in rows if (r['scenario_id'], r['call'], r['turn']) == ('SC-T18', 'call_1', 2))
    s = state(row['user_text'])
    from datetime import date
    s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 23)})
    s['tool_calls'] = row['tool_calls']
    answer = safe_followup_reply(s)
    assert 'bóc seal' in answer
    assert 'chưa xác minh' in answer.lower()
    assert 'HEPA' not in answer and '2026-06' not in answer
    from app.agent.guardrails.checks import check_answer, check_grounding
    assert check_grounding(answer, s['tool_calls']) is None
    assert check_answer(answer, s['tool_calls'], s['safe_text'])[1] is None
    # An incomplete dependency or expired source cannot authorize the explanation.
    from copy import deepcopy
    for patch in ({'effective_until': '2026-09-30'}, {'missing_required_section_ids': ['MISSING']},
                  {'required_context': ['order_date', 'receipt_condition']}):
        changed = deepcopy(s)
        first = changed['tool_calls'][0]['result']['evidence'][0]
        first['applicability'].update(patch)
        assert 'bình sữa, núm ti đã bóc seal' not in safe_followup_reply(changed)


def test_refund_form_recovery_uses_already_retrieved_source():
    rows = [json.loads(line) for line in (RUN / 'full.diagnostics_full.jsonl').read_text().splitlines()]
    row = next(r for r in rows if (r['scenario_id'], r['call'], r['turn']) == ('SC-T22', 'call_2', 2))
    s = state(row['user_text'])
    from datetime import date
    s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 29)})
    s['tool_calls'] = row['tool_calls']
    s['owned_order_ids'] = ['OD600011']
    # The existing runtime binds the policy result to this owner-verified order.
    s['policy_order_bindings'] = {i: 'OD600011' for i, c in enumerate(s['tool_calls']) if c['name'] == 'policy.search'}
    answer = safe_followup_reply(s)
    assert 'biểu mẫu' in answer
    assert '3' in answer and '5' in answer
    from app.agent.guardrails.checks import check_answer, check_grounding
    assert check_grounding(answer, s['tool_calls']) is None
    assert check_answer(answer, s['tool_calls'], s['safe_text'])[1] is None


def test_sourced_extended_warranty_formula_is_not_a_product_quote():
    from app.agent.guardrails.checks import check_answer
    text = ('Gói bảo hành mở rộng thêm 12 tháng, giá bằng 8% giá sản phẩm, '
            'chỉ áp dụng cho gia dụng trên 3.000.000đ, mua trong vòng 15 ngày kể từ ngày nhận hàng.')
    call = {'name': 'policy.search', 'result': {'evidence': [{'content': text,
        'applicability': {'status': 'applicable'}, 'evidence_type': 'business_rule'}]}}
    assert check_answer(text, [call], 'Có bán gói bảo hành mở rộng không?')[1] is None
    wrong = text.replace('8%', '5%').replace('3.000.000', '2.000.000')
    assert check_answer(wrong, [call], 'Có bán gói bảo hành mở rộng không?')[1] is not None


def test_extended_warranty_recovery_uses_specific_section_not_generic_warranty_history():
    rows = [json.loads(line) for line in (RUN / 'full.diagnostics_full.jsonl').read_text().splitlines()]
    row = next(r for r in rows if (r['scenario_id'], r['call'], r['turn']) == ('SC-T19', 'call_1', 2))
    s = state(row['user_text'])
    from datetime import date
    s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 21)})
    s['tool_calls'] = row['tool_calls']
    answer = safe_followup_reply(s)
    assert '8%' in answer and '3.000.000' in answer
    assert '35.000' in answer and '30.000' in answer
    assert '2.000.000' in answer
    from app.agent.guardrails.checks import check_answer
    assert check_answer(answer, s['tool_calls'], s['safe_text'])[1] is None
    assert check_answer(answer.replace('8%', '5%'), s['tool_calls'], s['safe_text'])[1] is not None
    for unsupported in ('Đơn của anh được miễn phí vận chuyển.',
                        'Giá máy là 3.000.000đ.'):
        assert check_answer(answer + ' ' + unsupported, s['tool_calls'], s['safe_text'])[1] is not None
    incomplete = answer.split('Phí vận chuyển')[0].strip()
    from app.mcp_servers.mcp_shared.consultation_followup import followup_task, followup_answer_complete
    task = followup_task(s)
    assert not followup_answer_complete(s, task, incomplete)
    assert followup_answer_complete(s, task, answer)
