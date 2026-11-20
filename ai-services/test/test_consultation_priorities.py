import asyncio
from copy import deepcopy

import pytest

from test_consultation_shortlist import consultation_state, products










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
