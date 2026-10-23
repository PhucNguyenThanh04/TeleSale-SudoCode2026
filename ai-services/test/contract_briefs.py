"""BTC brief shapes and evidence boundaries, using synthetic non-sample cases."""

import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from app.agent.harness.context import load_context, prompt_context
from app.agent.guardrails.checks import check_grounding
from app.agent.harness.policy import prepare_tool_call
from app.agent.implementations.business_agent import BusinessTools
from app.agent.harness.state import Decision
from app.schemas.agent import TextTurnRequest


SCHEMAS = Path(__file__).resolve().parents[3] / "BTC-Data-Vong1-TEAMS/schemas"


def valid_brief(name, value):
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def request(text="Tôi cần hỏi thêm về sản phẩm", identity="0923456789"):
    return TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
        channel="hotline", channel_identity=identity, on=date(2026, 10, 15),
        text=text, input_mode="clean")


class BriefContract(unittest.IsolatedAsyncioTestCase):
    def test_failed_handoff_cannot_be_announced_as_complete(self):
        failed = [{"name": "handoff.transfer", "args": {"brief": {}},
                   "result": {"ticket_id": "HT0042", "status": "failed"}}]
        announced = "Dạ, em đã chuyển yêu cầu đến nhân viên tư vấn ạ."
        self.assertEqual(check_grounding(announced, failed), "handoff_not_queued")
        self.assertIsNone(check_grounding("Dạ, em sẽ nhờ nhân viên hỗ trợ ạ.", failed))
        self.assertIsNone(check_grounding("Dạ, đơn đã chuyển sang mẫu khác ạ.", []))
        queued = [{**failed[0], "result": {"ticket_id": "HT0042", "status": "queued"}}]
        self.assertIsNone(check_grounding(announced, queued))

    def test_current_turn_quote_is_present_in_handoff(self):
        req = request("Tôi cần hỏi nhân viên thêm về SKU-NEW")
        state = {"request": req, "safe_text": req.text, "customer_phone": "0923456789",
            "customer_id": "C88", "identity_status": "known", "profile": {},
            "scoped_facts": {"product": {}, "room": {}}, "episodes": [], "history": [],
            "tool_calls": [{"name": "pricing.get_quote", "args": {"sku": "SKU-NEW",
                "on": "2026-10-15"}, "result": {"sku": "SKU-NEW",
                "final_price_vnd": 2300000, "applied_promos": []}}],
            "decision": Decision(action="tool", tool_name="handoff.transfer", tool_args={
                "brief": {"escalation_reason": "khach_yeu_cau_gap_nguoi"}})}
        brief = prepare_tool_call(state, lambda: datetime(2026, 10, 15,
            tzinfo=timezone.utc))[1]["brief"]
        valid_brief("handoff_brief", brief)
        self.assertEqual(brief["product_advised"], "SKU-NEW")
        self.assertEqual(brief["price_quoted_vnd"], 2300000)

    def test_ordinary_catalog_request_does_not_create_handoff(self):
        req = request("Tìm máy lọc cho phòng 25 mét vuông")
        state = {"request": req, "safe_text": req.text, "customer_phone": "0923456789",
            "decision": Decision(action="tool", tool_name="catalog.search",
                tool_args={"query": "máy lọc", "min_room_area_m2": 25})}
        name, args = prepare_tool_call(state, lambda: datetime.now(timezone.utc))
        self.assertEqual(name, "catalog.search")
        self.assertEqual(args["min_room_area_m2"], 25)

    async def test_promo_status_uses_successful_dated_quote_only(self):
        class Memory:
            include_prior = True
            max_episodes = 5

            async def read_context(self, *_):
                return {"history": [], "profile": {}, "owned_order_ids": [],
                    "episodes": [{"session_id": "old-call", "channel": "hotline",
                        "on": "2026-07-15", "summary": "Hỏi mẫu SKU-N", "outcome": "khac"}],
                    "scoped_facts": {"room": {}, "product": {"SKU-N": {
                        "promo_code": {"value": "SAVE-N", "source_kind": "tool"}}}}}

        class Tools:
            def __init__(self, promos):
                self.promos = promos

            async def invoke(self, name, args):
                if name == "inventory.check":
                    return {"sku": args["sku"], "in_stock": True}
                if self.promos is None:
                    return {"sku": args["sku"]}
                return {"sku": args["sku"], "final_price_vnd": 1230000,
                        "applied_promos": [{"promo_code": code} for code in self.promos]}

        req = request("SKU-N có còn ưu đãi không?")
        state = {"request": req, "safe_text": req.text, "customer_id": "C88",
            "customer_phone": "0923456789", "identity_status": "known",
            "received_at_monotonic": __import__("time").perf_counter(), "tool_calls": []}
        for promos, expected in ((["SAVE-N"], True), ([], False), (None, None)):
            with self.subTest(promos=promos):
                loaded = await load_context(state, Memory(), Tools(promos),
                    lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
                brief = loaded["call_brief"]
                valid_brief("call_brief", brief)
                self.assertIs(brief["products_advised"][0]["promo_still_active"], expected)

    async def test_ticket_without_queued_status_is_not_accepted(self):
        class Gateway:
            async def invoke(self, *_):
                return {"ticket_id": "HT0042", "status": "failed"}

        req = request("Xin gặp nhân viên tư vấn")
        state = {"request": req, "safe_text": req.text, "customer_phone": "0923456789",
            "identity_status": "known", "customer_id": "C88", "profile": {},
            "scoped_facts": {"product": {}, "room": {}}, "episodes": [], "history": [],
            "tool_calls": [], "tool_count": 0}
        result = await BusinessTools(Gateway(), state, 3,
            lambda: datetime(2026, 10, 15, tzinfo=timezone.utc)).invoke("handoff.transfer",
            {"brief": {"escalation_reason": "khach_yeu_cau_gap_nguoi"}})
        self.assertEqual(result["status"], "failed")
        self.assertFalse(state.get("needs_handoff", False))

    def test_handoff_uses_verified_values_and_keeps_ambiguous_product_unknown(self):
        req = request("Hai mẫu SKU-X và SKU-Y có dùng được khi mang thai không?")
        state = {"request": req, "safe_text": req.text, "customer_id": "C88",
            "customer_phone": "0923456789", "customer_name": "Mai", "identity_status": "known",
            "profile": {}, "scoped_facts": {"room": {
                "room_a": {"room_area_m2": {"value": 15, "source_kind": "customer"}},
                "room_b": {"room_area_m2": {"value": 30, "source_kind": "customer"}}}, "product": {
                "SKU-X": {"price_quoted_vnd": {"value": 2000000, "source_kind": "tool"}},
                "SKU-Y": {"price_quoted_vnd": {"value": 2000000, "source_kind": "tool"}}}},
            "episodes": [], "history": [], "tool_calls": [],
            "decision": Decision(action="tool", tool_name="handoff.transfer", tool_args={"brief": {
                "customer_phone": "0999999999", "customer_name": "Fake",
                "escalation_reason": "cau_hoi_y_te", "conversation_summary": "fake",
                "product_advised": "SKU-X", "price_quoted_vnd": 1,
                "open_questions": [], "next_action": "fake", "generated_at": "2000-01-01T00:00:00Z"}})}
        prepared = prepare_tool_call(state, lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
        self.assertIsNotNone(prepared)
        brief = prepared[1]["brief"]
        valid_brief("handoff_brief", brief)
        self.assertEqual(brief["customer_phone"], "0923456789")
        self.assertEqual(brief["customer_name"], "Mai")
        self.assertIsNone(brief["product_advised"])
        self.assertIsNone(brief["price_quoted_vnd"])
        self.assertIn(req.text, brief["open_questions"])
        self.assertEqual(brief["facts_confirmed"]["rooms"]["room_a"]["room_area_m2"], 15)

    def test_no_trusted_phone_blocks_ordinary_handoff(self):
        req = request(identity="unknown")
        state = {"request": req, "customer_phone": None, "identity_status": "unknown",
            "decision": Decision(action="tool", tool_name="handoff.transfer",
                tool_args={"brief": {"escalation_reason": "khac"}})}
        self.assertIsNone(prepare_tool_call(state, lambda: datetime.now(timezone.utc)))

    async def test_call_brief_keeps_scoped_history_and_unknown_promo(self):
        class Memory:
            include_prior = True
            max_episodes = 5

            async def read_context(self, *_):
                return {"history": [], "profile": {}, "owned_order_ids": [],
                    "prior_session_ids": [f"old-{i}" for i in range(7)],
                    "episodes": [{"session_id": f"old-{i}", "channel": "chat_fanpage",
                        "on": "2026-08-01", "summary": "Hỏi hai mẫu lọc không khí",
                        "outcome": "khac"} for i in range(5)],
                    "scoped_facts": {"room": {
                        "room_a": {"room_area_m2": {"value": 15, "source_kind": "customer"}},
                        "room_b": {"room_area_m2": {"value": 30, "source_kind": "customer"}}},
                        "product": {sku: {"price_quoted_vnd": {"value": 2000000,
                            "source_kind": "tool", "on": "2026-08-01"},
                            "promo_code": {"value": "PROMO-A", "source_kind": "tool"}}
                            for sku in ("SKU-X", "SKU-Y")}}}

        class Tools:
            async def invoke(self, name, args):
                return {"sku": args["sku"], "in_stock": True} if name == "inventory.check" else {"error": "unavailable"}

        req = request("Giá SKU-X hôm nay thế nào?")
        state = {"request": req, "safe_text": req.text, "customer_id": "C88",
            "customer_phone": "0923456789", "identity_status": "known",
            "received_at_monotonic": __import__("time").perf_counter(), "tool_calls": [],
            "crm_sessions": [{"session_id": "old-0", "channel": "chat_fanpage",
                "date": "2026-08-01", "summary": "Hỏi hai mẫu", "outcome": "khac"}]}
        result = await load_context(state, Memory(), Tools(),
                                    lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
        brief = result["call_brief"]
        valid_brief("call_brief", brief)
        self.assertEqual(brief["n_previous_sessions"], 7)
        self.assertEqual({x["sku"]: x["price_quoted_vnd"] for x in brief["products_advised"]},
                         {"SKU-X": 2000000, "SKU-Y": 2000000})
        self.assertEqual(brief["products_advised"][0]["quoted_on"], "2026-08-01")
        self.assertIsNone(brief["products_advised"][0]["promo_still_active"])
        self.assertIn("room_area_m2", brief["must_not_ask"])
        self.assertNotIn("0923456789", str(prompt_context({**state, **result}, 6)))
