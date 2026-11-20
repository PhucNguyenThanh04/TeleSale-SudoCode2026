import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from test_commerce_evidence import state, catalog, quote, stock, bind_history_observations
from test_consultation_followup import policy_result
from app.agent.implementations.business_agent import BusinessTools
from app.agent.harness.agent_nodes import AgentNodes, _task_answer_complete


def clock():
    return datetime(2026, 11, 5, tzinfo=timezone.utc)


def variant_catalog():
    return catalog(name='Giày Aster', variants=[
        {'variant_sku': 'SKU-ASTER-41-XAM', 'size': 41, 'color': 'xam'},
        {'variant_sku': 'SKU-ASTER-42-XAM', 'size': 42, 'color': 'xam'},
    ])


class Gateway:
    def __init__(self, catalogs=None, available=True):
        self.calls = []
        self.catalogs = catalogs or [catalog()]
        self.available = available
    async def invoke_trusted(self, name, args, *context, **kwargs):
        self.calls.append((name, deepcopy(args)))
        if name == 'catalog.search':
            return {'items': [i for c in self.catalogs for i in c['result']['items']]}
        if name == 'inventory.check':
            return {'sku': args['sku'], 'in_stock': self.available, 'qty': 10 if self.available else 0}
        if name == 'pricing.get_quote':
            return quote(args['sku'])['result']
        if name == 'policy.search':
            return policy_result()
        if name == 'order.create':
            return {'order_id': 'OD-OFFLINE', 'status': 'created'}
        if name == 'order.update':
            return {'order_id': args['order_id'], 'action': args['action'],
                    'new_variant_sku': args['new_variant_sku'], 'status': 'pickup_scheduled',
                    'fee_vnd': 0, 'price_diff_vnd': 40000, 'extra_payment_vnd': 40000}
        if name == 'order.status':
            return {'orders': [{'order_id': args['order_id'], 'sku': 'SKU-ASTER-41-XAM'}]}
        raise AssertionError(name)


def run_node(s, gateway, draft, proposed=()):
    def build(kind, llm, business, prompt):
        class Agent:
            async def ainvoke(self, *a, **kw):
                for name, args in proposed:
                    await business.invoke(name, args)
                return {'messages': [AIMessage(content=draft)]}
        return Agent()
    async def run():
        node = AgentNodes(None, gateway, None, 12, 6, clock=clock)
        s.update(await node.run_agent(s))
        s.update(await node.verify_agent(s))
        return s
    with patch('app.agent.harness.agent_nodes.build_agent', side_effect=build), patch(
            'app.agent.harness.agent_nodes.text_prompt', return_value='offline'):
        return asyncio.run(run())


@pytest.mark.parametrize('available', [True, False])
def test_requested_stock_is_read_without_purchase_or_model_tool_call(available):
    s = state('Aster giá bao nhiêu và hiện còn hàng không em?')
    s['tool_calls'] = [catalog()]
    gateway = Gateway(available=available)
    result = run_node(s, gateway, 'Aster giá 900.000đ.')
    assert [args['sku'] for name, args in gateway.calls if name == 'inventory.check'] == ['SKU-ASTER']
    assert ('còn hàng' if available else 'hết hàng') in result['agent_text']
    assert not any(name.startswith('order.') for name, _ in gateway.calls)






def test_parent_price_is_spoken_before_requesting_variant_and_then_consent_works():
    s = state('Giày Aster giá bao nhiêu, còn giảm không?')
    s['tool_calls'] = [variant_catalog()]
    gateway = Gateway([variant_catalog()])
    first = run_node(s, gateway, 'Mình cho em biết size hoặc màu cần chọn ạ?')
    answer = first['agent_text']
    assert answer and '900.000' in answer
    assert 'size' in answer.lower() or 'màu' in answer.lower()
    s['history'] = [{'customer': s['safe_text'], 'agent': answer}]
    s['session_tool_calls'], s['tool_calls'] = s['tool_calls'], []
    bind_history_observations(s)
    s['safe_text'] = 'Ok lấy size 41 màu xám, lên đơn cho tôi.'
    s['request'] = s['request'].model_copy(update={'text': s['safe_text']})
    gateway = Gateway([variant_catalog()])
    result = run_node(s, gateway, 'Em kiểm tra giúp mình.')
    orders = [args for name, args in gateway.calls if name == 'order.create']
    assert len(orders) == 1 and orders[0]['sku'] == 'SKU-ASTER-41-XAM'
    assert 'OD-OFFLINE' in result['agent_text']




def test_same_product_variant_exchange_uses_size_action_and_recovers_without_retry():
    s = state('Tôi đồng ý bù 40.000 đồng, cập nhật đổi sang size 42 màu xám cho đơn cũ nhé.')
    s['tool_calls'] = [variant_catalog()]
    s['owned_order_ids'] = ['OD-OLD']
    s['crm_orders'] = [{'order_id': 'OD-OLD', 'sku': 'SKU-ASTER-41-XAM'}]
    gateway = Gateway([variant_catalog()])
    result = run_node(s, gateway, 'Đã đổi hàng, chênh lệch 40.000đ.', [
        ('order.update', {'order_id': 'OD-OLD', 'action': 'exchange_product',
                          'new_variant_sku': 'SKU-ASTER-42-XAM'})])
    updates = [a for n, a in gateway.calls if n == 'order.update']
    assert len(updates) == 1 and updates[0]['action'] == 'exchange_size'
    assert 'OD-OLD' in result['agent_text'] and 'ghi nhận' in result['agent_text']
    assert 'tổng đài' not in result['agent_text']








def test_exchange_reads_verified_order_when_crm_lacks_original_variant_and_never_repeats_write():
    s = state('Tôi đồng ý đổi sang size 42 màu xám.')
    s['tool_calls'] = [variant_catalog()]; s['owned_order_ids'] = ['OD-OLD']
    gateway = Gateway([variant_catalog()]); tools = BusinessTools(gateway, s, 8, clock)
    args = {'order_id': 'OD-OLD', 'action': 'exchange_product', 'new_variant_sku': 'SKU-ASTER-42-XAM'}
    async def run():
        one = await tools.invoke('order.update', args)
        two = await tools.invoke('order.update', args)
        assert one == two
    asyncio.run(run())
    assert [n for n, _ in gateway.calls] == ['order.status', 'order.update']
    assert gateway.calls[-1][1]['action'] == 'exchange_size'


def test_unowned_exchange_does_not_trigger_lookup_or_write():
    s = state('Đổi sang size 42 nhé.');s['tool_calls'] = [variant_catalog()]
    gateway = Gateway(); tools = BusinessTools(gateway, s, 8, clock)
    result = asyncio.run(tools.invoke('order.update', {'order_id': 'OD-OTHER',
        'action': 'exchange_product', 'new_variant_sku': 'SKU-ASTER-42-XAM'}))
    assert 'error' in result and not gateway.calls


def test_stock_wording_cannot_bypass_exact_variant_grounding():
    from app.agent.guardrails.checks import check_answer
    calls = [variant_catalog(), stock()]
    assert check_answer('Giày Aster size 42 màu xám có sẵn trong kho.', calls)[1] is not None
    calls[-1] = stock('SKU-ASTER-42-XAM')
    assert check_answer('Giày Aster size 42 màu xám có sẵn trong kho.', calls)[1] is None
    calls[-1]['result'].update(in_stock=False, qty=0)
    assert check_answer('Giày Aster size 42 màu xám có sẵn trong kho.', calls)[1] is not None
    assert check_answer('Giày Aster size 42 màu xám không có sẵn trong kho.', calls)[1] is None


def test_available_in_warehouse_question_needs_stock_answer():
    s = state('Aster có sẵn trong kho không?');s['tool_calls'] = [catalog(), quote(), stock()]
    assert not _task_answer_complete('Aster giá 900.000đ.', s)
