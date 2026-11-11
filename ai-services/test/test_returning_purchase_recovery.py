"""Returning customers retain product context without inventing consent."""
import asyncio
from copy import deepcopy
from uuid import uuid4
import pytest

from test_commerce_evidence import state, catalog, quote, stock
from test_consultation_shortlist import clock
from app.agent.implementations.business_agent import BusinessTools
from app.mcp_servers.mcp_shared.consultation import derive_consultation


def returning_state(text):
    s = state(text)
    s['scoped_facts'] = {'product': {'SKU-ASTER': {'product_advised': {
        'value': 'SKU-ASTER', 'source': f'langmem:{uuid4()}:{uuid4()}',
        'source_kind': 'agent', 'status': 'active'}}}}
    s['history'] = [{'customer': 'Tôi gọi lại về Aster.',
        'agent': 'Aster là mẫu mình đã trao đổi.'}]
    return s


class Gateway:
    def __init__(self):
        self.calls = []

    async def invoke(self, name, args):
        self.calls.append((name, deepcopy(args)))
        if name == 'catalog.search':
            return catalog()['result']
        if name == 'pricing.get_quote':
            return quote()['result']
        if name == 'inventory.check':
            return stock()['result']
        raise AssertionError(name)


def test_returning_variant_purchase_creates_once_after_explicit_price_acceptance():
    s = returning_state('Ok lấy size 41 màu đen giá 900.000đ, lên đơn giúp tôi.')

    class VariantGateway(Gateway):
        async def invoke(self, name, args):
            if name == 'catalog.search':
                self.calls.append((name, deepcopy(args)))
                return catalog(variants=[
                    {'variant_sku': 'SKU-ASTER-40-DEN', 'size': 40, 'color': 'den'},
                    {'variant_sku': 'SKU-ASTER-41-DEN', 'size': 41, 'color': 'den'}])['result']
            if name == 'order.create':
                self.calls.append((name, deepcopy(args)))
                return {'status': 'created', 'order_id': 'OD-OFFLINE'}
            result = await super().invoke(name, args)
            result['sku'] = args['sku']
            return result

    gateway = VariantGateway()
    tools = BusinessTools(gateway, s, 5, clock)

    async def run():
        await tools.prepare_consultation()
        result = await tools.complete_purchase_if_ready()
        assert result['status'] == 'created'
        await tools.complete_purchase_if_ready()

    asyncio.run(run())
    orders = [args for name, args in gateway.calls if name == 'order.create']
    assert len(orders) == 1
    assert orders[0]['sku'] == 'SKU-ASTER-41-DEN'
    assert orders[0]['price_vnd'] == 900000


def test_returning_purchase_fetches_missing_metadata_and_prepares_selected_product():
    s = returning_state('Lấy mẫu đó, lên đơn giúp tôi.')
    gateway = Gateway()
    tools = BusinessTools(gateway, s, 5, clock)
    asyncio.run(tools.prepare_consultation())
    assert [name for name, _ in gateway.calls] == [
        'catalog.search', 'pricing.get_quote', 'inventory.check']
    decision = derive_consultation(s)
    assert decision.snapshot.selected_sku == 'SKU-ASTER'
    assert decision.snapshot.accepted_offer is None
    assert asyncio.run(tools.complete_purchase_if_ready()) is None


def test_returning_advice_fetches_metadata_without_creating_customer_selection():
    s = returning_state('Giá mẫu đó hiện tại bao nhiêu?')
    gateway = Gateway()
    tools = BusinessTools(gateway, s, 5, clock)
    asyncio.run(tools.prepare_consultation())
    assert [name for name, _ in gateway.calls] == ['catalog.search', 'pricing.get_quote']
    assert derive_consultation(s).snapshot.selected_sku is None


def test_unattributed_or_inactive_memory_does_not_trigger_metadata_lookup():
    for patch in [{'source': 'untrusted'}, {'status': 'retracted'}, {'value': 'SKU-OTHER'}]:
        s = returning_state('Lấy mẫu đó, lên đơn giúp tôi.')
        s['scoped_facts']['product']['SKU-ASTER']['product_advised'].update(patch)
        gateway = Gateway()
        asyncio.run(BusinessTools(gateway, s, 5, clock).prepare_consultation())
        assert gateway.calls == []


def test_multiple_remembered_products_do_not_choose_a_purchase_by_memory_order():
    s = returning_state('Lấy mẫu đó, lên đơn giúp tôi.')
    s['scoped_facts']['product']['SKU-BRIO'] = {'product_advised': {
        'value': 'SKU-BRIO', 'source': f'langmem:{uuid4()}:{uuid4()}'}}
    gateway = Gateway()
    asyncio.run(BusinessTools(gateway, s, 5, clock).prepare_consultation())
    assert gateway.calls == []
    assert derive_consultation(s).snapshot.selected_sku is None


def test_returning_purchase_continues_after_presenting_and_accepting_current_offer():
    from app.agent.harness.session_nodes import safe_consultation_reply
    s = returning_state('Lấy mẫu đó, lên đơn giúp tôi.')

    class OrderGateway(Gateway):
        async def invoke(self, name, args):
            if name == 'order.create':
                self.calls.append((name, deepcopy(args)))
                return {'status': 'created', 'order_id': 'OD-OFFLINE'}
            return await super().invoke(name, args)

    gateway = OrderGateway()

    async def run():
        tools = BusinessTools(gateway, s, 5, clock)
        await tools.prepare_consultation()
        assert await tools.complete_purchase_if_ready() is None
        answer = safe_consultation_reply(s)
        assert '900.000' in answer and 'đồng ý' in answer
        turn = str(s['request'].client_msg_id)
        s['history'].append({'customer': s['safe_text'], 'agent': answer,
                             'source_turn_id': turn})
        s['session_tool_calls'] = [{**c, 'source_turn_id': turn,
            'customer_id': s['customer_id'], 'session_id': str(s['request'].session_id)}
            for c in s['tool_calls']]
        s.update(safe_text='Đồng ý', tool_calls=[], tool_count=0)
        s['request'] = s['request'].model_copy(update={'text': 'Đồng ý', 'client_msg_id': uuid4()})
        purchase = BusinessTools(gateway, s, 5, clock)
        await purchase.prepare_consultation()
        result = await purchase.complete_purchase_if_ready()
        assert result['status'] == 'created'
        await purchase.complete_purchase_if_ready()

    asyncio.run(run())
    assert [name for name, _ in gateway.calls].count('order.create') == 1


@pytest.mark.parametrize('draft', [
    'Aster giá 169.000đ.',
    'Aster được giảm giá 50.000đ.',
    'Aster hiện không có khuyến mãi giảm giá.',
])
def test_verified_replies_reject_wrong_prices_and_promotion_polarity(draft):
    from app.agent.harness.agent_nodes import AgentNodes
    from app.agent.guardrails.checks import check_answer
    s = state('Aster giá bao nhiêu, có khuyến mãi không?')
    c = catalog()
    c['result']['items'][0]['list_price_vnd'] = 1690000
    q = quote(price=1521000)
    q['result'].update(list_price_vnd=1690000, applied_promos=[{
        'type': 'percent', 'promo_code': 'SALE-10', 'discount_vnd': 169000}])
    s.update(tool_calls=[c, q], agent_draft=draft)
    assert check_answer(draft, s['tool_calls'], s['safe_text'])[1] is not None
    reply = asyncio.run(AgentNodes(None, None, None, 5, 6).verify_agent(s))['agent_text']
    assert reply != draft
    assert check_answer(reply, s['tool_calls'], s['safe_text'])[1] is None
