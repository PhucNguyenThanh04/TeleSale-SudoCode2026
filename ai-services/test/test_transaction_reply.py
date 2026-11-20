import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.harness.agent_nodes import AgentNodes


def current(calls, draft):
    from test_text_harness_contract import turn_state
    state = turn_state('Lên đơn giúp tôi')
    state['request'] = state['request'].model_copy(update={'on':date(2026, 11, 2)})
    state.update(tool_calls=calls, agent_draft=draft)
    return state


def order(order_id="ODLOCAL7", sku="SKU-LOCAL-A", **result):
    return {"name": "order.create", "args": {"sku": sku, "qty": 2, "price_vnd": 430000},
            "result": {"status": "created", "order_id": order_id, "total_vnd": 860000, **result}}


@pytest.mark.parametrize("draft", [
    "Dạ em đã tạo đơn, dự kiến giao ngày 20/11 ạ.",
    "Mẫu này có khóa trẻ em. Em đã tạo đơn cho mình.",
])
def test_successful_order_survives_rejection_without_additional_tools(draft):
    async def run():
        state = current([order()], draft)
        from test_text_harness_contract import nodes
        from langchain_core.messages import AIMessage
        node, _ = nodes()
        node.llm.ainvoke.return_value = AIMessage(content='Em đã tạo đơn ODLOCAL7 cho mình.')
        result = await node.verify_agent(state)
        assert "ODLOCAL7" in result["agent_text"]
        assert "đã tạo đơn" in result["agent_text"]
        assert "20/11" not in result["agent_text"]
        assert "khóa trẻ em" not in result["agent_text"]
        assert result["verifier_events"]
        node.tools.invoke.assert_not_awaited()
        assert node.llm.ainvoke.await_count == 1
    asyncio.run(run())








def test_even_a_valid_draft_cannot_confirm_a_known_selection_mismatch():
    state = current([{'name':'catalog.search','result':{'items':[{
        'sku':'SKU-LOCAL-A','variants':[{'variant_sku':'SKU-LOCAL-A-R','size':37,'color':'do'}]}]}},
        order()], 'Dạ em đã tạo đơn ODLOCAL7 cho mình ạ.')
    async def run():
        from test_text_harness_contract import nodes
        from langchain_core.messages import AIMessage
        node, _ = nodes()
        node.llm.ainvoke.return_value = AIMessage(content='Em cần kiểm tra lại lựa chọn của mình.')
        result = await node.verify_agent(state)
        assert 'đã tạo đơn' not in result['agent_text']
        assert result['verifier_events']
    asyncio.run(run())
