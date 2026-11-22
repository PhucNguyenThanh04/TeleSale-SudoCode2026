import pytest

from app.agent.guardrails.checks import safe_tool_result
from app.mcp_servers.mcp_shared.memory_observations import memory_observations
from app.mcp_servers.mcp_shared.pii import mask_pii


@pytest.mark.parametrize('text', [
    'SĐT: 090 123 4567',
    'Phone +84 90 123 4567',
    'CCCD: 0123 4567 8901',
    'CCCD 0123-4567-8901',
    'STK: 1234567890123456',
    'STK: 1234 5678 9012 3456',
    'Số thẻ 1234567890123456789',
    'Tài khoản: 123.456.789',
])
def test_sensitive_number_formats_are_masked_at_shared_boundaries(text):
    masked = mask_pii(text)
    assert masked != text and '[SỐ ĐÃ ẨN]' in masked
    assert mask_pii(masked) == masked
    assert safe_tool_result({'note': text})['note'] == masked
    calls = memory_observations([{'name': 'schedule.callback', 'args': {},
        'result': {'callback_id': 'CB1', 'callback_at': text}}])
    assert calls[0]['result']['callback_at'] == masked


@pytest.mark.parametrize('text', [
    'Giá 12.500.000đ, tổng 25.000.000 VND.',
    'Ngân sách 123456789 đồng.',
    'SKU-DEVICE-1234567890123456',
    'Ngày 2026-10-15, lịch hẹn 2026-10-16T10:00:00+07:00.',
    'Giá 4.890.000đ, phòng 25 m², số lượng 2 chiếc.',
])
def test_business_numbers_keep_their_meaning(text):
    assert mask_pii(text) == text
