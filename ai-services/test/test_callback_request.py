from datetime import date
import pytest

from app.agent.harness.callback_request import callback_request


@pytest.mark.parametrize('text,expected', [
    ('Em đặt lịch hẹn gọi lại cho anh vào 10 giờ sáng ngày mai 22/10/2026 nhé.', '2026-10-22T10:00'),
    ('Em đặt lịch gọi lại ngày mai lúc 14 giờ nhé.', '2026-10-22T14:00'),
    ('Nếu đặt lịch gọi lại ngày mai lúc 10 giờ thì sao?', None),
    ('Đừng đặt lịch gọi lại ngày mai lúc 10 giờ.', None),
    ('Em gọi lại lúc 10 giờ nhé.', None),
    ('Em đặt lịch gọi lại ngày mai lúc 25 giờ.', None),
    ('Em đặt lịch gọi lại ngày mai lúc 10 giờ hoặc 14 giờ.', None),
    ('Em đặt lịch gọi lại ngày mai 23/10/2026 lúc 10 giờ.', None),
])
def test_explicit_callback_time_is_customer_bound_and_unambiguous(text, expected):
    assert callback_request(text, date(2026, 10, 21)) == expected


@pytest.mark.parametrize('failed', [False, True])
def test_actual_agent_executes_callback_once_without_model_and_uses_receipt(failed):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch
    from test_commerce_evidence import state
    from app.agent.harness.agent_nodes import AgentNodes
    s = state('Em đặt lịch gọi lại ngày mai lúc 10 giờ nhé.')
    s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 21)})
    calls = []
    async def invoke(name, args, *context, **kwargs):
        calls.append((name, args))
        return {'error': 'unavailable'} if failed else {
            'callback_id': 'CB1', 'callback_at': '2026-10-22T10:00'}
    with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('no model needed')):
        result = asyncio.run(AgentNodes(None, SimpleNamespace(invoke_trusted=invoke), None, 5, 6).run_agent(s))
    assert len(calls) == 1 and calls[0][0] == 'schedule.callback'
    assert ('đã đặt lịch' in result['agent_draft']) is not failed
    if not failed:
        assert '2026-10-22T10:00' in result['agent_draft']
