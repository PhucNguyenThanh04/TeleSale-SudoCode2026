"""The model must stop receiving callable tools once its turn budget is spent."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.agent.implementations.business_agent import BusinessOnlyMiddleware, BusinessTools
from app.schemas.agent import TextTurnRequest


def test_model_has_no_business_tools_after_turn_budget_is_exhausted():
    state = {"tool_count": 3}
    business = BusinessTools(None, state, 3, lambda: None)
    middleware = BusinessOnlyMiddleware(business)

    class Request:
        tools = [SimpleNamespace(name="catalog.search"),
                 SimpleNamespace(name="pricing.get_quote")]

        def override(self, **changes):
            return SimpleNamespace(**changes)

    async def handler(request):
        return request.tools

    result = asyncio.run(middleware.awrap_model_call(Request(), handler))
    assert result == []


def test_quote_name_is_rejected_with_catalog_instruction_before_mcp_call():
    class Gateway:
        def __init__(self):
            self.calls = []

        async def invoke(self, name, args):
            self.calls.append((name, args))
            return {"error": "unknown_sku"}

    gateway = Gateway()
    state = {"request": TextTurnRequest(
        client_msg_id=uuid4(), session_id=uuid4(), channel="web_chat",
        channel_identity=None,
        on="2026-10-15", text="Giá AirPure X?", input_mode="clean"),
        "tool_calls": [], "tool_count": 0}
    business = BusinessTools(gateway, state, 3, lambda: None)
    result = asyncio.run(business.invoke("pricing.get_quote", {"sku": "AirPure X"}))
    assert result == {"error": "sku_required", "next_tool": "catalog.search"}
    assert gateway.calls == []
