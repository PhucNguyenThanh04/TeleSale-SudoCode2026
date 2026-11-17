"""Offline reproductions of the six round-1 failures, without scorer inputs."""
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
from app.agent.harness.session_nodes import safe_consultation_reply, safe_transaction_reply
from app.mcp_servers.mcp_shared.consultation import derive_consultation, purchase_arguments, purchase_block_reason
from app.mcp_servers.mcp_shared.consultation_followup import followup_task


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


@pytest.mark.parametrize('policy', [False, True])
def test_variant_stock_request_survives_policy_route_and_no_exchange_permission(policy):
    text = 'Em kiểm tra tồn kho Giày Aster size 42 màu xám giúp anh, chưa tạo phiếu đổi nhé.'
    if policy:
        text += ' Chính sách đổi size thế nào?'
    s = state(text); s['tool_calls'] = [variant_catalog()]
    gateway = Gateway([variant_catalog()])
    tools = BusinessTools(gateway, s, 8, clock)
    async def run():
        if policy:
            await tools.prepare_followup(followup_task(s))
        else:
            await tools.prepare_consultation()
    asyncio.run(run())
    assert [a['sku'] for n, a in gateway.calls if n == 'inventory.check'] == ['SKU-ASTER-42-XAM']
    assert not any(n in {'order.update', 'order.create'} for n, _ in gateway.calls)


def test_policy_backed_price_sentence_is_a_presented_offer_and_can_be_accepted():
    s = state('Được rồi, em lên đơn 1 chiếc Aster, chuyển khoản nhé.')
    s['history'] = [{'customer': 'Aster giá bao nhiêu, bảo hành bao lâu?',
                     'agent': 'Aster giá 900.000đ, bảo hành 24 tháng.'}]
    s['session_tool_calls'] = [catalog(), quote(), stock(),
        {'name': 'policy.search', 'args': {'on': '2026-11-05'}, 'result': policy_result()}]
    bind_history_observations(s)
    assert derive_consultation(s).snapshot.accepted_offer is not None
    args = purchase_arguments(s)
    assert args and purchase_block_reason(s, args) is None
    gateway = Gateway()
    result = run_node(s, gateway, 'Aster giá 900.000đ.')
    assert sum(n == 'order.create' for n, _ in gateway.calls) == 1
    assert 'OD-OFFLINE' in result['agent_text']


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


def test_basket_total_is_required_before_accepting_a_partial_model_answer():
    from test_basket_harness import basket_state
    s = basket_state('Kiểm tra tồn kho và báo tổng giá giỏ hàng cả 2 sản phẩm Aster và Brio giúp tôi.')
    s['history'] = [{'customer': 'Anh đang xem Aster.', 'agent': 'Aster giá 900.000đ.'}]
    s['session_tool_calls'].append(catalog('SKU-BRIO', 'Brio'))
    s['session_tool_calls'].append(quote(qty=2))
    basket = next(c for c in s['session_tool_calls'] if c['name'] == 'pricing.quote_order')
    basket['args']['lines'] = [{'sku': 'SKU-ASTER', 'qty': 1}, {'sku': 'SKU-BRIO', 'qty': 1}]
    basket['result']['units'][1].update(sku='SKU-BRIO', applied_promos=[])
    assert not _task_answer_complete('Aster hiện còn hàng, giá 900.000đ.', s)
    reply = safe_consultation_reply(s)
    assert reply and '1.350.000' in reply and '2 sản phẩm' in reply


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


@pytest.mark.parametrize('result', [{'error': 'tool_error'},
    {'order_id': 'OD-OTHER', 'status': 'pickup_scheduled', 'action': 'exchange_size'}])
def test_uncertain_or_mismatched_update_receipt_cannot_confirm_success(result):
    s = state('Đổi sang size 42 giúp tôi.')
    s['tool_calls'] = [{'name': 'order.update', 'args': {'order_id': 'OD-OLD',
        'action': 'exchange_size', 'new_variant_sku': 'SKU-ASTER-42-XAM'}, 'result': result}]
    reply = safe_transaction_reply(s)
    assert reply is None or 'đã ghi nhận' not in reply.lower()


@pytest.mark.parametrize('text,read', [
    ('Aster còn hàng không? Chưa mua nhé.', True),
    ('Chưa cần kiểm tra tồn kho Aster.', False),
    ('Aster bảo hành bao lâu?', False),
])
def test_stock_read_is_independent_from_purchase_pause_but_respects_declined_lookup(text, read):
    s = state(text); s['tool_calls'] = [catalog()]
    gateway = Gateway()
    asyncio.run(BusinessTools(gateway, s, 8, clock).prepare_consultation())
    assert any(n == 'inventory.check' for n, _ in gateway.calls) is read
    assert not any(n in {'order.create', 'order.update'} for n, _ in gateway.calls)


@pytest.mark.parametrize('change', ['missing_policy', 'wrong_owner', 'future_policy', 'stale_policy', 'wrong_duration'])
def test_unverified_policy_price_sentence_cannot_become_purchase_permission(change):
    s = state('Em lên đơn 1 chiếc Aster nhé.')
    s['history'] = [{'customer': 'Aster bảo hành bao lâu?', 'agent': 'Aster giá 900.000đ, bảo hành 24 tháng.'}]
    policy = {'name': 'policy.search', 'args': {'on': '2026-11-05'}, 'result': policy_result()}
    s['session_tool_calls'] = [catalog(), quote(), stock(), policy]
    bind_history_observations(s)
    if change == 'missing_policy': s['session_tool_calls'].remove(policy)
    elif change == 'wrong_owner': policy['customer_id'] = 'OTHER'
    elif change == 'future_policy': policy['source_turn_id'] = str(s['request'].client_msg_id)
    elif change == 'stale_policy': policy['args']['on'] = '2026-11-04'
    elif change == 'wrong_duration': s['history'][0]['agent'] = 'Aster giá 900.000đ, bảo hành 99 tháng.'
    assert derive_consultation(s).snapshot.accepted_offer is None
    gateway = Gateway()
    assert asyncio.run(BusinessTools(gateway, s, 8, clock).complete_purchase_if_ready()) is None
    assert not any(n == 'order.create' for n, _ in gateway.calls)


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


def test_returning_stock_request_uses_unambiguous_sourced_scope_without_new_purchase_choice():
    s = state('Em kiểm tra size 42 màu xám có sẵn trong kho không, chỉ hỏi tồn trước nhé.')
    s['scoped_facts'] = {'product': {'SKU-ASTER': {'product_advised': {
        'value': 'SKU-ASTER', 'source': f'langmem:{uuid4()}:{uuid4()}', 'source_kind': 'customer'}}}}
    gateway = Gateway([variant_catalog()])
    asyncio.run(BusinessTools(gateway, s, 8, clock).prepare_consultation())
    assert [a['sku'] for n, a in gateway.calls if n == 'inventory.check'] == ['SKU-ASTER-42-XAM']
    assert derive_consultation(s).snapshot.selected_sku is None


@pytest.mark.parametrize('brand', ['Xiaomi', 'Orion'])
def test_stock_lookup_keeps_literal_brand_instead_of_broad_model_suffix(brand):
    from app.agent.harness.catalog_query import explicit_product_query
    assert explicit_product_query(f'Anh muốn kiểm tra {brand} Smart 4 Pro còn hàng không?') == f'{brand} Smart 4 Pro'


def test_old_basket_does_not_override_current_other_product_stock_question():
    from test_basket_harness import basket_state
    s = basket_state('Brio còn hàng không?')
    s['session_tool_calls'] += [catalog('SKU-BRIO', 'Brio'), stock('SKU-BRIO')]
    answer = safe_consultation_reply(s)
    assert 'Brio' in answer and 'còn hàng' in answer and 'tổng giá' not in answer
