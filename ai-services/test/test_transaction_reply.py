"""Verification must preserve completed transactions without repeating writes."""
import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.harness.agent_nodes import AgentNodes
from app.agent.harness.session_nodes import safe_transaction_reply, safe_quote_reply


def current(calls, draft):
    return {"tool_calls": calls, "agent_draft": draft, "safe_text": "Lên đơn giúp tôi",
            "request": SimpleNamespace(on=date(2026, 11, 2))}


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
        node = object.__new__(AgentNodes)
        node.guardrails_enabled = True
        node.tools = AsyncMock()
        result = await node.verify_agent(state)
        assert "ODLOCAL7" in result["agent_text"]
        assert "đã tạo đơn" in result["agent_text"]
        assert "20/11" not in result["agent_text"]
        assert "khóa trẻ em" not in result["agent_text"]
        assert result["verifier_events"]
        node.tools.invoke.assert_not_awaited()
    asyncio.run(run())


def test_uncertain_write_and_multiple_orders_are_not_guessed():
    for calls in [[{**order(), "result": {"error": "tool_error"}}],
                  [order(), order("ODLOCAL8", "SKU-LOCAL-B")]]:
        reply = safe_transaction_reply(current(calls, ""))
        assert "đã tạo đơn" not in reply
        assert "chưa tạo" not in reply
        assert "ODLOCAL7" not in reply


def test_known_wrong_variant_is_not_confirmed_as_correct():
    state = current([{"name": "catalog.search", "result": {"items": [{
        "sku": "SKU-LOCAL-A", "variants": [{"variant_sku": "SKU-LOCAL-A-R", "size": 37, "color": "do"}]}]}}, order()], "")
    assert "đã tạo đơn" not in safe_transaction_reply(state)


def test_quote_recovery_is_current_and_unambiguous():
    quote = {"name": "pricing.get_quote", "args": {"sku": "SKU-LOCAL-A", "on": "2026-11-02"},
             "result": {"sku": "SKU-LOCAL-A", "final_price_vnd": 430000}}
    assert "430.000" in safe_quote_reply(current([quote], ""))
    assert safe_quote_reply(current([quote, {**quote, "args": {"sku": "SKU-OTHER", "on": "2026-11-02"}}], "")) is None
    quote["args"]["on"] = "2026-11-01"
    assert safe_quote_reply(current([quote], "")) is None


def test_even_a_valid_draft_cannot_confirm_a_known_selection_mismatch():
    state = current([{'name':'catalog.search','result':{'items':[{
        'sku':'SKU-LOCAL-A','variants':[{'variant_sku':'SKU-LOCAL-A-R','size':37,'color':'do'}]}]}},
        order()], 'Dạ em đã tạo đơn ODLOCAL7 cho mình ạ.')
    async def run():
        node = object.__new__(AgentNodes)
        node.guardrails_enabled = True
        result = await node.verify_agent(state)
        assert 'đã tạo đơn' not in result['agent_text']
        assert result['verifier_events']
    asyncio.run(run())
