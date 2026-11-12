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


def test_repeat_reads_do_not_spend_budget_and_completed_purchase_is_not_repeated():
    asyncio.run(_repeat_reads())


async def _repeat_reads():
    current = state()
    current['safe_text']='Mua SKU-TEST giá 120000đ, lên đơn giúp tôi.'
    current["session_tool_calls"] = [{"name": "catalog.search", "result": {
        "items": [{"sku": "SKU-TEST", "variants": []}]}}]
    gateway = AsyncMock()
    gateway.invoke_trusted.return_value = {"sku": "SKU-TEST", "in_stock": True, "qty":10}
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
    assert (await business.invoke("order.create", {"sku": "SKU-TEST", "price_vnd": 120000})) == created
    assert gateway.invoke_trusted.await_count == 3


def test_ready_purchase_gets_one_continuation_but_unknown_customer_does_not():
    async def run(identity, text="Lên đơn giúp tôi", session_quote=False):
        current = state()
        current["safe_text"] = text
        current["identity_status"] = identity
        node = object.__new__(AgentNodes)
        current['session_tool_calls']=[{'name':'catalog.search','args':{},'result':{'items':[{'sku':'SKU-TEST','variants':[]}]}}]
        current['history']=[{'customer':'Tôi chọn SKU-TEST.','agent':'SKU-TEST giá 120000đ.'}]
        current['tool_calls']=[{'name':'inventory.check','args':{'sku':'SKU-TEST','on':'2026-10-15'},'result':{'in_stock':True,'qty':10}},
            {'name':'pricing.get_quote','args':{'sku':'SKU-TEST','on':'2026-10-15','qty':1},'result':{'sku':'SKU-TEST','final_price_vnd':120000}}]
        from copy import deepcopy
        from test_commerce_evidence import bind_history_observations
        prior_quote = current['tool_calls'].pop() if session_quote else deepcopy(current['tool_calls'][-1])
        current['session_tool_calls'].append(prior_quote)
        bind_history_observations(current)
        node.tools, node.llm = AsyncMock(), object()
        node.tools.invoke_trusted.return_value = {'status':'created','order_id':'OD-CONTINUATION'}
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
        writes = [call for call in node.tools.invoke_trusted.await_args_list if call.args[0]=='order.create']
        return agent.ainvoke.await_count, len(writes)

    # Continuation now writes through BusinessTools instead of prompting the model again.
    assert asyncio.run(run("known")) == (1, 1)
    assert asyncio.run(run("known", session_quote=True)) == (1, 1)
    assert asyncio.run(run("unknown")) == (1, 0)
    assert asyncio.run(run("known", "Chưa lên đơn nhé")) == (1, 0)


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


def test_k0_known_customer_status_lookup_uses_owned_identity_without_asking_again():
    async def run():
        current = state()
        current['safe_text'] = 'Em ơi, anh hỏi tình trạng đơn mình đặt lần trước. Em tra giúp nhé.'
        current['owned_order_ids'] = ['OD-OFFLINE']
        gateway = AsyncMock()
        gateway.invoke_trusted.return_value = {'orders': [{'order_id': 'OD-OFFLINE', 'status': 'shipping'}]}
        tools = BusinessTools(gateway, current, 3, lambda: None)
        assert await tools.prepare_order_status()
        assert current['tool_calls'][-1]['args']['order_id'] == 'OD-OFFLINE'
        await tools.prepare_order_status()
        # The model may request the same lookup by phone after preparation.
        await tools.invoke('order.status', {})
        assert gateway.invoke_trusted.await_count == 1
    asyncio.run(run())


def test_k0_status_preparation_does_not_lookup_foreign_orders_or_unknown_customers():
    async def run():
        for identity, text in [('unknown', 'Em tra tình trạng đơn giúp tôi.'),
                               ('known', 'Em tra đơn OD-FOREIGN giúp tôi.'),
                               ('known', 'Đừng kiểm tra đơn giúp tôi.'),
                               ('known', 'Nếu đặt đơn thì sao?')]:
            current = state()
            current.update(identity_status=identity, safe_text=text, owned_order_ids=['OD-MINE'])
            gateway = AsyncMock()
            assert not await BusinessTools(gateway, current, 3, lambda: None).prepare_order_status()
            gateway.invoke_trusted.assert_not_awaited()
    asyncio.run(run())
