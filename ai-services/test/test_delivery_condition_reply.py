"""A delivery estimate is not a deadline guarantee or permission to create."""
from copy import deepcopy

import pytest

from app.agent.harness.session_nodes import safe_consultation_reply
from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
from test_commerce_evidence import state, catalog, quote, stock, bind_history_observations


def delivery_state():
    s = state('Mua Aster giá 900.000đ, bắt buộc giao trong tuần này.')
    s['history'] = [{'customer': 'Tôi xem Aster.', 'agent': 'Aster giá 900.000đ.'}]
    s['session_tool_calls'] = [catalog(), quote(), stock()]
    bind_history_observations(s)
    s['tool_calls'] = [quote(), stock()]
    s['tool_calls'][0]['result']['estimated_delivery'] = '2026-11-10'
    return s


def test_delivery_recovery_discloses_estimate_and_asks_about_waiving_deadline():
    s = delivery_state()
    before = deepcopy(s['tool_calls'])
    reply = safe_consultation_reply(s)
    assert '2026-11-10' in reply and 'dự kiến' in reply
    assert 'không kèm yêu cầu giao đúng hạn' in reply and 'đặt hàng' in reply
    from app.agent.guardrails.checks import check_answer
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    from app.mcp_servers.mcp_shared.consultation import purchase_arguments
    calls = build_commerce_evidence(s, args=purchase_arguments(s))
    assert check_answer(reply, calls, s['safe_text'], focus_sku='SKU-ASTER')[1] is None
    assert s['tool_calls'] == before
    assert purchase_block_reason(s, {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000}) == 'delivery_confirmation_required'


@pytest.mark.parametrize('estimate', [None, 'không rõ', '2026-11-01'])
def test_missing_invalid_or_past_estimate_is_not_presented_as_verified(estimate):
    s = delivery_state()
    s['tool_calls'][0]['result']['estimated_delivery'] = estimate
    reply = safe_consultation_reply(s)
    assert 'không kèm yêu cầu giao đúng hạn' in reply
    assert '2026-11-' not in reply


def test_delivery_estimate_is_bound_to_selected_product():
    s = delivery_state()
    other = quote('SKU-OTHER')
    other['result']['estimated_delivery'] = '2026-11-06'
    s['tool_calls'].append(other)
    reply = safe_consultation_reply(s)
    assert '2026-11-10' in reply and '2026-11-06' not in reply


def test_only_customer_can_remove_delivery_condition():
    s = delivery_state()
    s['history'].append({'customer': s['safe_text'], 'agent': safe_consultation_reply(s)})
    args = {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000}
    for text in ('Ok, giao trong tuần này nhé.', 'Nếu bỏ yêu cầu giao trong tuần thì sao?'):
        s['safe_text'] = text
        assert purchase_block_reason(s, args) is not None
    s['safe_text'] = 'Tôi bỏ yêu cầu giao trong tuần, mua Aster giá 900.000đ, lên đơn COD nhé.'
    assert purchase_block_reason(s, args) is None


@pytest.mark.parametrize('text', [
    'Thôi được, chị lấy cái đó, giao trong tuần này nhé.',
    'Mua Aster giá 900.000đ, giao trong tuần này nhé.',
    'Chị mua Aster giá 900.000đ, giao trong tuần này như hôm trước nhé.',
    'Mua Aster giá 900.000đ, bắt buộc thanh toán COD, giao trong tuần này nhé.',
])
def test_week_delivery_preference_does_not_block_confirmed_purchase(text):
    s = delivery_state()
    s['safe_text'] = text
    assert purchase_block_reason(s, {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000}) is None


def test_soft_delivery_purchase_creates_once_and_reports_estimate_without_guarantee():
    import asyncio
    from types import SimpleNamespace
    from app.agent.implementations.business_agent import BusinessTools
    from app.agent.harness.session_nodes import safe_transaction_reply
    s = delivery_state()
    s['safe_text'] = 'Thôi được, chị lấy cái đó, giao trong tuần này nhé.'
    calls = []
    async def invoke(name, args, *context, **kwargs):
        assert name == 'order.create'
        calls.append(args)
        return {'status': 'created', 'order_id': 'OD-SOFT', 'estimated_delivery': '2026-11-10'}
    async def run():
        tools = BusinessTools(SimpleNamespace(invoke_trusted=invoke), s, 6, lambda: None)
        assert (await tools.complete_purchase_if_ready())['status'] == 'created'
        await tools.complete_purchase_if_ready()
    asyncio.run(run())
    assert len(calls) == 1 and calls[0]['sku'] == 'SKU-ASTER'
    answer = safe_transaction_reply(s)
    assert '2026-11-10' in answer and 'dự kiến' in answer
    assert 'cam kết' not in answer and 'đảm bảo' not in answer
    from app.agent.guardrails.checks import check_answer
    assert check_answer(answer, s['tool_calls'], s['safe_text'])[1] is None


@pytest.mark.parametrize('text', [
    'Chị chỉ mua nếu giao kịp trong tuần này.',
    'Nếu giao được trong tuần này thì chị mới mua.',
    'Mua Aster giá 900.000đ, bắt buộc giao trong tuần này.',
    'Mua Aster giá 900.000đ, phải giao trong tuần này.',
    'Mua Aster giá 900.000đ, cần nhận hàng trong tuần này.',
    'Mua Aster giá 900.000đ, bắt buộc nhận trước thứ sáu.',
    'Mua Aster giá 900.000đ, giao trước thứ sáu nhé.',
    'Mua Aster giá 900.000đ, giao trong tuần này trước 8 giờ nhé.',
])
def test_hard_deadline_remains_a_condition_even_after_later_plain_consent(text):
    from app.mcp_servers.mcp_shared.consultation import requirements
    s = delivery_state()
    s['safe_text'] = text
    assert requirements(s).get('delivery_condition')
    s['history'].append({'customer': text, 'agent': 'Em chưa xác nhận được thời hạn giao.'})
    s['safe_text'] = 'Mua Aster giá 900.000đ, lên đơn COD nhé.'
    assert purchase_block_reason(s, {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000}) == 'delivery_confirmation_required'


def test_later_soft_request_does_not_erase_an_earlier_hard_deadline():
    s = delivery_state()
    s['history'].append({'customer': s['safe_text'], 'agent': 'Em chưa xác nhận được thời hạn giao.'})
    s['safe_text'] = 'Mua Aster giá 900.000đ, giao trong tuần này nhé.'
    assert purchase_block_reason(s, {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000}) == 'delivery_confirmation_required'
