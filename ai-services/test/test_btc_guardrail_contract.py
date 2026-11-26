import asyncio

import pytest

from app.agent.guardrails.checks import check_answer, check_grounding
from app.agent.harness.agent_nodes import AgentNodes
from test_semantic_grounding import ReviewModel, turn_state, verdict


def order_status(status='created', order_id='OD-INDEPENDENT-81'):
    return {'name': 'order.status', 'args': {'order_id': order_id},
            'result': {'orders': [{'order_id': order_id, 'status': status}]}}


@pytest.mark.parametrize('answer', [
    'Theo hệ thống, đơn hàng đã được tạo.',
    'Đơn hàng của anh hiện đã được tạo.',
    'Đơn hàng OD-INDEPENDENT-81 đã được tạo thành công.',
])
def test_existing_order_status_is_not_a_claim_of_creating_another_order(answer):
    calls = [order_status()]
    assert check_grounding(answer, calls) is None
    assert check_answer(answer, calls, 'Đơn hôm trước đang ở trạng thái nào?') == (answer, None)


@pytest.mark.parametrize('answer', [
    'Em chưa thể cung cấp giá nhập và tên nhà cung cấp.',
    'Em không được phép cung cấp giá sàn hoặc nhà cung cấp ạ.',
])
def test_refusing_restricted_information_does_not_count_as_disclosure(answer):
    assert check_answer(answer, [], 'Giá nhập bao nhiêu?') == (answer, None)


def test_refusal_does_not_hide_a_real_disclosure_after_it():
    answer = 'Em chưa thể cung cấp giá nhập; giá nhập là 740.000đ.'
    assert check_answer(answer, [])[1] == 'unsupported_policy_or_internal_claim'


def test_price_reference_is_allowed_with_a_current_matching_quote():
    calls = [{'name': 'pricing.get_quote', 'args': {'sku': 'CONTROL-81'},
              'result': {'sku': 'CONTROL-81', 'final_price_vnd': 740000}}]
    answer = 'Giá vẫn như hôm trước, 740.000đ.'
    assert check_answer(answer, calls) == (answer, None)
    assert check_answer(answer, [])[1] == 'price_without_quote'


def test_historical_customer_budget_is_not_a_product_price():
    calls = [{'name': 'pricing.get_quote', 'args': {'sku': 'CONTROL-81'},
              'result': {'sku': 'CONTROL-81', 'final_price_vnd': 2450000}}]
    answer = 'Ngân sách của chị là 2,5 triệu. Một chiếc có giá 2.450.000đ.'
    assert check_answer(answer, calls, 'Giảm xuống một chiếc thôi.') == (answer, None)
    assert check_answer(answer.replace('2.450.000', '2.400.000'), calls)[1] == 'price_without_quote'


def test_unpriced_form_guidance_does_not_need_a_commercial_policy_lookup():
    answer = 'Anh chỉ nhập CCCD vào biểu mẫu bảo mật của hệ thống, em không lưu các thông tin này ở đây.'
    assert check_answer(answer, [], 'Chính sách hoàn tiền: tôi cung cấp CCCD ở đâu?') == (answer, None)


def test_product_recommendation_has_no_blanket_superlative_veto():
    answer = 'Mẫu này phù hợp nhất với nhu cầu chị vừa nêu.'
    assert check_answer(answer, [])[1] is None


def test_quoted_gift_code_does_not_require_a_name_lookup():
    calls = [{'name': 'pricing.get_quote', 'args': {'sku': 'CONTROL-81'}, 'result': {
        'sku': 'CONTROL-81', 'applied_promos': [{'type': 'gift', 'gift_sku': 'SKU-FILTER-92'}]}}]
    answer = 'Được tặng quà SKU-FILTER-92.'
    assert check_answer(answer, calls) == (answer, None)
    assert check_answer(answer.replace('SKU-FILTER-92', 'SKU-FILTER-93'), calls)[1] is not None


@pytest.mark.parametrize('draft,calls,customer', [
    ('Theo hệ thống, đơn hàng đã được tạo.', [order_status()], 'Đơn hôm trước thế nào?'),
    ('Em chưa thể cung cấp giá nhập và tên nhà cung cấp.', [], 'Giá nhập bao nhiêu?'),
])
def test_valid_btc_answers_reach_review_and_publication_without_repair(draft, calls, customer):
    state = turn_state(draft)
    state.update(tool_calls=calls, safe_text=customer)
    model = ReviewModel([verdict()])
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(state))
    assert result['verified_answer'] == draft
    assert len(model.payloads) == 1
    model.ainvoke.assert_not_awaited()


@pytest.mark.parametrize('answer', [
    'Em vừa tạo đơn mới cho anh.', 'Em đã lên đơn cho mình rồi.',
])
def test_existing_order_read_does_not_authorize_a_new_action_claim(answer):
    assert check_grounding(answer, [order_status()]) == 'order_creation_unverified'


def test_existing_order_status_still_requires_evidence_for_the_named_order():
    answer = 'Theo hệ thống, đơn hàng đã được tạo.'
    assert check_grounding(answer, []) == 'order_creation_unverified'
    wrong_order = 'Đơn hàng OD-INDEPENDENT-92 đã được tạo.'
    assert check_answer(wrong_order, [order_status()])[1] == 'order_id_mismatch'
    assert check_answer(answer, [order_status('shipping')])[1] is not None


def test_btc_budget_constraint_still_goes_through_semantic_review():
    state = turn_state('Ngân sách của chị là 6 triệu.')
    state['safe_text'] = 'Ngân sách của tôi chỉ 2,5 triệu.'
    model = ReviewModel([verdict(False, 'customer_constraint_violated', '6 triệu'), verdict()],
                        'Em sẽ giữ ngân sách chị đã cung cấp.')
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(state))
    assert result['verified_answer'] == 'Em sẽ giữ ngân sách chị đã cung cấp.'
    assert model.payloads[0]['answer'] == state['agent_draft']


def test_unsupported_ranking_is_reviewed_for_its_meaning_instead_of_a_keyword_ban():
    draft = 'Mẫu này tốt nhất trên thị trường.'
    model = ReviewModel([verdict(False, 'unsupported_claim', draft), verdict()],
                        'Em có thể đối chiếu thông số với nhu cầu mình đã nêu.')
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(turn_state(draft)))
    assert result['verified_answer'] == 'Em có thể đối chiếu thông số với nhu cầu mình đã nêu.'
    assert model.payloads[0]['answer'] == draft


@pytest.mark.parametrize('old_status', ['created', 'shipping'])
@pytest.mark.parametrize('created_first', [False, True])
def test_new_order_receipt_is_not_confused_with_another_orders_status(old_status, created_first):
    previous = order_status(old_status, 'OD-OLD-81')
    created = {'name': 'order.create', 'args': {'sku': 'CONTROL-81'},
               'result': {'order_id': 'OD-NEW-92', 'status': 'created'}}
    calls = [created, previous] if created_first else [previous, created]
    answer = 'Đơn hàng OD-NEW-92 đã được tạo thành công.'
    assert check_answer(answer, calls, 'Lên đơn mới cho tôi.') == (answer, None)
    assert check_answer(answer.replace('OD-NEW-92', 'OD-UNKNOWN-93'), calls)[1] is not None
    state = turn_state(answer)
    state.update(tool_calls=calls, safe_text='Lên đơn mới cho tôi.')
    model = ReviewModel([verdict()])
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(state))
    assert result['verified_answer'] == answer
    model.ainvoke.assert_not_awaited()


@pytest.mark.parametrize('answer', [
    'Mẫu này có giá đúng với ngân sách 5 triệu.',
    'Mẫu này bán theo ngân sách 5 triệu.',
    'Giá mẫu này trong ngân sách 5 triệu.',
    'Ngân sách 5 triệu chính là giá mẫu này.',
])
def test_budget_wording_cannot_hide_an_unquoted_product_price(answer):
    assert check_answer(answer, [], 'Ngân sách tôi 5 triệu.')[1] == 'price_without_quote'


@pytest.mark.parametrize('answer', [
    'Ngân sách của chị là 5 triệu.',
    'Dạ, với ngân sách 5 triệu, em sẽ tìm các mẫu phù hợp.',
    'Chị muốn giữ ngân sách 5 triệu ạ?',
    'Chị có ngân sách 5 triệu.',
])
def test_customer_budget_clauses_still_need_no_shop_quote(answer):
    assert check_answer(answer, [], 'Tôi hỏi tiếp mẫu hôm trước.') == (answer, None)


def test_unchanged_price_requires_a_quote_for_the_referenced_product():
    catalog = {'name': 'catalog.search', 'args': {}, 'result': {'items': [
        {'sku': 'CONTROL-81', 'name': 'Bộ điều khiển Boreal', 'variants': []},
        {'sku': 'FILTER-92', 'name': 'Bộ lọc Lumen', 'variants': []}]}}
    control_quote = {'name': 'pricing.get_quote', 'args': {'sku': 'CONTROL-81'},
                     'result': {'sku': 'CONTROL-81', 'final_price_vnd': 740000}}
    filter_quote = {'name': 'pricing.get_quote', 'args': {'sku': 'FILTER-92'},
                    'result': {'sku': 'FILTER-92', 'final_price_vnd': 74000}}
    answer = 'Giá Bộ lọc Lumen vẫn như hôm trước.'
    customer = 'Giá Bộ lọc Lumen còn như cũ không?'
    assert check_answer(answer, [catalog, control_quote], customer)[1] == 'price_without_quote'
    assert check_answer(answer, [catalog, control_quote, filter_quote], customer) == (answer, None)


@pytest.mark.parametrize('lookup', [False, True])
def test_a_correct_gift_code_cannot_support_a_made_up_gift_name(lookup):
    calls = [{'name': 'pricing.get_quote', 'args': {'sku': 'CONTROL-81'}, 'result': {
        'sku': 'CONTROL-81', 'applied_promos': [{'type': 'gift', 'gift_sku': 'SKU-FILTER-92'}]}}]
    if lookup:
        calls.append({'name': 'catalog.get_details', 'args': {'sku': 'SKU-FILTER-92'},
                      'result': {'items': [{'sku': 'SKU-FILTER-92', 'name': 'Màng lọc Lumen'}]}})
    wrong = 'Được tặng một Máy sấy tóc SKU-FILTER-92.'
    assert check_answer(wrong, calls)[1] == 'promotion_detail_unverified'
    assert check_answer('Được tặng quà SKU-FILTER-92.', calls)[1] is None
    named = 'Được tặng một Màng lọc Lumen SKU-FILTER-92.'
    assert (check_answer(named, calls)[1] is None) is lookup


@pytest.mark.parametrize('case', ['budget', 'quote', 'gift'])
def test_review_acceptance_cannot_override_missing_price_or_gift_evidence(case):
    catalog = {'name': 'catalog.search', 'args': {}, 'result': {'items': [
        {'sku': 'CONTROL-81', 'name': 'Bộ điều khiển Boreal', 'variants': []},
        {'sku': 'FILTER-92', 'name': 'Bộ lọc Lumen', 'variants': []}]}}
    quote = {'name': 'pricing.get_quote', 'args': {'sku': 'CONTROL-81', 'on': '2031-03-12'},
             'result': {'sku': 'CONTROL-81', 'final_price_vnd': 740000,
                        'applied_promos': [{'type': 'gift', 'gift_sku': 'SKU-FILTER-92'}]}}
    draft, calls, customer, expected = {
        'budget': ('Mẫu này có giá đúng với ngân sách 5 triệu.', [], 'Ngân sách tôi 5 triệu.', 'price_without_quote'),
        'quote': ('Giá Bộ lọc Lumen vẫn như hôm trước.', [catalog, quote],
                  'Giá Bộ lọc Lumen còn như cũ không?', 'price_without_quote'),
        'gift': ('Được tặng một Máy sấy tóc SKU-FILTER-92.', [quote], 'Mẫu này tặng gì?',
                 'promotion_detail_unverified'),
    }[case]
    state = turn_state(draft)
    state.update(tool_calls=calls, safe_text=customer)
    repaired = 'Em cần kiểm tra lại thông tin này.'
    model = ReviewModel([verdict()], repaired)
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(state))
    assert result['verified_answer'] == repaired
    assert result['verifier_events'][0]['reason'] == expected
    assert [payload['answer'] for payload in model.payloads] == [repaired]
