"""Executable contract for correction and four-product conversations."""

import importlib.util
import os
import unittest
import warnings
from functools import lru_cache
from datetime import date
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.agent.harness.runtime import DeepHarnessRuntime
from app.agent.harness.context import prompt_context
from app.agent.memory.fact_candidates import accepted_candidates
from app.agent.memory.reported_facts import reported_tool_candidates
from app.mcp_servers.mcp_memory.services.memory import write
from app.constants import DEFAULT_PROMPT_HISTORY_TURNS
from memory_contract import check_snapshot, load_cases
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn
from test_mcp_memory import TurnRepo


ROOT = Path(__file__).resolve().parents[2]
CASES = {case["case"]: case for case in load_cases(
    Path(__file__).parent / "fixtures" / "memory_contract_v1.json")}


@lru_cache(maxsize=1)
def btc_mock():
    data_dir = Path(os.getenv("BTC_DATA_DIR", ROOT.parent / "BTC-Data-Vong1-TEAMS"))
    path = data_dir / "eval" / "mock_tools.py"
    spec = importlib.util.spec_from_file_location("btc_reference_mock", path)
    module = importlib.util.module_from_spec(spec)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        spec.loader.exec_module(module)
    return module


def active_room_constraints(customer_facts):
    """Project scoped, active room facts without counting transcript mentions."""
    found = []

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            area = value.get("room_area_m2")
            if area is None and value.get("key") == "room_area_m2":
                area = value.get("value")
            if isinstance(area, dict):
                area = area.get("value")
            scope = next((value[key] for key in ("room", "scope", "location")
                          if isinstance(value.get(key), str) and value[key].strip()), None)
            if type(area) is int and scope and value.get("status", "active") == "active":
                found.append((scope, area))
            for item in value.values():
                if isinstance(item, (dict, list)):
                    visit(item)

    visit(customer_facts)
    return found


class MemoryUpdateContract(unittest.IsolatedAsyncioTestCase):
    async def test_sixteen_turn_harness_routes_each_requested_quote(self):
        case = CASES["many_products"]
        mock = btc_mock()

        class Gateway(FakeGateway):
            async def invoke(self, name, args):
                self.calls.append((name, args))
                if name == "crm.get_customer":
                    return {"found": True, "customer_id": "C105",
                            "phone": "0900000105", "orders": [], "sessions": []}
                if name == "pricing.get_quote":
                    return mock.pricing_get_quote(sku=args["sku"], on=args["on"])
                return {"error": "unavailable"}

        model = FakeToolModel(replies=[])
        gateway = Gateway()
        memory = FakeMemory()
        runtime = DeepHarnessRuntime(model, gateway, memory)
        session = uuid4()
        final_first_call_context = None
        for call in case["calls"]:
            for item in call["turns"]:
                expected = item["expected_after_turn"]
                quote = expected.get("tool_calls", {}).get("contains")
                if quote:
                    sku = quote["args"]["sku"]
                    value = mock.pricing_get_quote(sku=sku, on=call["on"])
                    model.replies[:] = [
                        AIMessage(content="", tool_calls=[{
                            "name": "pricing.get_quote", "args": {"sku": sku},
                            "id": "quote_" + sku}]),
                        AIMessage(content=f"{sku} hiện giá {value['final_price_vnd']:,} đồng.")]
                elif "profile" in expected:
                    area = expected["profile"]["room_area_m2"]["value"]
                    model.replies[:] = [AIMessage(content=
                        '{"answer":"Dạ, em ghi nhận ạ.","fact_candidates":'
                        f'[{{"key":"room_area_m2","value":{area},"source":"customer"}}]}}')]
                else:
                    model.replies[:] = [AIMessage(content="Dạ, em ghi nhận ạ.")]
                request = turn(item["text"], session).model_copy(update={
                    "on": date.fromisoformat(call["on"])})
                response = await runtime.run(request)
                state = runtime.state_for(request)
                if item["text"] == case["calls"][0]["turns"][-1]["text"]:
                    final_first_call_context = prompt_context(
                        state, DEFAULT_PROMPT_HISTORY_TURNS)
                actual = {"customer_id": state.get("customer_id"),
                          "profile": memory.profile,
                          "tool_calls": state.get("tool_calls", []),
                          "agent_text": response.agent_text}
                with self.subTest(text=item["text"]):
                    self.assertEqual(check_snapshot(expected, actual), [])
                    self.assertEqual(check_snapshot(item["forbidden"], actual), [])
        self.assertIsNotNone(final_first_call_context)
        scoped_rooms = active_room_constraints(final_first_call_context["customer_facts"])
        self.assertEqual({area for _, area in scoped_rooms}, {12, 45})
        self.assertEqual(len({scope for scope, _ in scoped_rooms}), 2)

    async def test_explicit_correction_supersedes_but_hypothetical_does_not(self):
        case = CASES["correction"]
        first, second, hypothetical = case["calls"][0]["turns"]
        later = case["calls"][1]["turns"][0]
        model = FakeToolModel(replies=[
            AIMessage(content='{"answer":"Dạ.","fact_candidates":'
                              '[{"key":"preferred_color","value":"đen","source":"customer"}]}'),
            AIMessage(content='{"answer":"Dạ, màu trắng ạ.","fact_candidates":'
                              '[{"key":"preferred_color","value":"trắng","source":"customer"}]}'),
            AIMessage(content='{"answer":"Dạ, em giải thích thêm ạ.","fact_candidates":'
                              '[{"key":"preferred_color","value":"xanh","source":"customer"}]}'),
            AIMessage(content="Dạ, em tư vấn tiếp ạ.")])
        memory = FakeMemory()
        runtime = DeepHarnessRuntime(model, FakeGateway(customer_id="C101"), memory)
        session = uuid4()
        for item in (first, second, hypothetical):
            request = turn(item["text"], session)
            await runtime.run(request)
            actual = {"customer_id": runtime.state_for(request).get("customer_id"),
                      "profile": memory.profile,
                      "memory_writes": runtime.state_for(request).get("memory_writes", [])}
            self.assertEqual(check_snapshot(item["expected_after_turn"], actual), [])
            self.assertEqual(check_snapshot(item["forbidden"], actual), [])
        request = turn(later["text"], uuid4())
        await runtime.run(request)
        self.assertEqual(check_snapshot(later["expected_after_turn"],
                                        {"profile": memory.profile}), [])

    async def test_long_episode_keeps_all_four_product_references(self):
        case = CASES["many_products"]
        repo = TurnRepo()
        session_id = str(uuid4())
        for item in case["calls"][0]["turns"]:
            await write(repo, "commit_turn", "C105", session_id, {
                "customer_text": item["text"], "agent_text": "Dạ, em ghi nhận.",
                "on": "2026-10-15", "channel": "hotline",
                "client_msg_id": str(uuid4()), "facts": []})
        summary = repo.episode_summaries[session_id]
        for product in ("Mini", "Pro", "RO9", "DC1"):
            with self.subTest(product=product):
                self.assertIn(product, summary)

    def test_two_quotes_in_one_turn_retain_each_sku(self):
        mock = btc_mock()
        skus = ("SKU-AP-MINI", "SKU-AP-PRO")
        on = "2026-10-15"
        calls = [{"name": "pricing.get_quote", "args": {"sku": sku, "on": on},
                  "result": mock.pricing_get_quote(sku=sku, on=on)} for sku in skus]
        answer = " | ".join(
            f"{sku}: {call['result']['final_price_vnd']:,} đồng"
            for sku, call in zip(skus, calls))
        accepted = accepted_candidates("Cho tôi giá hai mẫu đó.", calls,
                                       reported_tool_candidates(answer, calls), answer)
        remembered_skus = {fact["value"] for fact in accepted
                           if fact["key"] == "product_advised"}
        self.assertEqual(remembered_skus, set(skus))

    def test_one_quote_still_retains_its_sku(self):
        mock = btc_mock()
        sku = "SKU-AP-MINI"
        quote = mock.pricing_get_quote(sku=sku, on="2026-10-15")
        calls = [{"name": "pricing.get_quote",
                  "args": {"sku": sku, "on": "2026-10-15"}, "result": quote}]
        answer = f"{sku}: {quote['final_price_vnd']:,} đồng"
        accepted = accepted_candidates("Giá mẫu Mini?", calls,
                                       reported_tool_candidates(answer, calls), answer)
        self.assertIn(sku, {fact["value"] for fact in accepted
                            if fact["key"] == "product_advised"})

    def test_two_room_constraints_need_separate_scope(self):
        text = "Phòng ngủ 12 m², còn phòng khách 45 m²."
        proposals = [{"key": "room_area_m2", "value": area, "source": "customer"}
                     for area in (12, 45)]
        accepted = accepted_candidates(text, [], proposals)
        self.assertEqual({fact["value"] for fact in accepted
                          if fact["key"] == "room_area_m2"}, {12, 45})

    def test_reported_quote_and_promo_keep_sku_association(self):
        mock = btc_mock()
        skus = ("SKU-AP-MINI", "SKU-AP-PRO")
        calls = [{"name": "pricing.get_quote",
                  "args": {"sku": sku, "on": "2026-10-15"},
                  "result": mock.pricing_get_quote(sku=sku, on="2026-10-15")}
                 for sku in skus]
        answer = " | ".join(
            f"{sku}: {call['result']['final_price_vnd']:,} đồng; "
            + ", ".join(item["promo_code"] for item in call["result"]["applied_promos"])
            for sku, call in zip(skus, calls))
        candidates = reported_tool_candidates(answer, calls)
        actual_quotes = {(item.get("sku"), item["value"]) for item in candidates
                         if item["key"] == "price_quoted_vnd"}
        expected_quotes = {(sku, call["result"]["final_price_vnd"])
                           for sku, call in zip(skus, calls)}
        with self.subTest(kind="quote"):
            self.assertEqual(actual_quotes, expected_quotes)
        with self.subTest(kind="promo"):
            self.assertIn(("SKU-AP-PRO", "AIR-OCT"),
                          {(item.get("sku"), item["value"]) for item in candidates
                           if item["key"] == "promo_code"})

    def test_two_stock_observations_keep_sku_association(self):
        mock = btc_mock()
        skus = ("SKU-AP-MINI", "SKU-AP-X-2024")
        calls = [{"name": "inventory.check",
                  "args": {"sku": sku, "on": "2026-10-15"},
                  "result": mock.inventory_check(sku, "2026-10-15")}
                 for sku in skus]
        self.assertEqual([call["result"]["in_stock"] for call in calls],
                         [True, False])
        candidates = reported_tool_candidates(
            "SKU-AP-MINI còn hàng; SKU-AP-X-2024 hết hàng.", calls)
        self.assertEqual({(item.get("sku"), item["value"]) for item in candidates
                          if item["key"] == "in_stock"},
                         {("SKU-AP-MINI", True), ("SKU-AP-X-2024", False)})
