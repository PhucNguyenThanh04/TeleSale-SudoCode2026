from test_deep_memory import FakeStreamAgent
import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.agent.harness.agent_nodes import AgentNodes
from app.agent.guardrails.checks import FALLBACK
from app.schemas.agent import TextTurnRequest


def test_missing_promotion_quote_refreshes_current_date_and_rewrites_old_offer():
    asyncio.run(_exercise())


def test_quote_failure_keeps_unverified_offer_blocked():
    asyncio.run(_exercise(fail=True))


def test_ambiguous_products_do_not_trigger_guessed_quote():
    asyncio.run(_exercise(multiple=True))


def test_remembered_product_still_requires_a_current_quote():
    asyncio.run(_exercise(memory_only=True))


async def _exercise(fail=False, multiple=False, memory_only=False):
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(), channel="hotline",
        channel_identity="0900000000", on=date(2026, 11, 1),
        text="Có tặng gì kèm không?", input_mode="clean")
    current = {"request": request, "safe_text": request.text, "identity_status": "known",
        "customer_id": "TEST", "customer_phone": "0900000000", "tool_calls": [],
        "tool_count": 0, "session_tool_calls": [{"name": "pricing.get_quote",
            "args": {"sku": "SKU-EXAMPLE", "on": "2026-10-01"},
            "result": {"sku": "SKU-EXAMPLE", "final_price_vnd": 1200000,
                       "applied_promos": [{"promo_code": "GIFT-OLD", "type": "gift"}]}}]}
    node = object.__new__(AgentNodes)
    node.tools = AsyncMock()
    node.tools.invoke_trusted.return_value = {"sku": "SKU-EXAMPLE",
        "final_price_vnd": 1200000, "applied_promos": [], "freeship": False}
    if fail:
        node.tools.invoke_trusted.return_value = {"error": "tool_unavailable"}
    if multiple:
        current["session_tool_calls"].append({"name": "pricing.get_quote",
            "args": {"sku": "SKU-OTHER"}, "result": {"sku": "SKU-OTHER"}})
    if memory_only:
        current["session_tool_calls"] = []
        current["scoped_facts"] = {"product": {"SKU-EXAMPLE": {
            "product_advised": {"value": "SKU-EXAMPLE", "source_kind": "tool"}}}}
    node.llm = object()
    node.max_tool_calls, node.prompt_history_turns, node.guardrails_enabled = 5, 6, True
    node.clock = lambda: datetime.now(timezone.utc)
    agent = FakeStreamAgent()
    agent.response.side_effect = [
        {"messages": [AIMessage(content="Dạ, mẫu này đang tặng kèm một màng lọc và miễn phí vận chuyển ạ.")]},
        {"messages": [AIMessage(content="Dạ, giá hiện tại là 1.200.000đ ạ.")]}]
    with patch("app.agent.harness.agent_nodes.build_agent", return_value=agent), \
         patch("app.agent.harness.agent_nodes.text_prompt", return_value="test"):
        output = await node.run_agent(current)
    current.update(output)
    verified = await node.verify_agent(current)
    if fail or multiple:
        assert verified["agent_text"] == FALLBACK
        assert agent.response.await_count == 1
        assert node.tools.invoke_trusted.await_count == (0 if multiple else 1)
        return
    assert verified["agent_text"] != FALLBACK
    assert "tặng" not in verified["agent_text"]
    assert "1.200.000" in verified["agent_text"]
    assert agent.response.await_count == 2
    args = node.tools.invoke_trusted.await_args.args
    assert args[0] == "pricing.get_quote"
    assert args[1]["sku"] == "SKU-EXAMPLE"
    assert args[1]["on"] == "2026-11-01"
