"""Advice respects feasibility and customer constraints before commercial incentives."""
import asyncio
from copy import deepcopy

import pytest

from test_consultation_shortlist import consultation_state, products
from app.agent.harness.agent_nodes import _task_answer_complete
from app.mcp_servers.mcp_shared.consultation_shortlist import build_shortlist, consultation_scope


@pytest.mark.parametrize('in_stock,available,qty', [(False, 0, 1), (True, 1, 2)])
def test_current_stock_feasibility_outranks_cheaper_price(in_stock, available, qty):
    items = products()
    items[0]['list_price_vnd'] = 4500000
    s = consultation_state(f'Ngân sách mỗi chiếc khoảng 5 triệu, cần {qty} chiếc.', items=items)
    s['tool_calls'] = [{'name': 'inventory.check',
        'args': {'sku': 'SKU-ASTER', 'on': '2026-11-05'},
        'result': {'sku': 'SKU-ASTER', 'in_stock': in_stock, 'qty': available}}]
    result = build_shortlist(s, scope=consultation_scope(s))
    assert [item['sku'] for item in result.items] == ['SKU-BERYL']


def test_stale_or_failed_stock_does_not_prove_product_unavailable():
    items = products()
    items[0]['list_price_vnd'] = 4500000
    for on, result in [('2026-11-04', {'sku': 'SKU-ASTER', 'in_stock': False, 'qty': 0}),
                       ('2026-11-05', {'error': 'unavailable'})]:
        s = consultation_state('Ngân sách khoảng 5 triệu.', items=items)
        s['tool_calls'] = [{'name': 'inventory.check', 'args': {'sku': 'SKU-ASTER', 'on': on},
                            'result': result}]
        assert build_shortlist(s, scope=consultation_scope(s)).items[0]['sku'] == 'SKU-ASTER'


def test_explicit_feature_waiver_outranks_inferred_preference():
    s = consultation_state('Nhà có bé nhỏ, không cần khóa trẻ em, ngân sách khoảng 5 triệu.')
    s['tool_calls'] = [{'name': 'pricing.get_quote',
        'args': {'sku': item['sku'], 'qty': 1, 'on': '2026-11-05'},
        'result': {'sku': item['sku'], 'final_price_vnd': item['list_price_vnd']}}
        for item in products()[:2]]
    result = build_shortlist(s, scope=consultation_scope(s), quoted_only=True)
    assert result.items[0]['sku'] == 'SKU-BERYL'
    assert _task_answer_complete('Beryl Air có giá 4.800.000đ, không có khóa trẻ em.', s)


def test_unavailable_customer_selection_is_not_silently_replaced():
    s = consultation_state('Tôi chọn Aster Air để xem giá.')
    s['tool_calls'] = [{'name': 'inventory.check',
        'args': {'sku': 'SKU-ASTER', 'on': '2026-11-05'},
        'result': {'sku': 'SKU-ASTER', 'in_stock': False, 'qty': 0}}]
    assert not build_shortlist(s, scope=consultation_scope(s)).items


@pytest.mark.parametrize('draft,stock_result', [
    ('Beryl Air có giá 4.800.000đ, không có khóa trẻ em.', None),
    ('Aster Air có giá 5.200.000đ.', {'sku': 'SKU-ASTER', 'in_stock': False, 'qty': 0}),
])
def test_agent_replaces_grounded_but_lower_priority_advice(draft, stock_result):
    from types import SimpleNamespace
    from unittest.mock import patch
    from langchain_core.messages import AIMessage
    from app.agent.harness.agent_nodes import AgentNodes
    from test_consultation_shortlist import QuoteGateway, clock
    s = consultation_state()
    if stock_result:
        s['tool_calls'] = [{'name': 'inventory.check',
            'args': {'sku': 'SKU-ASTER', 'on': '2026-11-05'}, 'result': stock_result}]
    gateway = QuoteGateway()

    async def invoke(name, args, *context, **kwargs):
        return await gateway.invoke(name, args)

    tools = SimpleNamespace(invoke_trusted=invoke)

    class Agent:
        async def ainvoke(self, *args, **kwargs):
            return {'messages': [AIMessage(content=draft)]}

    before = deepcopy(s)
    with patch('app.agent.harness.agent_nodes.build_agent', return_value=Agent()), \
         patch('app.agent.harness.agent_nodes.text_prompt', return_value='offline'):
        result = asyncio.run(AgentNodes(None, tools, None, 6, 6, clock=clock).run_agent(s))
    assert result['agent_draft'] != draft
    if stock_result:
        assert 'Aster Air' not in result['agent_draft']
    else:
        assert 'Aster Air' in result['agent_draft'] and 'vượt mức chi' in result['agent_draft']
    assert s['history'] == before['history']
    assert not any(call['name'] == 'order.create' for call in s['tool_calls'])
