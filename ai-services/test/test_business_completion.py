"""General tool and context contracts for completing a purchase safely."""
import asyncio
from datetime import date
from uuid import uuid4
from unittest.mock import AsyncMock
from unittest.mock import patch
from datetime import datetime, timezone
from langchain_core.messages import AIMessage
from app.agent.harness.agent_nodes import AgentNodes

from app.agent.implementations.business_agent import BusinessTools
from app.agent.harness.policy import catalog_variant, prepare_tool_call
from app.agent.harness.context import prompt_context
from app.agent.harness.state import Decision
from app.schemas.agent import TextTurnRequest


def state():
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(), channel="hotline",
        channel_identity="0900000000", on=date(2026, 10, 15), text="Lên đơn giúp tôi",
        input_mode="clean")
    return {"request": request, "safe_text": request.text, "identity_status": "known",
            "customer_id": "C-TEST", "customer_phone": "0900000000", "tool_calls": [],
            "tool_count": 0}


def test_parent_resolves_only_unique_catalog_variant_and_keeps_scopes():
    current = state()
    current["tool_calls"] = [{"name": "catalog.search", "result": {"items": [{
        "sku": "SKU-TEST", "variants": [
            {"variant_sku": "SKU-TEST-A", "size": 40, "color": "den"},
            {"variant_sku": "SKU-TEST-B", "size": 41, "color": "trang"}]}]}}]
    assert catalog_variant(current, {"sku": "SKU-TEST"}) is None
    assert catalog_variant(current, {"sku": "SKU-TEST", "size": 41}) == "SKU-TEST-B"
    assert catalog_variant(current, {"sku": "SKU-TEST", "color": "đen"}) == "SKU-TEST-A"
    assert catalog_variant(current, {"sku": "SKU-TEST", "size": 44}) is None
    current["decision"] = Decision(action="tool", tool_name="inventory.check",
        tool_args={"sku": "SKU-TEST", "size": 41, "color": "trang"})
    assert prepare_tool_call(current, lambda: None)[1] == {
        "sku": "SKU-TEST-B", "on": "2026-10-15"}
    current["scoped_facts"] = {"product": {"SKU-TEST": {"size": {
        "value": 40, "source_kind": "customer"}}, "SKU-OTHER": {"color": {
        "value": "trang", "source_kind": "customer"}}}}
    assert catalog_variant(current, {"sku": "SKU-TEST"}) == "SKU-TEST-A"
    context = prompt_context(current, 6)
    assert context["customer_facts"]["products"][0]["size"]["value"] == 40
    assert context["customer_facts"]["products"][1]["sku"] == "SKU-OTHER"


def test_repeat_reads_do_not_spend_budget_and_writes_are_not_cached():
    asyncio.run(_repeat_reads())


async def _repeat_reads():
    current = state()
    gateway = AsyncMock()
    gateway.invoke_trusted.return_value = {"sku": "SKU-TEST", "in_stock": True}
    business = BusinessTools(gateway, current, 3, lambda: None)
    first = await business.invoke("inventory.check", {"sku": "SKU-TEST"})
    second = await business.invoke("inventory.check", {"sku": "SKU-TEST"})
    assert first == second
    assert current["tool_count"] == 1
    assert gateway.invoke_trusted.await_count == 1
    gateway.invoke_trusted.return_value = {"sku": "SKU-TEST", "final_price_vnd": 120000}
    await business.invoke("pricing.get_quote", {"sku": "SKU-TEST"})
    gateway.invoke_trusted.return_value = {"status": "created", "order_id": "OD-TEST"}
    created = await business.invoke("order.create", {"sku": "SKU-TEST", "price_vnd": 120000,
                                                    "payment": "COD", "qty": 1})
    assert created["status"] == "created"
    assert (await business.invoke("order.create", {"sku": "SKU-TEST", "price_vnd": 120000})) == {
        "error": "tool_limit"}
    assert gateway.invoke_trusted.await_count == 3


def test_ready_purchase_gets_one_continuation_but_unknown_customer_does_not():
    async def run(identity, text="Lên đơn giúp tôi"):
        current = state()
        current["safe_text"] = text
        current["identity_status"] = identity
        node = object.__new__(AgentNodes)
        node.tools, node.llm = AsyncMock(), object()
        node.max_tool_calls, node.prompt_history_turns, node.agent_kind = 5, 6, "deep"
        node.clock = lambda: datetime.now(timezone.utc)
        agent = AsyncMock()

        async def respond(*args, **kwargs):
            if not current["tool_calls"]:
                current["tool_calls"] = [
                    {"name": "inventory.check", "args": {"sku": "SKU-TEST"},
                     "result": {"in_stock": True}},
                    {"name": "pricing.get_quote", "args": {"sku": "SKU-TEST"},
                     "result": {"final_price_vnd": 120000}}]
                current["tool_count"] = 2
            return {"messages": [AIMessage(content="Dạ em kiểm tra tiếp ạ")]}

        agent.ainvoke.side_effect = respond
        with patch("app.agent.harness.agent_nodes.build_agent", return_value=agent), \
             patch("app.agent.harness.agent_nodes.text_prompt", return_value="test"):
            await node.run_agent(current)
        return agent.ainvoke.await_count

    assert asyncio.run(run("known")) == 2
    assert asyncio.run(run("unknown")) == 1
    assert asyncio.run(run("known", "Chưa lên đơn nhé")) == 1


def test_invented_sku_is_not_sent_to_gateway_or_charged_to_budget():
    async def run():
        current = state()
        current["tool_calls"] = [{"name": "catalog.search", "result": {"items": [
            {"sku": "SKU-TEST", "variants": []}]}}]
        gateway = AsyncMock()
        business = BusinessTools(gateway, current, 3, lambda: None)
        result = await business.invoke("pricing.get_quote", {"sku": "SKU-INVENTED"})
        assert result == {"error": "unverified_sku", "next_tool": "catalog.search"}
        assert current["tool_count"] == 0
        gateway.invoke_trusted.assert_not_awaited()
    asyncio.run(run())


def test_explicit_human_request_routes_without_model_and_checks_ticket():
    async def run():
        current = state()
        current["safe_text"] = "Cho tôi gặp nhân viên tư vấn giúp nhé"
        node = object.__new__(AgentNodes)
        node.tools, node.llm = AsyncMock(), object()
        node.tools.invoke_trusted.return_value = {"status": "queued", "ticket_id": "HT-TEST"}
        node.max_tool_calls, node.prompt_history_turns = 5, 6
        node.clock = lambda: datetime.now(timezone.utc)
        with patch("app.agent.harness.agent_nodes.build_agent") as build:
            result = await node.run_agent(current)
        build.assert_not_called()
        assert result["needs_handoff"] is True
        assert result["handoff_ticket_id"] == "HT-TEST"
        assert current["tool_calls"][0]["name"] == "handoff.transfer"
    asyncio.run(run())
