import pytest
from app.agent.guardrails.checks import check_answer


@pytest.mark.parametrize('text', [
    'Dạ, em đã ghi nhận đơn hàng cho chị rồi ạ.',
    'Đơn hàng của chị đang được xử lý, em sẽ thông báo khi có mã đơn.',
    'Dạ, em đã đặt lịch hẹn gọi lại vào 10 giờ sáng mai ạ.',
])
def test_failed_or_missing_write_cannot_support_acknowledgement(text):
    calls = [{'name': 'order.create', 'args': {}, 'result': {'error': 'invalid_args'}}]
    assert check_answer(text, calls)[1] is not None


@pytest.mark.parametrize('text', [
    'Em chưa tạo được đơn hàng cho chị.',
    'Chị muốn em đặt lịch gọi lại không ạ?',
    'Em đã ghi nhận yêu cầu tư vấn của chị.',
    'Em chưa đặt lịch gọi lại cho anh.',
])
def test_failure_question_and_nontransactional_note_are_not_false_success(text):
    assert check_answer(text, [])[1] is None


def test_successful_callback_receipt_supports_acknowledgement():
    calls = [{'name': 'schedule.callback', 'args': {'callback_at': '2026-10-22T10:00'},
              'result': {'callback_id': 'CB0001', 'callback_at': '2026-10-22T10:00'}}]
    assert check_answer('Em đã đặt lịch gọi lại cho anh lúc 10 giờ sáng mai.', calls)[1] is None
