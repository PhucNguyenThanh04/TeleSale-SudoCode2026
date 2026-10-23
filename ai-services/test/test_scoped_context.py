"""Returning callers see product-specific history and dated refreshes."""

import unittest
from datetime import date, datetime, timezone
from uuid import uuid4

from app.agent.harness.context import load_context, prompt_context, _open_episode_items
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
    async def test_structured_blocker_takes_precedence_over_legacy_fact_wording(self):
        class BlockerMemory(Memory):
            async def read_context(self, session_id, customer_id):
                data = await super().read_context(session_id, customer_id)
                data["profile"] = {"blocker": {"value": "hỏi ông xã",
                                              "source_kind": "customer"}}
                data["episodes"][0]["topics"] = [{"scope_type": "unknown",
                    "scope_id": "", "items": [{"kind": "blocker", "status": "open",
                        "text": "cần hỏi chồng", "item_id": "b-1"}]}]
                return data

        request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
            channel="hotline", channel_identity="0984726714", on=date(2026, 10, 15),
            text="Tôi gọi lại", input_mode="clean")
        state = {"request": request, "safe_text": request.text,
                 "customer_id": "C900", "customer_phone": "0984726714",
                 "identity_status": "known", "received_at_monotonic": 0.0,
                 "tool_calls": []}
        result = await load_context(state, BlockerMemory(), Tools(),
                                    lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
        self.assertEqual(result["call_brief"]["open_blockers"], ["cần hỏi chồng"])

    def test_same_open_question_for_two_products_keeps_both_scopes(self):
        episode = {"topics": [
            {"scope_type": "product", "scope_id": "SKU-A",
             "items": [{"item_id": "a", "kind": "question", "text": "Giá bao nhiêu?",
                        "status": "open"}]},
            {"scope_type": "product", "scope_id": "SKU-B",
             "items": [{"item_id": "b", "kind": "question", "text": "Giá bao nhiêu?",
                        "status": "open"}]},
        ]}
        self.assertEqual(_open_episode_items([episode], "question"),
                         ["SKU-A: Giá bao nhiêu?", "SKU-B: Giá bao nhiêu?"])

    def test_later_session_resolution_hides_older_open_question(self):
        episodes = [
            {"session_id": "recent", "topics": [],
             "resolved_prior_items": [{"item_id": "q-1"}]},
            {"session_id": "older", "topics": [{"scope_type": "unknown",
                "scope_id": "", "items": [{"item_id": "q-1", "kind": "question",
                    "text": "Có giao cuối tuần?", "status": "open"}]}]},
        ]
        self.assertEqual(_open_episode_items(episodes, "question"), [])

    async def test_prior_open_items_only_on_first_turn(self):
        class EpisodicMemory(Memory):
            def __init__(self, turn_count):
                self.turn_count = turn_count

            async def read_context(self, session_id, customer_id):
                data = await super().read_context(session_id, customer_id)
                data["turn_count"] = self.turn_count
                data["episodes"][0]["topics"] = [{"scope_type": "product",
                    "scope_id": "SKU-ALPHA", "items": [
                        {"kind": "question", "text": "Có giao cuối tuần?", "status": "open"},
                        {"kind": "blocker", "text": "Cần hỏi người thân", "status": "open"},
                        {"kind": "question", "text": "Có bảo hành?", "status": "resolved"}]}]
                return data

        request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
            channel="hotline", channel_identity="0984726714", on=date(2026, 10, 15),
            text="Tôi muốn trao đổi tiếp", input_mode="clean")
        state = {"request": request, "safe_text": request.text, "customer_id": "C900",
                 "customer_phone": "0984726714", "identity_status": "known",
                 "received_at_monotonic": 0.0, "tool_calls": []}
        first_tools = Tools()
        first = await load_context(state, EpisodicMemory(0), first_tools,
                                   lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
        self.assertEqual(first["call_brief"]["open_questions"], ["Có giao cuối tuần?"])
        self.assertEqual(first["call_brief"]["open_blockers"], ["Cần hỏi người thân"])
        self.assertNotIn("mẫu SKU-ALPHA", first["call_brief"]["suggested_opening"])
        self.assertTrue(first["call_brief"]["stale_warnings"])
        next_tools = Tools()
        later = await load_context(state, EpisodicMemory(1), next_tools,
                                   lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
        self.assertIsNone(later["call_brief"])
        self.assertEqual(next_tools.calls, [])

    async def test_late_identity_emits_brief_when_no_owned_episode_exists(self):
        class LateIdentityMemory(Memory):
            async def read_context(self, session_id, customer_id):
                data = await super().read_context(session_id, customer_id)
                data["turn_count"] = 2
                data["current_episode"] = None
                return data

        request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
            channel="hotline", channel_identity="0984726714", on=date(2026, 10, 15),
            text="Tôi là khách lần trước", input_mode="clean")
        state = {"request": request, "safe_text": request.text, "customer_id": "C900",
                 "customer_phone": "0984726714", "identity_status": "known",
                 "received_at_monotonic": 0.0, "tool_calls": []}
        loaded = await load_context(state, LateIdentityMemory(), Tools(),
                                    lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
        self.assertIsNotNone(loaded["call_brief"])

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
        self.assertEqual(brief["products_advised"][0]["quoted_on"], "2026-02-15")
        self.assertIn("room_area_m2", brief["must_not_ask"])
        self.assertEqual(brief["profile_facts"]["rooms"]["phong_ngu"]["room_area_m2"]["value"], 12)
        self.assertEqual(brief["products_advised"][1]["promo_still_active"], None)
        context = prompt_context({**state, **loaded}, 6)
        self.assertEqual({room["room"] for room in context["customer_facts"]["rooms"]},
                         {"phong_ngu", "phong_khach"})
        self.assertEqual({product["sku"] for product in context["sales_history"]["products"]},
                         {"SKU-ALPHA", "SKU-BETA"})
