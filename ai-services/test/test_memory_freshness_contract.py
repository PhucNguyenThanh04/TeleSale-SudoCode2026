"""Contract for reopening a customer conversation months later."""

import json
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.agent.harness.runtime import DeepHarnessRuntime
from app.agent.harness.context import load_context, prompt_context
from app.agent.guardrails.checks import check_answer
from memory_contract import check_snapshot, load_cases
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn
from contract_memory_updates import btc_mock


CASES = {case["case"]: case for case in load_cases(
    Path(__file__).parent / "fixtures" / "memory_contract_v1.json")}


class SavedMemory:
    include_prior = True
    max_episodes = 5

    def __init__(self, profile):
        self.profile = profile

    async def read_context(self, session_id, customer_id):
        return {"history": [], "profile": self.profile,
                "episodes": [{"session_id": str(uuid4()), "channel": "hotline",
                              "on": "2026-10-15", "summary": "Hỏi mẫu lọc cũ",
                              "outcome": "khac"}], "owned_order_ids": [], "turn_count": 0}


class ReferenceGateway:
    def __init__(self):
        self.calls = []

    async def invoke(self, name, args):
        self.calls.append((name, args))
        mock = btc_mock()
        if name == "inventory.check":
            return mock.inventory_check(args["sku"], args["on"])
        if name == "pricing.get_quote":
            return mock.pricing_get_quote(args["sku"], args["on"])
        return {"error": "unavailable"}


class MemoryFreshnessContract(unittest.IsolatedAsyncioTestCase):
    async def test_initial_call_establishes_customer_room_area(self):
        case = CASES["return_after_months"]
        first_call = case["calls"][0]
        model = FakeToolModel(replies=[
            AIMessage(content='{"answer":"Dạ, em ghi nhận ạ.","fact_candidates":'
                              '[{"key":"room_area_m2","value":30,"source":"customer"}]}'),
            AIMessage(content="Dạ, em sẽ kiểm tra ạ.")])
        memory = FakeMemory()
        runtime = DeepHarnessRuntime(model, FakeGateway(customer_id="C106"), memory)
        session = uuid4()
        for item in first_call["turns"]:
            request = turn(item["text"], session)
            await runtime.run(request)
            actual = {"customer_id": runtime.state_for(request).get("customer_id"),
                      "profile": memory.profile}
            self.assertEqual(check_snapshot(item["expected_after_turn"], actual), [])

    def test_old_quote_cannot_be_presented_as_current_price(self):
        sku, on = "SKU-AP-MINI", "2027-06-15"
        quote = btc_mock().pricing_get_quote(sku=sku, on=on)
        answer, reason = check_answer("Dạ, giá hiện tại là 4.000.000 đồng.",
                                      [{"name": "pricing.get_quote",
                                        "args": {"sku": sku, "on": on},
                                        "result": quote}],
                                      "Mẫu Mini còn giá cũ không?")
        self.assertIsNotNone(reason)
        self.assertNotIn("4.000.000", answer)

    async def test_early_return_keeps_preference_but_rechecks_price(self):
        request = turn("Mẫu Mini hôm trước còn giá đó không?").model_copy(update={
            "on": datetime(2026, 10, 18).date()})
        state = {"request": request, "safe_text": request.text,
                 "customer_id": "C106", "customer_phone": "0900000106",
                 "identity_status": "resolved", "received_at_monotonic": time.perf_counter(),
                 "tool_calls": []}
        memory = SavedMemory({
            "preferred_color": {"key": "preferred_color", "value": "trắng",
                                "source_kind": "customer"},
            "product_advised": {"key": "product_advised", "value": "SKU-AP-MINI",
                                "source_kind": "tool"},
            "price_quoted_vnd": {"key": "price_quoted_vnd", "value": 2_190_000,
                                 "source_kind": "tool"}})
        gateway = ReferenceGateway()
        result = await load_context(state, memory, gateway,
                                    lambda: datetime(2026, 10, 18, tzinfo=timezone.utc))
        self.assertEqual(result["call_brief"]["profile_facts"]["preferred_color"],
                         "trắng")
        self.assertIn(("pricing.get_quote", "2026-10-18"),
                      [(name, args["on"]) for name, args in gateway.calls])

    async def test_eight_month_return_refreshes_stock_and_quote_on_call_date(self):
        case = CASES["return_after_months"]
        on = case["calls"][1]["on"]
        request = turn(case["calls"][1]["turns"][0]["text"]).model_copy(update={
            "on": datetime.fromisoformat(on).date()})
        state = {"request": request, "safe_text": request.text,
                 "customer_id": "C106", "customer_phone": "0900000106",
                 "identity_status": "resolved", "received_at_monotonic": time.perf_counter(),
                 "tool_calls": []}
        memory = SavedMemory({
            "room_area_m2": {"key": "room_area_m2", "value": 30,
                             "source_kind": "customer"},
            "product_advised": {"key": "product_advised", "value": "SKU-AP-X-2024",
                                "source_kind": "tool"},
            "price_quoted_vnd": {"key": "price_quoted_vnd", "value": 4_000_000,
                                 "source_kind": "tool"}})
        gateway = ReferenceGateway()
        result = await load_context(state, memory, gateway,
                                    lambda: datetime(2027, 6, 15, tzinfo=timezone.utc))
        expected = case["calls"][1]["turns"][0]["expected_after_turn"]
        self.assertEqual(check_snapshot(expected, {
            "customer_id": state["customer_id"], "profile": result["profile"]}), [])
        self.assertEqual([(name, args["on"]) for name, args in gateway.calls],
                         [("inventory.check", on), ("pricing.get_quote", on)])
        self.assertIn("hết hàng", " ".join(result["call_brief"]["stale_warnings"]))
        self.assertEqual(result["call_brief"]["profile_facts"]["room_area_m2"], 30)
        self.assertEqual(result["profile"]["price_quoted_vnd"]["value"], 4_000_000)
        self.assertEqual(result["tool_calls"][1]["result"]["final_price_vnd"],
                         btc_mock().pricing_get_quote("SKU-AP-X-2024", on)["final_price_vnd"])

    async def test_old_raw_address_never_enters_prompt(self):
        request = turn("Giao về địa chỉ cũ được không?").model_copy(update={
            "on": datetime(2027, 6, 15).date()})
        state = {"request": request, "safe_text": request.text,
                 "customer_id": "C106", "customer_phone": "0900000106",
                 "identity_status": "resolved", "received_at_monotonic": time.perf_counter(),
                 "tool_calls": []}
        address = "12 Đường Thử Nghiệm, Hà Nội"
        memory = SavedMemory({
            "delivery_address": {"key": "delivery_address", "value": address,
                                 "source_kind": "customer"}})
        result = await load_context(state, memory, ReferenceGateway(),
                                    lambda: datetime(2027, 6, 15, tzinfo=timezone.utc))
        context = prompt_context({**state, **result}, history_turns=6)
        self.assertNotIn("delivery_address", result["profile"])
        self.assertNotIn(address, json.dumps(context, ensure_ascii=False))
        self.assertNotIn(address, json.dumps(result["call_brief"], ensure_ascii=False))

    async def test_legacy_personal_fields_and_history_are_filtered_but_valid_preference_remains(self):
        request = turn("Tôi vẫn thích màu trắng.")
        state = {"request": request, "safe_text": request.text,
                 "customer_id": "C106", "customer_phone": "0900000106",
                 "identity_status": "known", "received_at_monotonic": time.perf_counter(),
                 "tool_calls": []}
        memory = SavedMemory({
            "delivery_address": {"key": "delivery_address", "value": "45 Phố Kiểm Thử, Hà Nội",
                                 "source_kind": "customer"},
            "preferred_color": {"key": "preferred_color", "value": "trắng",
                                "source_kind": "customer"},
        })
        result = await load_context(state, memory, ReferenceGateway(),
                                    lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
        result["history"] = [{"customer": "Giao tới 45 Phố Kiểm Thử, Hà Nội",
                              "agent": "Dạ."}]
        context = prompt_context({**state, **result}, history_turns=6)
        self.assertNotIn("45 Phố Kiểm Thử", json.dumps(context, ensure_ascii=False))
        self.assertNotIn("45 Phố Kiểm Thử", json.dumps(result["call_brief"], ensure_ascii=False))
        self.assertEqual(context["customer_facts"]["preferred_color"]["value"], "trắng")

    async def test_legacy_address_inside_allowed_fact_and_episode_is_not_exposed(self):
        request = turn("Tôi muốn hỏi tiếp máy lọc.")
        state = {"request": request, "safe_text": request.text,
                 "customer_id": "C106", "customer_phone": "0900000106",
                 "identity_status": "known", "received_at_monotonic": time.perf_counter(),
                 "tool_calls": []}
        addresses = ("12 ngõ 34, phường Mai Dịch, Hà Nội",
                     "Căn 1205 tòa nhà A, quận Cầu Giấy",
                     "Ngõ 12, phường Mai Dịch, Hà Nội",
                     "Căn hộ 1205, chung cư Mai Dịch, Hà Nội",
                     "Cần hỏi Nguyễn Văn An trước khi mua")
        for address in addresses:
            with self.subTest(address=address):
                memory = SavedMemory({
                    "blocker": {"key": "blocker", "value": address,
                                "source_kind": "customer"},
                    "preferred_color": {"key": "preferred_color", "value": "trắng",
                                        "source_kind": "customer"},
                })

                async def legacy_read(session_id, customer_id):
                    return {"history": [{"customer": f"Tôi ở {address}", "agent": "Dạ."}],
                            "profile": memory.profile,
                            "episodes": [{"session_id": str(uuid4()), "channel": "hotline",
                                          "on": "2026-10-15", "summary": f"Giao đến {address}",
                                          "outcome": "khac"}],
                            "owned_order_ids": [], "turn_count": 1}

                memory.read_context = legacy_read
                result = await load_context(state, memory, ReferenceGateway(),
                                            lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
                context = prompt_context({**state, **result}, history_turns=6)
                visible = json.dumps({"profile": result["profile"], "context": context,
                                      "brief": result["call_brief"]}, ensure_ascii=False)
                self.assertNotIn(address, visible)
                self.assertEqual(context["customer_facts"]["preferred_color"]["value"],
                                 "trắng")
