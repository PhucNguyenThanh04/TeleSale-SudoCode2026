import asyncio
import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from uuid import uuid4
import pytest

from app.agent.implementations.business_agent import BusinessTools
from app.mcp_servers.mcp_shared.commerce_rules import _catalog, _inventory, quote
from app.agent.memory.store import safe_observations
from test_commerce_evidence import state

BTC = Path(__file__).resolve().parents[3] / 'BTC-Data-Vong1-TEAMS'
PRODUCTS = json.loads((BTC / 'catalog/products.json').read_text())['products']
PROMOS = json.loads((BTC / 'catalog/promotions.json').read_text())['promotions']
EVENTS = json.loads((BTC / 'catalog/inventory_timeline.json').read_text())['events']


class OfflineCommerce:
    def __init__(self):
        self.calls = []

    async def invoke_trusted(self, name, args, *_args, **_kwargs):
        self.calls.append((name, deepcopy(args)))
        if name == 'catalog.search':
            return _catalog(PRODUCTS, args)
        if name == 'pricing.get_quote':
            return quote(PRODUCTS, PROMOS, args, set(), set())
        if name == 'inventory.check':
            return _inventory(PRODUCTS, EVENTS, args['sku'], args['on'])
        if name == 'pricing.quote_order':
            from app.mcp_servers.mcp_shared.commerce_rules import quote_order
            return quote_order(PRODUCTS, PROMOS, args)
        if name == 'order.create':
            return {'status': 'created', 'order_id': 'OD-OFFLINE'}
        raise AssertionError(name)




















def commit(s, reply):
    tid = str(s['request'].client_msg_id)
    s['history'].append({'customer': s['safe_text'], 'agent': reply,
                         'source_turn_id': tid, 'on': str(s['request'].on)})
    s['session_tool_calls'].extend({**call, 'source_turn_id': tid,
        'customer_id': s['customer_id'], 'session_id': str(s['request'].session_id)}
        for call in safe_observations(s['tool_calls']))


def next_turn(s, text):
    s.update(safe_text=text, tool_calls=[], tool_count=0)
    s.pop('consultation_scope', None)
    s['request'] = s['request'].model_copy(update={'text': text, 'client_msg_id': uuid4()})








def test_unrelated_price_read_from_k0_is_blocked_after_named_catalog_lookup():
    async def run():
        s = state('Chị hỏi máy lọc nước Sunhouse UF.')
        gateway = OfflineCommerce()
        tools = BusinessTools(gateway, s, 5, lambda: None)
        await tools.invoke('catalog.search', {'query': 'máy lọc nước Sunhouse UF'})
        result = await tools.invoke('pricing.get_quote', {'sku': 'SKU-MB-MON'})
        assert result['error'] == 'unverified_sku'
        assert [name for name, _ in gateway.calls] == ['catalog.search']
    asyncio.run(run())


def test_spectra_short_name_cannot_authorize_a_previously_quoted_combo_order():
    async def run():
        s = state('ok, vậy chị lấy Spectra, chị trả Momo nhé')
        gateway = OfflineCommerce()
        tools = BusinessTools(gateway, s, 5, lambda: None)
        await tools.invoke('catalog.search', {'query': 'Spectra S1'})
        await tools.invoke('pricing.get_quote', {'sku': 'SKU-BDL-MOM'})
        await tools.invoke('inventory.check', {'sku': 'SKU-BDL-MOM'})
        result = await tools.invoke('order.create', {'sku': 'SKU-BDL-MOM', 'qty': 1,
            'price_vnd': 4790000, 'payment': 'momo'})
        assert result.get('error')
        assert not any(name == 'order.create' for name, _ in gateway.calls)
    asyncio.run(run())


def test_actual_agent_prepares_and_answers_owned_order_when_model_asks_for_id_again():
    from unittest.mock import patch
    from langchain_core.messages import AIMessage
    from app.agent.harness.agent_nodes import AgentNodes
    async def run():
        s = state('Anh hỏi tình trạng đơn đã mua hôm trước, em tra giúp nhé.')
        s['owned_order_ids'] = ['OD-OFFLINE']
        class Gateway(OfflineCommerce):
            async def invoke_trusted(self, name, args, *_args, **_kwargs):
                if name == 'order.status':
                    self.calls.append((name, dict(args)))
                    return {'orders': [{'order_id': 'OD-OFFLINE', 'status': 'shipping'}]}
                return await super().invoke_trusted(name, args, *_args, **_kwargs)
        class Agent:
            async def astream(self, *_args, **_kwargs):
                yield 'values', {'messages': [AIMessage(content='Anh cho em xin mã đơn hàng nhé.')]}
        gateway = Gateway()
        with patch('app.agent.harness.agent_nodes.build_agent', return_value=Agent()), \
             patch('app.agent.harness.agent_nodes.text_prompt', return_value='offline'):
            node = AgentNodes(None, gateway, None, 5, 6)
            s.update(await node.run_agent(s))
            result = await node.verify_agent(s)
        assert 'OD-OFFLINE' in result['agent_text'] and 'đơn đang giao' in result['agent_text']
        assert [name for name, _ in gateway.calls] == ['order.status']
    asyncio.run(run())
