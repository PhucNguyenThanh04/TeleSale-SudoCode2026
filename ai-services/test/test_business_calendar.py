import asyncio
from copy import deepcopy
from datetime import datetime
from unittest.mock import AsyncMock

import pytest


def calendar():
    return {'timezone': 'Asia/Ho_Chi_Minh',
        'weekly': {str(day): [['08:00', '21:00']] for day in range(7)},
        'dates': {'2032-05-11': {'hours': [['07:00', '23:00']]},
                  '2032-05-12': {'hours': []}}, 'delivery_closed_weekdays': [6]}


@pytest.mark.parametrize('requested,expected', [
    ('2032-05-10T07:30', '2032-05-10T08:00:00+07:00'),
    ('2032-05-10T21:00', '2032-05-11T07:00:00+07:00'),
    ('2032-05-11T07:30', '2032-05-11T07:30:00+07:00'),
    ('2032-05-11T22:30', '2032-05-11T22:30:00+07:00'),
    ('2032-05-12T10:00', '2032-05-13T10:00:00+07:00'),
    ('2032-05-12T22:30', '2032-05-13T08:00:00+07:00'),
    ('2032-05-10T02:30+00:00', '2032-05-10T09:30:00+07:00'),
])
def test_opening_windows_and_date_exceptions_are_data_driven(requested, expected):
    from app.mcp_servers.mcp_shared.business_calendar import normalize_callback_at
    result = normalize_callback_at(datetime.fromisoformat(requested), calendar=calendar())
    assert result.isoformat() == expected


def test_split_opening_windows_and_sunday_opening_use_the_next_valid_time():
    from app.mcp_servers.mcp_shared.business_calendar import normalize_callback_at
    rules = calendar()
    rules['dates']['2032-05-10'] = {'hours': [['08:00', '12:00'], ['13:00', '21:00']]}
    rules['weekly']['6'] = [['09:00', '18:00']]
    assert normalize_callback_at(datetime(2032, 5, 10, 12, 30), calendar=rules).hour == 13
    assert normalize_callback_at(datetime(2032, 5, 16, 8, 30), calendar=rules).isoformat() == '2032-05-16T09:00:00+07:00'


def test_canonical_callback_args_are_idempotent_and_record_only_an_actual_shift(monkeypatch):
    from app.mcp_servers.mcp_shared import business_calendar as cal
    from app.mcp_servers.mcp_order.write_authorization import normalized_write
    monkeypatch.setattr(cal, 'load_calendar', calendar)
    raw = {'customer_phone': '0900000027', 'callback_at': '2032-05-12T10:30'}
    normalized = normalized_write('schedule.callback', raw)
    assert normalized['callback_at'] == '2032-05-13T10:30:00+07:00'
    assert normalized['requested_callback_at'] == raw['callback_at'] + ':00'
    assert normalized_write('schedule.callback', normalized) == normalized
    normal = normalized_write('schedule.callback', {**raw, 'callback_at': '2032-05-11T22:30'})
    assert 'requested_callback_at' not in normal


def test_review_and_signed_execution_bind_the_effective_time_and_show_moved_from(monkeypatch):
    from app.mcp_servers.mcp_shared import business_calendar as cal
    from test_write_authorization import OrderRepo, business, current

    async def run():
        monkeypatch.setattr(cal, 'load_calendar', calendar)
        repo, state = OrderRepo(), current('Hẹn gọi theo lịch làm việc mà mình vừa thống nhất.')
        reviewer = AsyncMock(return_value=True)
        tools = business(state, repo, reviewer)
        result = await tools.invoke('schedule.callback', {'callback_at': '2032-05-12T10:30'})
        assert 'error' not in result, result
        reviewed = reviewer.await_args.args[1]
        assert reviewed['callback_at'] == '2032-05-13T10:30:00+07:00'
        assert reviewed['requested_callback_at'] == '2032-05-12T10:30:00'
        assert result['moved_from'] == reviewed['requested_callback_at']
        assert repo.writes[0][1]['moment'] == datetime.fromisoformat(reviewed['callback_at'])
        assert state['tool_calls'][0]['args']['callback_at'] == reviewed['callback_at']
    asyncio.run(run())


def test_forged_original_time_or_changed_calendar_cannot_reuse_a_signed_grant(monkeypatch):
    from app.mcp_servers.mcp_shared import business_calendar as cal
    from app.mcp_servers.mcp_order.write_authorization import sign_write_authorization, verify_write_authorization
    from test_write_authorization import current, wire, SECRET
    monkeypatch.setattr(cal, 'load_calendar', calendar)
    context, args = wire(current(), 'schedule.callback', {
        'customer_phone': '0900000027', 'callback_at': '2032-05-12T10:30'})
    signed = sign_write_authorization('schedule.callback', args, context, SECRET)
    with pytest.raises(PermissionError):
        verify_write_authorization('schedule.callback', {**args, 'callback_at': '2032-05-14T08:00',
            'trusted_authorization': signed}, SECRET)
    changed = deepcopy(calendar())
    changed['dates']['2032-05-12']['hours'] = [['08:00', '21:00']]
    monkeypatch.setattr(cal, 'load_calendar', lambda: changed)
    with pytest.raises(PermissionError):
        verify_write_authorization('schedule.callback', {**args, 'trusted_authorization': signed}, SECRET)


def test_callback_denial_prevents_writing_even_when_calendar_has_a_valid_alternative(monkeypatch):
    from app.mcp_servers.mcp_shared import business_calendar as cal
    from test_write_authorization import OrderRepo, business, current

    async def run():
        monkeypatch.setattr(cal, 'load_calendar', calendar)
        repo, state = OrderRepo(), current('Tôi chỉ nhận được đúng thời điểm đã nói, không đổi.')
        result = await business(state, repo, AsyncMock(return_value=False)).invoke(
            'schedule.callback', {'callback_at': '2032-05-12T10:30'})
        assert result['error'] == 'customer_authorization_required' and not repo.writes
    asyncio.run(run())
