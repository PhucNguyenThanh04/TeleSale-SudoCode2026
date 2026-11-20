import asyncio

import pytest

from app.agent.implementations.business_agent import BusinessTools
from test_commerce_evidence import state, catalog, quote, stock, bind_history_observations
from test_purchase_continuation import gateway


@pytest.mark.parametrize('proposed,spoken,canonical', [
    ('MOMO', 'momo', 'momo'), ('Bank Transfer', 'chuyển khoản', 'bank'),
    ('BANK_TRANSFER', 'chuyển khoản', 'bank'), ('cod', 'COD', 'COD'),
])
def test_model_payment_alias_is_canonical_before_gateway(proposed, spoken, canonical):
    s = state(f'Mua Aster giá 900.000đ, lên đơn thanh toán {spoken} nhé.')
    s['history'] = [{'customer': 'Tôi hỏi Aster.', 'agent': 'Aster giá 900.000đ.'}]
    s['session_tool_calls'] = [catalog(), quote(), stock()]
    bind_history_observations(s)
    calls = []
    result = asyncio.run(BusinessTools(gateway(calls), s, 6, lambda: None).invoke(
        'order.create', {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000, 'payment': proposed}))
    assert result.get('status') == 'created', result
    assert calls[-1][1]['payment'] == canonical


def test_identical_failed_create_is_not_sent_again_in_same_turn():
    from types import SimpleNamespace
    s = state('Mua Aster giá 900.000đ, lên đơn COD nhé.')
    s['history'] = [{'customer': 'Tôi hỏi Aster.', 'agent': 'Aster giá 900.000đ.'}]
    s['session_tool_calls'] = [catalog(), quote(), stock()]
    bind_history_observations(s)
    calls = []
    async def invoke(name, args, *context, **kwargs):
        calls.append((name, args))
        return {'error': 'tool_error'}
    async def run():
        tools = BusinessTools(SimpleNamespace(invoke_trusted=invoke), s, 6, lambda: None)
        payload = {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000, 'payment': 'COD'}
        first = await tools.invoke('order.create', payload)
        second = await tools.invoke('order.create', payload)
        assert first == second == {'error': 'tool_error'}
    asyncio.run(run())
    assert len(calls) == 1
