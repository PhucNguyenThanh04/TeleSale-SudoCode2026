"""Returning callers see product-specific history and dated refreshes."""

import unittest
from datetime import date, datetime, timezone
from uuid import uuid4

from app.agent.harness.context import load_context, prompt_context
from app.schemas.agent import TextTurnRequest


class Memory:
    include_prior = True
    max_episodes = 5

    async def read_context(self, _session_id, _customer_id):
        return {"history": [], "profile": {}, "owned_order_ids": [],
                "episodes": [{"session_id": str(uuid4()), "channel": "chat_fanpage",
                              "on": "2026-02-15", "summary": "Hỏi hai mẫu", "outcome": "khac"}],
                "scoped_facts": {"room": {
                    "phong_ngu": {"room_area_m2": {"value": 12, "source_kind": "customer"}},
                    "phong_khach": {"room_area_m2": {"value": 45, "source_kind": "customer"}}},
                    "product": {
                    "SKU-ALPHA": {"product_advised": {"value": "SKU-ALPHA", "source_kind": "tool"},
                                  "price_quoted_vnd": {"value": 2_000_000, "source_kind": "tool",
                                                       "on": "2026-02-15"}},
                    "SKU-BETA": {"product_advised": {"value": "SKU-BETA", "source_kind": "tool"},
                                 "price_quoted_vnd": {"value": 4_000_000, "source_kind": "tool",
                                                      "on": "2026-02-15"}}}}}


class Tools:
    def __init__(self):
        self.calls = []

    async def invoke(self, name, args):
        self.calls.append((name, args))
        if name == "inventory.check":
            return {"sku": args["sku"], "in_stock": True}
        return {"sku": args["sku"], "final_price_vnd": 2_500_000,
                "applied_promos": []}


class ScopedContextTest(unittest.IsolatedAsyncioTestCase):
    async def test_refreshes_only_named_sku_and_keeps_other_history_separate(self):
        tools = Tools()
        request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
            channel="hotline", channel_identity="0984726714", on=date(2026, 10, 15),
            text="Cho tôi giá SKU-ALPHA hôm nay", input_mode="clean")
        state = {"request": request, "safe_text": request.text, "customer_id": "C900",
                 "customer_phone": "0984726714", "identity_status": "known",
                 "received_at_monotonic": 0.0, "tool_calls": []}
        loaded = await load_context(state, Memory(), tools,
                                    lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
        brief = loaded["call_brief"]
        self.assertEqual({item["sku"]: item["price_quoted_vnd"]
                          for item in brief["products_advised"]},
                         {"SKU-ALPHA": 2_000_000, "SKU-BETA": 4_000_000})
        self.assertEqual({args["sku"] for _, args in tools.calls}, {"SKU-ALPHA"})
        self.assertTrue(all(args["on"] == "2026-10-15" for _, args in tools.calls))
        self.assertTrue(any("SKU-ALPHA" in warning for warning in brief["stale_warnings"]))
        self.assertFalse(any("SKU-BETA" in warning for warning in brief["stale_warnings"]))
        context = prompt_context({**state, **loaded}, 6)
        self.assertEqual({room["room"] for room in context["customer_facts"]["rooms"]},
                         {"phong_ngu", "phong_khach"})
        self.assertEqual({product["sku"] for product in context["sales_history"]["products"]},
                         {"SKU-ALPHA", "SKU-BETA"})
