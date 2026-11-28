import asyncio
import socket

import pytest

from app.agent.guardrails.checks import check_answer
from app.agent.guardrails.semantic_grounding import review_answer
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.harness.observability import capture_diagnostic_events
from test_semantic_grounding import ReviewModel, context, turn_state, verdict


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('guardrail precision tests must stay offline')
    monkeypatch.setattr(socket.socket, 'connect', denied)


@pytest.mark.parametrize('answer', [
    'Dạ chị, em ghi nhận nhà có bé nhỏ và ngân sách tầm 5 triệu. Chị dùng phòng bao nhiêu mét vuông ạ?',
    'Em ghi nhận mức ngân sách 5 triệu của chị.',
    'Với mức chị muốn chi là 5 triệu, em sẽ tìm mẫu phù hợp.',
    'Em chưa biết mẫu này còn hàng không ạ.',
    'Em chưa xác minh được tình trạng còn hàng của mẫu này.',
    'Chị cần mẫu có sẵn trong kho đúng không ạ?',
    'Chị muốn máy có HEPA không ạ?',
    'Em chưa có thông tin về HEPA của mẫu này.',
    'Chị đang tìm mẫu có HEPA để dùng cho bé.',
    'Em chưa xác minh được ưu đãi miễn phí vận chuyển.',
    'Em chưa thể xác nhận mẫu này được tặng màng lọc.',
    'Em cần kiểm tra lại chính sách bảo hành 24 tháng chị vừa hỏi.',
    'Em ghi nhận chị cần giao ngày 15/12/2026.',
    'Chị muốn giao vào ngày 15/12/2026 phải không ạ?',
    'Em chưa thể xác nhận đã đặt lịch gọi lại.',
    'Em chưa thể xác nhận đã chuyển bộ phận phụ trách.',
    'Em chưa thể xác nhận thông tin giá nhập.',
    'Mẫu này có HEPA không ạ?',
    'Chị cho em biết mình có cần HEPA không ạ?',
    'Em chưa có thông tin về ưu đãi và miễn phí vận chuyển.',
    'Em chưa xác minh được giá 5 triệu, tồn kho và miễn phí vận chuyển.',
    'Em ghi nhận chị thấy bên kia bán 5 triệu.',
    'Em cần kiểm tra mẫu này có HEPA và PM2.5 không.',
    'Chị cho em xin mã đơn để kiểm tra bảo hành ạ.',
    'Ngân sách chị khoảng 5 triệu, em ghi nhận rồi ạ.',
    'Với tầm giá chị mong muốn là 5 triệu, em sẽ tìm mẫu phù hợp.',
    'Em chưa xác minh được ưu đãi; em cũng chưa biết có miễn phí vận chuyển hay không.',
    'Em chưa có thông tin về HEPA, hiện tại em vẫn chưa xác minh được tính năng đó.',
    'Em chưa xác minh được HEPA nên cần kiểm tra thêm ạ.',
])
def test_mentions_and_customer_needs_are_not_commercial_assertions(answer):
    customer = 'NHÀ CHỊ CÓ BÉ NHỎ TẦM 5 triệu THÔI EM'
    assert check_answer(answer, [], customer) == (answer, None)


@pytest.mark.parametrize('answer', [
    'Em chưa biết còn hàng không, nhưng mẫu này còn hàng.',
    'Em chưa có thông tin về HEPA. Mẫu này có HEPA H13.',
    'Chị muốn máy có HEPA, mẫu này có HEPA H13.',
    'Em chưa xác minh ưu đãi, hiện được miễn phí vận chuyển.',
    'Em cần kiểm tra bảo hành, sản phẩm bảo hành 24 tháng.',
    'Em ghi nhận chị cần giao ngày 15/12/2026. Bên em chắc chắn giao ngày 15/12/2026.',
    'Em chưa thể xác nhận đã đặt lịch; em đã đặt lịch gọi lại rồi.',
    'Em chưa thể xác nhận đã chuyển bộ phận phụ trách; em đã chuyển bộ phận phụ trách rồi.',
    'Em ghi nhận ngân sách 5 triệu, mẫu này giá 5 triệu.',
    'Em ghi nhận ngân sách 5 triệu chính là giá mẫu này.',
    'Em chưa rõ về HEPA và mẫu này có HEPA H13.',
    'Chị muốn hỏi HEPA không ạ? Mẫu này có HEPA H13.',
    'Mẫu này còn hàng, chị muốn mua không ạ?',
    'Em chưa rõ ưu đãi nên hiện được miễn phí vận chuyển.',
    'Chị cần máy có HEPA nên mẫu này có HEPA H13.',
    'Mẫu này đúng với tầm giá chị mong muốn là 5 triệu.',
])
def test_non_assertions_do_not_hide_separate_real_violations(answer):
    assert check_answer(answer, [], 'Ngân sách tôi 5 triệu.')[1] is not None


@pytest.mark.parametrize('eta,reason', [('27/10', 'delivery_unverified'), ('28/10', None)])
def test_receipt_date_wording_is_checked_against_latest_quote(eta, reason):
    quotes = [
        {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-EXAMPLE', 'address': area},
         'result': {'estimated_delivery': expected}}
        for area, expected in [(None, '2026-10-30'), ('Hà Nội', '2026-10-28')]
    ]
    answer = f'Ngày nhận hàng dự kiến sớm nhất là Thứ Ba, ngày {eta}.'
    assert check_answer(answer, quotes, 'Khi nào nhận hàng?')[1] == reason


@pytest.mark.parametrize('area,eta,reason', [
    (' ở Hà Nội', '28/10', None),
    (' ở Hà Nội', '30/10', 'delivery_unverified'),
    ('', '30/10', 'delivery_unverified'),
])
def test_delivery_quotes_for_two_addresses_keep_their_scope(area, eta, reason):
    quotes = [
        {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-EXAMPLE', 'address': city},
         'result': {'estimated_delivery': date}}
        for city, date in [('Hà Nội', '2026-10-28'), ('Đà Nẵng', '2026-10-30')]
    ]
    answer = f'Dự kiến giao hàng{area} vào ngày {eta}.'
    assert check_answer(answer, quotes, 'Đơn này khi nào tới?')[1] == reason


def test_nonassertive_reply_skips_semantic_provider():
    answer = 'Chị muốn máy có HEPA không ạ?'
    model = ReviewModel([verdict(True, 'supported', '')])
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(turn_state(answer)))
    assert result['verified_answer'] == answer
    assert model.payloads == []


@pytest.mark.parametrize('prefix', ['', 'Nếu chị đặt máy hôm nay (24/03), '])
def test_wrong_eta_is_recovered_from_current_quote_without_model_repair(prefix):
    answer = prefix + 'ngày nhận hàng dự kiến sớm nhất là Thứ Ba, ngày 27/10.'
    state = turn_state(answer)
    on = state['request'].on
    state['safe_text'] = 'Tính lại ngày em nhận được hàng giúp chị.'
    state['tool_calls'].append({'name': 'pricing.get_quote', 'args': {'sku': 'DEVICE-81', 'on': on.isoformat()},
                                'result': {'estimated_delivery': '2031-03-28'}})
    model = ReviewModel([verdict(True, 'supported', '')])
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(state))
    assert '28/03/2031' in result['verified_answer']
    assert '27/10' not in result['verified_answer']
    assert result['verified_answer'].startswith(prefix)
    model.ainvoke.assert_not_awaited()


def test_sensitive_identifiers_cannot_be_claimed_as_saved():
    answer = ('Em không được phép đọc lại các dãy số định danh hoặc số tài khoản đã bị che. '
              'Các thông tin này đã được ghi nhận trong hồ sơ của chị ạ.')
    assert check_answer(answer, [], 'Em nhắc lại hai dãy số rồi lưu giúp chị.')[1] is not None
    refusal = 'Em không đọc lại hoặc lưu số tài khoản vào ghi chú hội thoại.'
    assert check_answer(refusal, [], 'Lưu vào ghi chú giúp chị.')[1] is None


@pytest.mark.parametrize('reason', ['unanswered_request', 'unnecessary_clarification'])
def test_subjective_quality_verdict_is_not_a_violation(reason):
    answer = 'Chị muốn tìm hiểu tính năng nào ạ?'
    model = ReviewModel([verdict(False, reason, answer)])
    assert asyncio.run(review_answer(model, answer, context())) is None


def test_reviewer_cannot_reject_a_clause_absent_from_the_answer():
    answer = 'Thiết bị hỗ trợ Zigbee.'
    model = ReviewModel([verdict(False, 'contradiction', 'Thiết bị hỗ trợ Wi-Fi.')])
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(turn_state(answer)))
    assert result['verified_answer'] == answer
    assert not result.get('verifier_events')
    model.ainvoke.assert_not_awaited()


@pytest.mark.parametrize('answer,claim', [
    ('Chị muốn máy có HEPA không ạ?', 'HEPA'),
    ('Em chưa xác minh được miễn phí vận chuyển.', 'miễn phí vận chuyển'),
    ('Em ghi nhận ngân sách của chị tầm 5 triệu.', '5 triệu'),
])
def test_reviewer_cannot_turn_a_non_commercial_mention_into_a_violation(answer, claim):
    model = ReviewModel([verdict(False, 'unsupported_claim', claim)])
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(turn_state(answer)))
    assert result['verified_answer'] == answer
    assert not result.get('verifier_events')
    model.ainvoke.assert_not_awaited()


@pytest.mark.parametrize('decision', [RuntimeError('unavailable'), TimeoutError('deadline'), {}])
def test_failed_review_does_not_block_an_otherwise_valid_answer(decision):
    answer = 'Thiết bị hỗ trợ Zigbee.'
    model = ReviewModel([decision])
    with capture_diagnostic_events() as events:
        result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(turn_state(answer)))
    assert result['reply_error'] is None
    assert result['verified_answer'] == answer
    assert not result.get('verifier_events')
    assert any(event.get('reason') == 'grounding_review_unavailable' for event in events)
    model.ainvoke.assert_not_awaited()


def test_budget_acknowledgement_reaches_the_customer_without_repair_or_fallback():
    answer = 'Dạ chị, em ghi nhận nhà có bé nhỏ và ngân sách tầm 5 triệu. Chị dùng phòng bao nhiêu mét vuông ạ?'
    state = turn_state(answer)
    state.update(safe_text='NHÀ CHỊ CÓ BÉ NHỎ TẦM 5 triệu THÔI EM', tool_calls=[])
    model = ReviewModel([verdict()])
    nodes = AgentNodes(model, None, None, 8, 6, safe_fallback_on_rejection=True)
    result = asyncio.run(nodes.verify_agent(state))
    assert result['verified_answer'] == answer
    assert result['reply_error'] is None
    assert not result.get('verifier_events')
    model.ainvoke.assert_not_awaited()


def test_reviewer_acceptance_does_not_override_a_real_commercial_violation():
    state = turn_state('Mẫu này giá 5 triệu, hiện còn hàng.')
    state['tool_calls'] = []
    model = ReviewModel([verdict()], 'Mẫu này giá 5 triệu, hiện còn hàng.')
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(state))
    assert result['reply_error'] == 'agent_reply_unavailable'
    assert result['verifier_events'][0]['reason'] == 'price_without_quote'
