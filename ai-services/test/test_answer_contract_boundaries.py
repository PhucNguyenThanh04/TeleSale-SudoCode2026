import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.agent.factory import build_runtime
from app.agent.guardrails.checks import check_answer, check_grounding
from app.agent.guardrails.semantic_grounding import review_answer
from app.configs import Settings
from test_semantic_grounding import ReviewModel, context, turn_state, verdict


@pytest.mark.parametrize('answer', [
    'Dạ đơn hàng của mình đã được lên thành công rồi ạ!',
    'Đơn hàng đã tạo xong, mình yên tâm nhé.',
    'Việc tạo đơn hàng đã hoàn tất.',
    'Em vừa đặt thành công đơn hàng cho mình.',
])
def test_paraphrased_order_completion_requires_a_real_receipt(answer):
    assert check_grounding(answer, []) == 'order_creation_unverified'
    assert check_answer(answer, [])[1] == 'order_creation_unverified'


@pytest.mark.parametrize('answer', [
    'Em chưa tạo được đơn hàng cho mình.',
    'Em chưa thể xác nhận đơn hàng đã được tạo.',
    'Em đã tiếp nhận yêu cầu tạo đơn hàng của mình.',
    'Mình có muốn em tạo đơn hàng không?',
])
def test_pending_negative_or_question_is_not_a_completed_order(answer):
    assert check_grounding(answer, []) is None
    assert check_answer(answer, [])[1] is None


@pytest.mark.parametrize('receipt', [
    {'status': 'created'},
    {'status': 'created', 'order_id': ''},
    {'status': 'created', 'order_id': 'ORDER-81', 'ok': False},
    {'status': 'review_pending', 'order_id': 'ORDER-81'},
])
def test_invalid_or_pending_receipt_cannot_support_completed_order(receipt):
    calls = [{'name': 'order.create', 'args': {}, 'result': receipt}]
    assert check_answer('Đơn hàng đã được tạo thành công.', calls)[1] == 'order_creation_unverified'


def test_valid_receipt_supports_the_same_natural_order_confirmation():
    calls = [{'name': 'order.create', 'args': {},
        'result': {'status': 'created', 'order_id': 'ORDER-81'}}]
    answer = 'Đơn hàng đã được tạo thành công.'
    assert check_grounding(answer, calls) is None
    assert check_answer(answer, calls) == (answer, None)


def test_reading_an_existing_created_order_is_not_a_claim_of_new_creation():
    calls = [{'name': 'order.status', 'args': {'order_id': 'ORDER-81'},
        'result': {'orders': [{'order_id': 'ORDER-81', 'status': 'created'}]}}]
    answer = 'Theo hệ thống, đơn đã tạo.'
    assert check_grounding(answer, calls) is None
    assert check_answer(answer, calls, 'Đơn của tôi đang ở trạng thái nào?') == (answer, None)


@pytest.mark.parametrize('answer', [
    'Em đã tiếp nhận yêu cầu đổi sang size 44 cho đơn hàng của mình.',
    'Em đã tạo phiếu đổi hàng cho mình.',
    'Yêu cầu trả hàng đã được gửi tới bộ phận xử lý.',
])
def test_preview_cannot_support_claim_that_order_change_was_submitted(answer):
    calls = [{'name': 'order.preview_update', 'args': {'order_id': 'ORDER-81'},
              'result': {'order_id': 'ORDER-81', 'status': 'preview', 'estimate': True}}]
    assert check_grounding(answer, calls) == 'order_update_unverified'
    assert check_answer(answer, calls)[1] == 'order_update_unverified'


@pytest.mark.parametrize('answer', [
    'Em chưa tiếp nhận yêu cầu đổi hàng cho mình.',
    'Mình có muốn em tạo phiếu đổi hàng không?',
    'Em đang xem trước phương án đổi hàng, chưa gửi yêu cầu.',
])
def test_order_change_question_and_pending_preview_are_not_claims_of_submission(answer):
    assert check_grounding(answer, []) is None
    assert check_answer(answer, [])[1] is None


def test_real_pending_update_receipt_supports_acknowledgement_without_approval():
    calls = [{'name': 'order.update', 'args': {'order_id': 'ORDER-81'},
              'result': {'order_id': 'ORDER-81', 'status': 'review_pending', 'estimate': True}}]
    answer = 'Em đã tiếp nhận yêu cầu đổi hàng của mình, hồ sơ đang chờ duyệt.'
    assert check_grounding(answer, calls) is None
    assert check_answer(answer, calls)[1] is None


def test_update_receipt_for_a_different_order_cannot_confirm_the_requested_change():
    calls = [{'name': 'order.update', 'args': {'order_id': 'ORDER-81'},
              'result': {'order_id': 'ORDER-92', 'status': 'review_pending'}}]
    answer = 'Em đã tiếp nhận yêu cầu đổi hàng của mình, hồ sơ đang chờ duyệt.'
    assert check_grounding(answer, calls) == 'order_update_unverified'
    assert check_answer(answer, calls)[1] == 'order_update_unverified'


@pytest.mark.parametrize('ordinary,exception', [(9, 18), (12, 27)])
def test_blanket_policy_cannot_take_a_duration_from_a_conditional_exception(ordinary, exception):
    calls = [{'name': 'policy.search', 'result': {'retrieval_status': 'ok', 'evidence': [{
        'chunk_id': 'RULE-INDEPENDENT',
        'content': f'Đổi trả trong {ordinary} ngày. Riêng thiết bị có lỗi kỹ thuật được đổi trong {exception} ngày.',
        'applicability': {'status': 'applicable'}}]}}]
    assert check_answer(f'Mọi sản phẩm đều được đổi trả trong {exception} ngày.', calls)[1] is not None
    answer = f'Riêng thiết bị có lỗi kỹ thuật được đổi trong {exception} ngày.'
    assert check_answer(answer, calls)[1] is None


def test_normal_runtime_reviews_semantic_claims_and_repairs_lost_policy_scope():
    bad = 'Shop luôn đổi cả sản phẩm đã dùng.'
    repaired = 'Shop chỉ tiếp nhận khi sản phẩm chưa sử dụng.'
    model = ReviewModel([verdict(False, 'missing_condition', 'cả sản phẩm đã dùng'), verdict()], repaired)
    settings = Settings.model_construct(langfuse_enabled=False)
    with patch('app.agent.factory.build_llm', return_value=model):
        runtime = build_runtime(settings, gateway=SimpleNamespace())
    state = turn_state(bad)
    state['tool_calls'] = [{'name': 'policy.search', 'args': {'on': '2031-03-12'},
        'result': {'retrieval_status': 'ok', 'evidence': [{
            'chunk_id': 'RULE-81', 'content': 'Chỉ tiếp nhận sản phẩm chưa sử dụng.',
            'applicability': {'status': 'applicable'}}]}}]
    result = asyncio.run(runtime.nodes.verify_agent(state))
    assert result['verified_answer'] == repaired
    assert [item['answer'] for item in model.payloads] == [bad, repaired]


def test_semantic_review_keeps_customer_sources_outside_recent_dialogue():
    data = context()
    data['current_episode'] = {'committed_turns': [{
        'source_turn_id': 'earlier-current', 'customer': 'Tổng ngân sách chỉ 740000 đồng.',
        'agent': 'Em sẽ giữ giới hạn đó.'}]}
    data['previous_episodes'] = [{'customer_statements': [{
        'source_turn_id': 'earlier-session', 'customer': 'Tôi cần hai bộ cho phòng thu.'}]}]
    model = ReviewModel([verdict()])
    asyncio.run(review_answer(model, 'Em giữ đúng yêu cầu đã trao đổi.', data))
    reviewed = model.payloads[0]['context']
    assert reviewed['current_episode']['committed_turns'][0]['customer'] == 'Tổng ngân sách chỉ 740000 đồng.'
    assert reviewed['previous_episodes'][0]['customer_statements'][0]['customer'] == 'Tôi cần hai bộ cho phòng thu.'
