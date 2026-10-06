"""Behavior checks for the injectable one-turn graph."""

import json
import unittest
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage

from app.agent.guardrails import FALLBACK, check_answer, verified_answer
from app.agent.chat import chat
from fake_memory import InMemoryStore
from app.agent.runtime import HarnessRuntime
from app.agent.state import parse_decision
from app.schemas.agent import ChatRequest, TextTurnRequest


class FakeModel:
    def __init__(self, *decisions):
        self.decisions = list(decisions)
        self.seen = []

    async def ainvoke(self, messages):
        self.seen.append(messages)
        decision = self.decisions.pop(0)
        return AIMessage(content=decision if isinstance(decision, str) else
                         json.dumps(decision, ensure_ascii=False))


class FakeTools:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def invoke(self, name, args):
        self.calls.append((name, args.copy()))
        result = self.results.get((name, args.get("sku")),
                                  self.results.get(name, {"error": "tool_unavailable"}))
        return result.copy()


class EmptyRemoteMemory:
    include_prior = True

    async def read_context(self, _session_id, _customer_id):
        return {"history": [], "profile": {}, "episodes": [], "owned_order_ids": []}

    async def record_turn(self, *_args, **_kwargs):
        return {"turn_no": 1}

    async def write_fact(self, *_args):
        return {"error": "not_used"}


class TurnOnlyMemory(EmptyRemoteMemory):
    async def write_fact(self, *_args):
        raise AssertionError("write_fact must be paused")

    async def record_order(self, *_args):
        raise AssertionError("record_order must be paused")


def harness(llm, tools, memory=None, **kwargs):
    return HarnessRuntime(llm, tools, memory if memory is not None else InMemoryStore(), **kwargs)


def turn(session="22222222-2222-4222-8222-222222222222", **changes):
    data = dict(
        client_msg_id=UUID("11111111-1111-4111-8111-111111111111"),
        session_id=UUID(session), channel="hotline", channel_identity="0984726714",
        on="2026-10-17", text="Máy này còn hàng không?", input_mode="clean",
    )
    return TextTurnRequest.model_validate(data | changes)


class GraphTest(unittest.IsolatedAsyncioTestCase):
    async def test_fenced_inventory_decision_calls_tool_without_model_retry(self):
        fenced = "```json\n" + json.dumps({
            "action": "tool", "response": "", "tool_name": "inventory.check",
            "tool_args": {"sku": "SKU-JK-DWN-M-DEN"}, "memory_writes": [],
        }) + "\n```"
        model = FakeModel(
            {"action": "tool", "tool_name": "catalog.search",
             "tool_args": {"query": "Áo phao lông vũ Warmly"}},
            fenced,
            {"action": "respond", "response": "Dạ, size M màu đen hiện hết hàng ạ."},
        )
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": [{"sku": "SKU-JK-DWN",
                                                          "name": "Áo phao lông vũ Warmly"}],
                                              "total": 1},
                           "inventory.check": {"sku": "SKU-JK-DWN-M-DEN",
                                               "in_stock": False, "qty": 0}})
        with self.assertLogs("app.agent", level="INFO") as captured:
            response = await harness(model, tools).run(
                turn(text="Áo phao lông vũ Warmly size M màu đen còn hàng không?"))
        self.assertEqual(response.agent_text, "Dạ, size M màu đen hiện hết hàng ạ.")
        self.assertEqual(len(model.seen), 3)
        self.assertEqual([name for name, _ in tools.calls].count("inventory.check"), 1)
        logs = "\n".join(captured.output)
        self.assertIn("đã bóc Markdown fence quanh JSON", logs)
        self.assertNotIn("yêu cầu model sửa định dạng JSON", logs)

    async def test_fenced_answer_rewrite_is_accepted(self):
        model = FakeModel(
            {"action": "respond", "response": "Đây là mẫu tốt nhất ạ."},
            "```json\n" + json.dumps({"action": "respond",
                                        "response": "Dạ, em hỗ trợ mình ạ."}) + "\n```",
        )
        tools = FakeTools({"crm.get_customer": {"found": False}})
        with self.assertLogs("app.agent", level="INFO") as captured:
            response = await harness(model, tools).run(turn())
        self.assertEqual(response.agent_text, "Dạ, em hỗ trợ mình ạ.")
        self.assertIn("Kiểm tra câu trả lời: đã bóc Markdown fence quanh JSON",
                      "\n".join(captured.output))

    def test_decision_parser_accepts_only_one_enclosing_json_fence(self):
        payload = json.dumps({
            "action": "respond", "response": "Dạ, em hỗ trợ ạ.",
            "memory_writes": [{"key": "room_area", "value": "25m2", "op": "add"}],
        }, ensure_ascii=False)
        plain, ignored_plain, fenced_plain = parse_decision(payload)
        self.assertEqual(plain.response, "Dạ, em hỗ trợ ạ.")
        self.assertEqual((ignored_plain, fenced_plain), (1, False))
        for opening in ("```json", "```", "```JSON"):
            decision, ignored, fenced = parse_decision(f" \n{opening}\n{payload}\n```\n ")
            self.assertEqual(decision.response, plain.response)
            self.assertEqual((ignored, fenced), (1, True))
        for invalid in (
            f"Lời dẫn\n```json\n{payload}\n```",
            f"```json\n{payload}\n```\nLời kết",
            f"```json\n{payload}\n```\n```json\n{payload}\n```",
            "```json\n{bad json}\n```",
            "```json\n{\"action\": \"unknown\"}\n```",
        ):
            with self.subTest(invalid=invalid[:25]), self.assertRaises(ValueError):
                parse_decision(invalid)

    def test_respond_null_tool_args_is_normalized_but_tool_null_args_is_rejected(self):
        decision, ignored, fenced = parse_decision(json.dumps({
            "action": "respond", "response": "Dạ, giá là 5.490.000đ ạ.",
            "tool_name": None, "tool_args": None, "memory_writes": [],
        }))
        self.assertEqual(decision.tool_args, {})
        self.assertEqual((ignored, fenced), (0, False))
        for action, args in (("tool", None), ("respond", [])):
            with self.subTest(action=action, args=args), self.assertRaises(ValueError):
                parse_decision(json.dumps({"action": action, "tool_name": "catalog.search",
                                           "tool_args": args}))

    async def test_null_tool_args_on_valid_quote_answer_does_not_trigger_fallback(self):
        answer = ("Dạ, máy lọc không khí Xiaomi Smart 4 Pro hiện có giá là "
                  "5.490.000đ và được miễn phí vận chuyển ạ.")
        model = FakeModel(
            {"action": "tool", "tool_name": "catalog.search",
             "tool_args": {"query": "máy lọc không khí xiaomi 4 pro"}},
            {"action": "tool", "tool_name": "pricing.get_quote",
             "tool_args": {"sku": "SKU-XM-4P"}},
            {"action": "respond", "response": answer,
             "tool_name": None, "tool_args": None, "memory_writes": []},
        )
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": [{"sku": "SKU-XM-4P",
                                                          "name": "Máy lọc không khí Xiaomi Smart 4 Pro"}],
                                              "total": 1},
                           "pricing.get_quote": {"sku": "SKU-XM-4P", "list_price_vnd": 5490000,
                                                 "final_price_vnd": 5490000,
                                                 "applied_promos": [{"promo_code": "COD-0",
                                                                     "type": "freecod",
                                                                     "discount_vnd": 0}],
                                                 "freeship": True}})
        response = await harness(model, tools).run(turn(
            on="2026-09-15", text="a lô cho anh hỏi máy lọc không khí xiao mi bốn pờ rô giá bao nhiêu",
            input_mode="chat_teencode"))
        self.assertEqual(response.agent_text, answer)
        self.assertEqual(len(model.seen), 3)

    async def test_broad_promo_question_quotes_every_catalog_sku_on_business_day(self):
        items = [{"sku": f"SKU-AP-{index}", "name": f"Máy lọc mẫu {index}"}
                 for index in range(7)]
        results = {"crm.get_customer": {"found": False},
                   "catalog.search": {"items": items, "total": 7}}
        for index, item in enumerate(items):
            discount = 500000 if index == 0 else 0
            results[("pricing.get_quote", item["sku"])] = {
                "sku": item["sku"], "list_price_vnd": 4890000,
                "final_price_vnd": 4890000 - discount,
                "applied_promos": ([{"promo_code": "AP-SEP", "type": "fixed",
                                     "discount_vnd": discount}] if discount else []),
                "freeship": False,
            }
        model = FakeModel({"action": "tool", "tool_name": "catalog.search",
                           "tool_args": {"query": "máy lọc không khí"}})
        tools = FakeTools(results)
        response = await harness(model, tools, max_tool_calls=3).run(turn(
            on="2026-09-15", text="máy lọc không khí có loại nào đang khuyến mãi không em?"))
        quotes = [(name, args) for name, args in tools.calls if name == "pricing.get_quote"]
        self.assertEqual([args["sku"] for _, args in quotes], [item["sku"] for item in items])
        self.assertTrue(all(args["on"] == "2026-09-15" for _, args in quotes))
        self.assertIn("7/7 mẫu", response.agent_text)
        self.assertIn("Máy lọc mẫu 0: giảm 500.000đ, còn 4.390.000đ", response.agent_text)
        self.assertNotIn("Máy lọc mẫu 1: giảm", response.agent_text)
        self.assertEqual(len(model.seen), 1)

    async def test_broad_promo_question_forces_catalog_when_model_answers_early(self):
        model = FakeModel({"action": "respond", "response": "Em chưa có thông tin ạ."},
                          {"action": "respond", "response": "Dạ, em chưa tìm thấy mẫu phù hợp ạ."})
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": [], "total": 0}})
        response = await harness(model, tools).run(turn(
            text="máy lọc không khí có loại nào đang khuyến mãi không em?"))
        self.assertEqual(tools.calls[1],
                         ("catalog.search", {"query": "máy lọc không khí"}))
        self.assertIn("chưa tìm thấy mẫu", response.agent_text)

    async def test_broad_quote_reply_reports_unverified_items_and_separates_gifts(self):
        items = [{"sku": "SKU-AP-X", "name": "AirPure X"},
                 {"sku": "SKU-AP-Y", "name": "AirPure Y"}]
        results = {"crm.get_customer": {"found": False},
                   "catalog.search": {"items": items, "total": 21},
                   ("pricing.get_quote", "SKU-AP-X"): {
                       "sku": "SKU-AP-X", "list_price_vnd": 4890000,
                       "final_price_vnd": 4890000,
                       "applied_promos": [{"promo_code": "GIFT-FILTER", "type": "gift",
                                           "discount_vnd": 0}], "freeship": True},
                   ("pricing.get_quote", "SKU-AP-Y"): {"error": "tool_error"}}
        model = FakeModel({"action": "tool", "tool_name": "catalog.search",
                           "tool_args": {"query": "máy lọc không khí"}})
        response = await harness(model, FakeTools(results)).run(turn(
            text="máy lọc không khí có loại nào đang khuyến mãi không em?"))
        self.assertIn("1/21 mẫu", response.agent_text)
        self.assertIn("Có quà tặng: AirPure X", response.agent_text)
        self.assertIn("chưa xác minh được các mẫu còn lại", response.agent_text)
        self.assertNotIn("AirPure Y", response.agent_text)

    async def test_broad_quote_sweep_stops_at_catalog_limit(self):
        items = [{"sku": f"SKU-AP-{index}", "name": f"Máy {index}"}
                 for index in range(21)]
        results = {"crm.get_customer": {"found": False},
                   "catalog.search": {"items": items, "total": 21}}
        for item in items:
            results[("pricing.get_quote", item["sku"])] = {
                "sku": item["sku"], "list_price_vnd": 4890000,
                "final_price_vnd": 4890000, "applied_promos": [], "freeship": False}
        tools = FakeTools(results)
        model = FakeModel({"action": "tool", "tool_name": "catalog.search",
                           "tool_args": {"query": "máy lọc"}})
        response = await harness(model, tools).run(turn(
            text="máy lọc có loại nào đang khuyến mãi không?"))
        self.assertEqual(len([name for name, _ in tools.calls
                              if name == "pricing.get_quote"]), 20)
        self.assertIn("20/21 mẫu", response.agent_text)
        self.assertIn("chưa xác minh được các mẫu còn lại", response.agent_text)

    async def test_broad_price_question_uses_final_quote_not_catalog_list_price(self):
        items = [{"sku": "SKU-AP-X", "name": "AirPure X", "list_price_vnd": 4890000},
                 {"sku": "SKU-AP-Y", "name": "AirPure Y", "list_price_vnd": 5200000}]
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": items, "total": 2},
                           ("pricing.get_quote", "SKU-AP-X"): {
                               "sku": "SKU-AP-X", "final_price_vnd": 4390000},
                           ("pricing.get_quote", "SKU-AP-Y"): {
                               "sku": "SKU-AP-Y", "final_price_vnd": 5200000}})
        model = FakeModel({"action": "tool", "tool_name": "catalog.search",
                           "tool_args": {"query": "máy lọc không khí"}})
        response = await harness(model, tools).run(turn(
            text="giá các mẫu máy lọc không khí bao nhiêu?"))
        self.assertIn("AirPure X: 4.390.000đ", response.agent_text)
        self.assertIn("AirPure Y: 5.200.000đ", response.agent_text)
        self.assertNotIn("4.890.000đ", response.agent_text)
        self.assertEqual([name for name, _ in tools.calls].count("pricing.get_quote"), 2)

    async def test_single_product_price_response_forces_quote_before_answer(self):
        answer = "Máy lọc không khí Xiaomi Smart 4 Pro giá 5.490.000đ ạ."
        model = FakeModel(
            {"action": "tool", "tool_name": "catalog.search",
             "tool_args": {"query": "Xiaomi Smart 4 Pro"}},
            {"action": "respond", "response": answer},
            {"action": "respond", "response": answer},
        )
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": [{"sku": "SKU-XM-4P",
                                                          "name": "Máy lọc không khí Xiaomi Smart 4 Pro"}],
                                              "total": 1},
                           "pricing.get_quote": {"sku": "SKU-XM-4P", "final_price_vnd": 5490000,
                                                 "applied_promos": [], "freeship": False}})
        response = await harness(model, tools).run(turn(text="Xiaomi Smart 4 Pro giá bao nhiêu?"))
        self.assertEqual(response.agent_text, answer)
        self.assertEqual([name for name, _ in tools.calls].count("pricing.get_quote"), 1)

    async def test_price_question_ignores_accessory_result_when_quoting_machine(self):
        answer = "Máy lọc không khí AirPure X giá 4.390.000đ ạ."
        model = FakeModel(
            {"action": "tool", "tool_name": "catalog.search",
             "tool_args": {"query": "AirPure X"}},
            {"action": "respond", "response": answer},
            {"action": "respond", "response": answer},
        )
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": [
                               {"sku": "SKU-AP-X", "name": "Máy lọc không khí AirPure X",
                                "category": "gia-dung/may-loc-khong-khi"},
                               {"sku": "SKU-AP-FLT-X", "name": "Màng lọc thay thế AirPure X/Y",
                                "category": "gia-dung/phu-kien"}], "total": 2},
                           ("pricing.get_quote", "SKU-AP-X"): {
                               "sku": "SKU-AP-X", "final_price_vnd": 4390000},
                           ("pricing.get_quote", "SKU-AP-FLT-X"): {
                               "sku": "SKU-AP-FLT-X", "final_price_vnd": 690000}})
        response = await harness(model, tools).run(turn(
            on="2026-09-15", text="Máy AirPure X giá bao nhiêu?"))
        self.assertIn("AirPure X: 4.390.000đ", response.agent_text)
        self.assertEqual([args["sku"] for name, args in tools.calls
                          if name == "pricing.get_quote"], ["SKU-AP-X", "SKU-AP-FLT-X"])

    async def test_catalog_advice_is_rewritten_after_unsupported_claim(self):
        customer = "Nhà chị có bé nhỏ, ngân sách tầm 5 triệu thôi em. tư vấn máy lọc không khí"
        unsafe = ("Dạ, với nhu cầu của chị, AirPure X phù hợp nhất vì có HEPA H13 "
                  "và cảm biến PM2.5 ạ.")
        safe = ("Dạ, em tìm thấy Máy lọc không khí AirPure X "
                "và Máy lọc không khí Xiaomi Smart 4 Lite. Phòng chị rộng bao nhiêu m2 ạ?")
        model = FakeModel(
            {"action": "tool", "tool_name": "catalog.search",
             "tool_args": {"query": "máy lọc không khí", "max_price_vnd": 5000000}},
            {"action": "respond", "response": unsafe},
            {"action": "respond", "response": safe},
        )
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": [
                               {"sku": "SKU-AP-X", "name": "Máy lọc không khí AirPure X",
                                "attributes": {"room_area_m2": 25}},
                               {"sku": "SKU-XM-4L",
                                "name": "Máy lọc không khí Xiaomi Smart 4 Lite",
                                "attributes": {"room_area_m2": 43}}], "total": 2}})
        with self.assertLogs("app.agent", level="INFO") as captured:
            response = await harness(model, tools).run(turn(text=customer))
        self.assertEqual(response.agent_text, safe)
        self.assertEqual(len(model.seen), 3)
        self.assertEqual([name for name, _ in tools.calls].count("catalog.search"), 1)
        logs = "\n".join(captured.output)
        self.assertIn("so sánh mức phù hợp chưa có nguồn", logs)
        self.assertIn("yêu cầu viết lại câu trả lời", logs)
        self.assertIn("kết quả viết lại | câu trả lời: đạt", logs)

    async def test_catalog_advice_uses_grounded_reply_when_rewrite_fails(self):
        model = FakeModel(
            {"action": "tool", "tool_name": "catalog.search",
             "tool_args": {"query": "máy lọc không khí"}},
            {"action": "respond", "response": "AirPure X có HEPA H13 ạ."},
            {"action": "respond", "response": "AirPure X tốt nhất ạ."},
        )
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": [{"sku": "SKU-AP-X",
                                                          "name": "Máy lọc không khí AirPure X",
                                                          "attributes": {"room_area_m2": 25}}],
                                              "total": 1}})
        response = await harness(model, tools).run(turn(text="Tư vấn máy lọc không khí cho nhà chị"))
        self.assertIn("Máy lọc không khí AirPure X", response.agent_text)
        self.assertIn("diện tích phòng", response.agent_text)
        self.assertNotIn("HEPA", response.agent_text)

    async def test_empty_catalog_keeps_existing_fallback_after_bad_rewrite(self):
        model = FakeModel(
            {"action": "tool", "tool_name": "catalog.search",
             "tool_args": {"query": "máy lọc không khí"}},
            {"action": "respond", "response": "AirPure X có HEPA H13 ạ."},
            {"action": "respond", "response": "AirPure X tốt nhất ạ."},
        )
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": [], "total": 0}})
        response = await harness(model, tools).run(turn(text="Tư vấn máy lọc không khí cho nhà chị"))
        self.assertEqual(response.agent_text, FALLBACK)

    def test_customer_budget_is_distinct_from_product_price(self):
        customer = "Nhà chị có bé nhỏ, ngân sách tầm 5 triệu thôi em."
        catalog = [{"name": "catalog.search", "args": {"max_price_vnd": 5000000},
                    "result": {"items": [{"sku": "SKU-AP-X", "name": "AirPure X",
                                          "list_price_vnd": 4890000}]}}]
        answer = "Dạ, với ngân sách 5 triệu, em tìm thấy AirPure X ạ."
        self.assertEqual(check_answer(answer, catalog, customer)[1], "price_without_quote")
        self.assertEqual(check_answer(answer, catalog, "Ngân sách 4 triệu")[1],
                         "price_without_quote")
        self.assertEqual(check_answer("Giá AirPure X là 5 triệu ạ.", catalog, customer)[1],
                         "price_without_quote")
        self.assertEqual(check_answer("Giá AirPure X là 4.890.000đ ạ.", catalog, customer)[1],
                         "price_without_quote")
        quote = {"name": "pricing.get_quote", "args": {"sku": "SKU-AP-X", "on": "2026-10-15"},
                 "result": {"sku": "SKU-AP-X", "final_price_vnd": 4890000}}
        mixed = "Với ngân sách 5 triệu, AirPure X có giá 4.890.000đ ạ."
        self.assertEqual(check_answer(mixed, [*catalog, quote], customer)[1],
                         "price_without_quote")
        price_only = "AirPure X có giá 4.890.000đ ạ."
        self.assertEqual(check_answer(price_only, [*catalog, quote], customer), (price_only, None))

    def test_customer_reported_competitor_price_is_not_our_quote(self):
        customer = "Bên kia chị thấy đang bán 4590k thôi, sao bên em đắt hơn?"
        quote = {"name": "pricing.get_quote", "args": {"sku": "SKU-AP-X", "on": "2026-10-15"},
                 "result": {"sku": "SKU-AP-X", "final_price_vnd": 4890000,
                            "applied_promos": [], "freeship": True}}
        answer = "Dạ, chị thấy bên kia bán 4.590.000đ; AirPure X bên em giá 4.890.000đ ạ."
        self.assertEqual(check_answer(answer, [quote], customer)[1], "price_without_quote")
        self.assertEqual(check_answer(answer, [], customer)[1], "price_without_quote")
        own_price_only = "Dạ, em đã ghi nhận giá bên kia chị báo; AirPure X bên em giá 4.890.000đ ạ."
        self.assertEqual(check_answer(own_price_only, [quote], customer), (own_price_only, None))
        invented = "Dạ, bên kia bán 4.500.000đ; AirPure X bên em giá 4.890.000đ ạ."
        self.assertEqual(check_answer(invented, [quote], customer)[1],
                         "price_without_quote")

    async def test_competitor_objection_without_product_does_not_search_sentence(self):
        model = FakeModel({"action": "respond",
                           "response": "Dạ, chị đang so giá mẫu nào để em kiểm tra báo giá ạ?"})
        tools = FakeTools({"crm.get_customer": {"found": False}})
        response = await harness(model, tools).run(turn(
            text="Bên kia chị thấy đang bán 4590k thôi, sao bên em đắt hơn?"))
        self.assertIn("mẫu nào", response.agent_text)
        self.assertEqual([name for name, _ in tools.calls], ["crm.get_customer"])

    def test_discount_amount_is_checked_separately_from_sale_price(self):
        quote = {"name": "pricing.get_quote", "args": {"sku": "SKU-AP-X", "on": "2026-10-15"},
                 "result": {"sku": "SKU-AP-X", "list_price_vnd": 4890000,
                            "final_price_vnd": 4890000,
                            "applied_promos": [{"promo_code": "GIFT-FILTER", "type": "gift",
                                                "discount_vnd": 0}], "freeship": True}}
        customer = "Em ơi AirPure X đang giảm 500k đúng không?"
        answer = "Dạ, AirPure X hiện có giá 4.890.000đ, không giảm giá bằng tiền ạ."
        self.assertEqual(check_answer(answer, [quote], customer), (answer, None))
        for answer, reason in (
            ("AirPure X giá 4.390.000đ, không giảm 500k ạ.", "price_without_quote"),
            ("AirPure X giá 4390000, không giảm 500k ạ.", "price_without_quote"),
            ("AirPure X giá 4.890.000đ, đang giảm 500k ạ.", "price_without_quote"),
            ("AirPure X giá 4.890.000đ, không giảm 300k ạ.", "price_without_quote"),
            ("AirPure X giảm giá còn 4.890.000đ, không giảm 500k ạ.", "price_without_quote"),
        ):
            with self.subTest(answer=answer):
                self.assertEqual(check_answer(answer, [quote], customer)[1], reason)
        self.assertEqual(check_answer("AirPure X không giảm 500k ạ.", [], customer)[1],
                         "price_without_quote")
        no_promo = {**quote, "result": {**quote["result"], "applied_promos": []}}
        self.assertEqual(check_answer("AirPure X không giảm 500k ạ.", [no_promo], customer)[1],
                         "price_without_quote")
        wrong_sku = "SKU-AP-Y giá 4.890.000đ, không giảm 500k ạ."
        self.assertEqual(check_answer(wrong_sku, [quote], customer)[1], "price_without_quote")

        discounted = {**quote, "result": {**quote["result"], "final_price_vnd": 4390000,
                                          "applied_promos": [{"promo_code": "AP-SEP",
                                                              "type": "fixed", "discount_vnd": 500000}]}}
        self.assertEqual(check_answer("AirPure X giá 4.390.000đ, giảm 500k ạ.",
                                      [discounted], customer)[1], None)
        self.assertEqual(check_answer("AirPure X giá 4.390.000đ, không giảm 500k ạ.",
                                      [discounted], customer)[1], "price_without_quote")

    async def test_discount_question_returns_verified_answer_instead_of_fallback(self):
        answer = "Dạ, AirPure X có giá 4.890.000đ, hiện không giảm giá bằng tiền ạ."
        model = FakeModel(
            {"action": "tool", "tool_name": "catalog.search", "tool_args": {"query": "AirPure X"}},
            {"action": "tool", "tool_name": "pricing.get_quote", "tool_args": {"sku": "SKU-AP-X"}},
            {"action": "respond", "response": answer},
        )
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": [{"sku": "SKU-AP-X", "name": "AirPure X"}],
                                              "total": 1},
                           "pricing.get_quote": {"sku": "SKU-AP-X", "list_price_vnd": 4890000,
                                                 "final_price_vnd": 4890000,
                                                 "applied_promos": [{"promo_code": "GIFT-FILTER",
                                                                     "type": "gift", "discount_vnd": 0}],
                                                 "freeship": True}})
        response = await harness(model, tools).run(turn(
            on="2026-10-15", text="Em ơi AirPure X đang giảm 500k đúng không?"))
        self.assertEqual(response.agent_text, answer)
        self.assertFalse(response.needs_handoff)

    def test_product_specs_and_superlatives_need_evidence(self):
        item = {"sku": "SKU-AP-X", "name": "Máy lọc không khí AirPure X",
                "attributes": {"room_area_m2": 25}}
        call = {"name": "catalog.search", "args": {"query": "máy lọc không khí"},
                "result": {"items": [item]}}
        self.assertEqual(check_answer("Máy lọc không khí AirPure X có HEPA H13 ạ.", [call])[1],
                         "unsupported_product_spec")
        self.assertEqual(check_answer("Máy lọc không khí AirPure X có cảm biến PM2.5 ạ.", [call])[1],
                         "unsupported_product_spec")
        self.assertEqual(check_answer("AirPure X phù hợp nhất ạ.", [call])[1],
                         "unsupported_comparison")
        evidenced = {**call, "result": {"items": [{**item, "attributes": {
            "room_area_m2": 25, "filter": "HEPA H13", "sensor": "PM2.5"}}]}}
        spec = "Máy lọc không khí AirPure X có HEPA H13 và cảm biến PM2.5 ạ."
        self.assertEqual(check_answer(spec, [evidenced]), (spec, None))
        short_name = "AirPure X có HEPA H13 ạ."
        self.assertEqual(check_answer(short_name, [evidenced]), (short_name, None))

    async def test_invalid_memory_proposals_do_not_discard_valid_answer(self):
        response_text = "Dạ, phòng 25m2 có AirPure X và Xiaomi Smart 4 Lite ạ."
        model = FakeModel(
            {"action": "tool", "tool_name": "catalog.search",
             "tool_args": {"query": "máy lọc không khí", "min_room_area_m2": 25}},
            {"action": "respond", "response": response_text,
             "memory_writes": [
                 {"key": "room_area", "value": "25m2", "op": "add"},
                 {"key": "interest_product_category", "value": "máy lọc không khí", "op": "add"},
             ]},
        )
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": [
                               {"sku": "SKU-AP-X", "name": "AirPure X",
                                "attributes": {"room_area_m2": 25}},
                               {"sku": "SKU-XM-4L", "name": "Xiaomi Smart 4 Lite",
                                "attributes": {"room_area_m2": 43}}], "total": 2}})
        with self.assertLogs("app.agent", level="INFO") as captured:
            result = await harness(model, tools, TurnOnlyMemory()).run(
                turn(text="Máy lọc không khí cho phòng 25m2"))
        self.assertEqual(result.agent_text, response_text)
        self.assertEqual(len(model.seen), 2)
        self.assertIn("bỏ qua đề xuất ghi bộ nhớ", "\n".join(captured.output))
        self.assertIn("đã lưu lượt chat", "\n".join(captured.output))

    async def test_created_order_does_not_write_fact_or_order_memory(self):
        model = FakeModel(
            {"action": "tool", "tool_name": "inventory.check",
             "tool_args": {"sku": "SKU-AP-X"}},
            {"action": "tool", "tool_name": "pricing.get_quote",
             "tool_args": {"sku": "SKU-AP-X"}},
            {"action": "tool", "tool_name": "order.create",
             "tool_args": {"sku": "SKU-AP-X", "qty": 1,
                           "price_vnd": 4890000, "payment": "COD"}},
            {"action": "respond", "response": "Dạ, em đã tạo đơn ạ."},
        )
        tools = FakeTools({
            "crm.get_customer": {"found": True, "customer_id": "C001",
                                 "phone": "0984726714"},
            "inventory.check": {"sku": "SKU-AP-X", "in_stock": True, "qty": 3},
            "pricing.get_quote": {"sku": "SKU-AP-X", "final_price_vnd": 4890000},
            "order.create": {"status": "created", "order_id": "OD-NEW"},
        })
        result = await harness(model, tools, TurnOnlyMemory()).run(turn())
        self.assertEqual(result.agent_text, "Dạ, em đã tạo đơn ạ.")
        self.assertEqual([name for name, _ in tools.calls].count("order.create"), 1)

    async def test_invalid_model_json_gets_one_repair_attempt_after_quote(self):
        model = FakeModel(
            {"action": "tool", "tool_name": "pricing.get_quote",
             "tool_args": {"sku": "SKU-AP-X"}},
            '{"action":"respond","response":"Giá 4.890.000đ ạ, chị Hoa 0984726714"',
            {"action": "respond", "response": "Giá 4.890.000đ ạ."},
        )
        tools = FakeTools({"crm.get_customer": {"found": True, "customer_id": "C001",
                                               "phone": "0984726714", "name": "Hoa"},
                           "pricing.get_quote": {"sku": "SKU-AP-X",
                                                 "final_price_vnd": 4890000}})
        with self.assertLogs("app.agent", level="INFO") as captured:
            response = await harness(model, tools).run(turn())
        self.assertEqual(response.agent_text, "Giá 4.890.000đ ạ.")
        self.assertEqual([name for name, _ in tools.calls].count("pricing.get_quote"), 1)
        self.assertEqual(len(model.seen), 3)
        self.assertIn("sai định dạng", model.seen[-1][0].content)
        self.assertIn("phản hồi JSON không hợp lệ", "\n".join(captured.output))
        self.assertIn("Giá 4.890.000đ", "\n".join(captured.output))
        self.assertNotIn("0984726714", "\n".join(captured.output))
        self.assertNotIn("chị Hoa", "\n".join(captured.output))

    async def test_search_question_is_reduced_to_product_terms_then_quote_uses_unique_sku(self):
        model = FakeModel(
            {"action": "tool", "tool_name": "catalog.search",
             "tool_args": {"query": "giá của Giày trekking HikePro bao nhiêu tiền vậy?"}},
            {"action": "tool", "tool_name": "pricing.get_quote",
             "tool_args": {"query": "Giày trekking HikePro"}},
            {"action": "respond", "response": "Giá giày là 1.990.000đ ạ."},
        )
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": [{"sku": "SKU-SN-TRK"}], "total": 1},
                           "pricing.get_quote": {"sku": "SKU-SN-TRK",
                                                 "final_price_vnd": 1990000}})
        response = await harness(model, tools).run(turn())
        self.assertEqual(response.agent_text, "Giá giày là 1.990.000đ ạ.")
        self.assertEqual(tools.calls[1], ("catalog.search", {"query": "Giày trekking HikePro"}))
        self.assertEqual(tools.calls[2], ("pricing.get_quote",
                                          {"sku": "SKU-SN-TRK", "on": "2026-10-17"}))

    def test_shorthand_price_requires_matching_quote(self):
        quote = [{"name": "pricing.get_quote", "args": {"sku": "SKU-AP-X", "on": "2026-10-15"},
                  "result": {"sku": "SKU-AP-X", "final_price_vnd": 4890000}}]
        self.assertEqual(verified_answer("Giá 4tr890 ạ.", quote), "Giá 4tr890 ạ.")
        self.assertEqual(verified_answer("Giá 4tr890 ạ.", [
            {**quote[0], "result": {"sku": "SKU-AP-X", "final_price_vnd": 4800000}}]), FALLBACK)

    async def test_model_and_tool_outputs_log_with_private_fields_hidden(self):
        model = FakeModel(
            {"action": "tool", "tool_name": "inventory.check",
             "tool_args": {"sku": "SKU-AP-Y", "customer_phone": "0984726714"}},
            {"action": "respond", "response": "Dạ Hoa, sản phẩm còn hàng ạ.",
             "memory_writes": [{"key": "special_note", "value": "hoa@example.com"}]},
        )
        tools = FakeTools({
            "crm.get_customer": {"found": True, "customer_id": "C001",
                                 "phone": "0984726714", "name": "Hoa"},
            "inventory.check": {"sku": "SKU-AP-Y", "in_stock": True, "qty": 3,
                                "customer_phone": "0984726714", "secret_token": "private-token"},
        })
        request = turn(text="Tôi là Hoa, số 0984726714")
        with self.assertLogs("app.agent", level="INFO") as captured:
            await harness(model, tools).run(request)
        detail = "\n".join(captured.output)
        self.assertIn("model trả về", detail)
        self.assertIn("gửi vào công cụ", detail)
        self.assertIn('"response": "Dạ [TÊN ĐÃ ẨN], sản phẩm còn hàng ạ."', detail)
        self.assertIn('"tool": "inventory.check"', detail)
        self.assertIn('"qty": 3', detail)
        self.assertIn('"orders_count": 0', detail)
        for secret in ("0984726714", "Hoa", "hoa@example.com", "private-token",
                       "C001", str(request.session_id), str(request.client_msg_id)):
            self.assertNotIn(secret, detail)

    async def test_agent_logs_steps_and_tool_without_customer_content(self):
        model = FakeModel(
            {"action": "tool", "tool_name": "inventory.check",
             "tool_args": {"sku": "SKU-AP-Y"}},
            {"action": "respond", "response": "Dạ, sản phẩm còn hàng ạ."},
        )
        tools = FakeTools({
            "crm.get_customer": {"found": True, "customer_id": "C001",
                                 "phone": "0984726714", "name": "Hoa"},
            "inventory.check": {"sku": "SKU-AP-Y", "in_stock": True, "qty": 3},
        })
        runtime = harness(model, tools)
        request = turn(text="Tên tôi là Hoa, SĐT 0984726714; hỏi SKU-AP-Y")
        with self.assertLogs("app.agent", level="INFO") as captured:
            await runtime.run(request)
            await runtime.run(request)
        completed = [line.split(": hoàn tất", 1)[0].split("app.agent:", 1)[1]
                     for line in captured.output if ": hoàn tất" in line]
        self.assertEqual(completed, ["Nhận yêu cầu", "Xác định khách hàng", "Đọc ngữ cảnh",
                                     "Quyết định bước tiếp", "Gọi công cụ",
                                     "Quyết định bước tiếp", "Kiểm tra câu trả lời",
                                     "Lưu bộ nhớ", "Lượt chat"])
        self.assertTrue(any("Lượt chat: trả kết quả đã xử lý" in line
                            for line in captured.output))
        self.assertTrue(any("Gọi công cụ: kết quả công cụ" in line and
                            "inventory.check" in line and "thành công" in line
                            for line in captured.output))
        log_text = "\n".join(captured.output)
        self.assertIn("SKU-AP-Y", log_text)
        for secret in ("0984726714", "Hoa", "C001", "SĐT",
                       str(request.session_id), str(request.client_msg_id)):
            self.assertNotIn(secret, log_text)

    async def test_chat_function_creates_and_reuses_session(self):
        model = FakeModel(*([{"action": "respond", "response": "Dạ, em hỗ trợ mình ạ."}] * 3))
        tools = FakeTools({"crm.get_customer": {"found": False}})
        runtime = harness(model, tools)
        first_request = ChatRequest(client_msg_id=uuid4(), session_id=None,
            channel="chat_fanpage", channel_identity="fb.new", on="2026-10-15",
            text="Chào shop", input_mode="clean")
        first = await chat(first_request, runtime=runtime)
        second_request = first_request.model_copy(update={"client_msg_id": uuid4(),
                                                    "session_id": first.session_id,
                                                    "text": "Tôi muốn hỏi tiếp"})
        second = await chat(second_request, runtime=runtime)
        repeated = await chat(second_request, runtime=runtime)
        another = await chat(first_request.model_copy(update={"client_msg_id": uuid4()}),
                             runtime=runtime)
        self.assertEqual(second, repeated)
        self.assertEqual(first.session_id, second.session_id)
        self.assertNotEqual(first.session_id, another.session_id)
        self.assertEqual(json.loads(model.seen[1][1].content)["session_history"],
                         [{"customer": "Chào shop", "agent": "Dạ, em hỗ trợ mình ạ."}])
        self.assertEqual(json.loads(model.seen[2][1].content)["session_history"], [])
        self.assertEqual(len(model.seen), 3)

    async def test_prompt_receives_only_recent_turns(self):
        class LongHistoryMemory(EmptyRemoteMemory):
            async def read_context(self, _session_id, _customer_id):
                return {"history": [{"customer": f"c{i}", "agent": f"a{i}"}
                                    for i in range(5)],
                        "profile": {}, "episodes": [], "owned_order_ids": []}

        model = FakeModel({"action": "respond", "response": "Dạ, em tiếp tục hỗ trợ ạ."})
        tools = FakeTools({"crm.get_customer": {"found": False}})
        await harness(model, tools, LongHistoryMemory(),
                             prompt_history_turns=2).run(turn())
        context = json.loads(model.seen[0][1].content)
        self.assertEqual([item["customer"] for item in context["session_history"]],
                         ["c3", "c4"])

    async def test_configured_tool_budget_allows_four_tool_observations(self):
        model = FakeModel(*([{"action": "tool", "tool_name": "catalog.search",
                            "tool_args": {"query": "máy lọc"}}] * 4),
                          {"action": "respond", "response": "Dạ, em đã kiểm tra sản phẩm ạ."})
        tools = FakeTools({"crm.get_customer": {"found": False},
                           "catalog.search": {"items": []}})
        response = await harness(model, tools, max_tool_calls=4).run(turn())
        self.assertEqual(response.agent_text, "Dạ, em đã kiểm tra sản phẩm ạ.")
        self.assertEqual([name for name, _ in tools.calls].count("catalog.search"), 4)

    async def test_seed_crm_session_builds_returning_call_brief(self):
        model = FakeModel({"action": "respond", "response": "Dạ, mình muốn tiếp tục phần đã trao đổi ạ."})
        tools = FakeTools({"crm.get_customer": {"found": True, "customer_id": "C034",
            "phone": "0984726714", "name": "Loan", "honorific": "cô",
            "sessions": [{"session_id": "S-OLD-3", "date": "2026-10-09",
                          "channel": "hotline", "summary": "Đã hỏi máy lọc nước",
                          "outcome": "hen_goi_lai"}]}})
        response = await harness(model, tools, EmptyRemoteMemory()).run(turn())
        self.assertTrue(response.call_brief["is_returning"])
        self.assertEqual(response.call_brief["last_session"]["session_id"], "S-OLD-3")
        self.assertIn("Call Brief", model.seen[0][0].content)

    async def test_identity_context_tool_day_memory_and_duplicate_request(self):
        memory = InMemoryStore()
        memory.seed_fact("C001", "room_area_m2", 25, "set", "previous-session#turn2")
        model = FakeModel(
            {"action": "tool", "tool_name": "inventory.check", "tool_args": {"sku": "SKU-AP-Y"}},
            {"action": "respond", "response": "Dạ, sản phẩm còn hàng ạ.",
             "memory_writes": [{"key": "product_advised", "value": "SKU-AP-Y", "op": "set"}]},
        )
        tools = FakeTools({
            "crm.get_customer": {"found": True, "ambiguous": False, "customer_id": "C001", "phone": "0984726714"},
            "inventory.check": {"sku": "SKU-AP-Y", "in_stock": True, "qty": 3},
        })
        runtime = harness(model, tools, memory)
        request = turn()
        first = await runtime.run(request)
        second = await runtime.run(request)

        self.assertEqual(first, second)
        self.assertEqual(first.agent_text, "Dạ, sản phẩm còn hàng ạ.")
        self.assertEqual(tools.calls[0], ("crm.get_customer", {"phone": "0984726714"}))
        self.assertEqual(tools.calls[1][1], {"sku": "SKU-AP-Y", "on": "2026-10-17"})
        self.assertIn("room_area_m2", model.seen[0][1].content)
        self.assertIn("SKU-AP-Y", model.seen[1][1].content)
        self.assertNotIn("product_advised", memory.profile("C001"))
        self.assertEqual(len(memory.sessions[str(request.session_id)]), 1)

    async def test_ambiguous_identity_cannot_read_or_write_profile(self):
        memory = InMemoryStore()
        memory.seed_fact("C034", "budget_vnd", 1000000, "set", "old#turn1")
        model = FakeModel({"action": "respond", "response": "Dạ, em cần xác nhận thông tin ạ.",
                           "memory_writes": [{"key": "product_advised", "value": "SKU-AP-Y"}]})
        tools = FakeTools({"crm.get_customer": {"found": True, "ambiguous": True,
                                                  "candidates": [{"customer_id": "C034"}, {"customer_id": "C035"}]}})
        response = await harness(model, tools, memory).run(turn(channel_identity="0958421083"))
        self.assertIn("xác nhận", response.agent_text)
        self.assertNotIn("budget_vnd", model.seen[0][1].content)
        self.assertNotIn("product_advised", memory.profile("C034"))

    async def test_unavailable_tool_and_unsupported_claim_fall_back(self):
        model = FakeModel({"action": "tool", "tool_name": "pricing.get_quote",
                           "tool_args": {"sku": "SKU-AP-Y"}})
        tools = FakeTools({"crm.get_customer": {"found": False}})
        response = await harness(model, tools).run(turn(channel="chat_fanpage", channel_identity="fb.unknown"))
        self.assertEqual(response.agent_text, FALLBACK)
        self.assertTrue(response.needs_handoff)
        self.assertEqual(tools.calls[1], ("pricing.get_quote", {"sku": "SKU-AP-Y", "on": "2026-10-17"}))

        model2 = FakeModel({"action": "respond", "response": "Giá là 5.200.000đ ạ."})
        response2 = await harness(model2, tools).run(turn())
        self.assertIn("mẫu cần kiểm tra giá", response2.agent_text)

    async def test_model_input_masks_phone_and_keeps_prior_profile_unchanged(self):
        memory = InMemoryStore()
        memory.seed_fact("C001", "budget_vnd", 5000000, "set", "old#turn1")
        model = FakeModel({"action": "respond", "response": "Dạ em đã ghi nhận ạ.",
                           "memory_writes": [{"key": "budget_vnd", "value": 5700000, "op": "supersede"}]})
        tools = FakeTools({"crm.get_customer": {"found": True, "customer_id": "C001", "phone": "0984726714"}})
        await harness(model, tools, memory).run(turn(text="SĐT tôi 0984726714, ngân sách 5,7 triệu"))
        self.assertNotIn("0984726714", model.seen[0][1].content)
        self.assertEqual(memory.profile("C001")["budget_vnd"]["value"], 5000000)
        self.assertEqual(memory.fact_history["C001"][0]["status"], "active")

    async def test_new_customer_can_get_basic_quote_without_phone(self):
        model = FakeModel(
            {"action": "tool", "tool_name": "pricing.get_quote",
             "tool_args": {"sku": "SKU-AP-Y", "customer_phone": "0999999999"}},
            {"action": "respond", "response": "Dạ, giá là 5.200.000đ ạ."},
        )
        tools = FakeTools({
            "crm.get_customer": {"found": False},
            "pricing.get_quote": {"sku": "SKU-AP-Y", "final_price_vnd": 5200000},
        })
        response = await harness(model, tools).run(turn(channel="chat_fanpage", channel_identity="fb.new"))
        self.assertEqual(response.agent_text, "Dạ, giá là 5.200.000đ ạ.")
        self.assertNotIn("customer_phone", tools.calls[1][1])

    async def test_other_customer_order_id_is_blocked_before_tool_call(self):
        model = FakeModel({"action": "tool", "tool_name": "order.update",
                           "tool_args": {"order_id": "OD-OTHER", "action": "return"}})
        tools = FakeTools({
            "crm.get_customer": {"found": True, "customer_id": "C001", "phone": "0984726714",
                                 "orders": [{"order_id": "OD-MINE"}]},
        })
        response = await harness(model, tools).run(turn())
        self.assertEqual(response.agent_text, FALLBACK)
        self.assertEqual([name for name, _ in tools.calls], ["crm.get_customer"])

        model2 = FakeModel({"action": "tool", "tool_name": "order.status",
                            "tool_args": {"order_id": "OD-OTHER", "customer_phone": "0984726714"}})
        tools2 = FakeTools(tools.results)
        response2 = await harness(model2, tools2).run(turn())
        self.assertEqual(response2.agent_text, FALLBACK)
        self.assertEqual([name for name, _ in tools2.calls], ["crm.get_customer"])

    async def test_verified_customer_can_read_only_owned_order(self):
        model = FakeModel(
            {"action": "tool", "tool_name": "order.status", "tool_args": {"order_id": "OD-MINE"}},
            {"action": "respond", "response": "Đơn đã giao ạ, mã OD-MINE."},
        )
        tools = FakeTools({
            "crm.get_customer": {"found": True, "customer_id": "C001", "phone": "0984726714",
                                 "orders": [{"order_id": "OD-MINE"}]},
            "order.status": {"orders": [
                {"order_id": "OD-MINE", "status": "delivered"},
                {"order_id": "OD-OTHER", "status": "shipping"},
            ]},
        })
        response = await harness(model, tools).run(turn())
        self.assertEqual(response.agent_text, "Đơn đã giao ạ, mã OD-MINE.")
        self.assertEqual(tools.calls[1], ("order.status", {"order_id": "OD-MINE"}))
        self.assertNotIn("OD-OTHER", model.seen[1][1].content)

    async def test_model_cannot_write_unsupported_or_pii_fact(self):
        memory = InMemoryStore()
        model = FakeModel({"action": "respond", "response": "Dạ, em ghi nhận ạ.",
                           "memory_writes": [
                               {"key": "budget_vnd", "value": 9999999},
                               {"key": "delivery_address", "value": "12 đường Lê Lợi"},
                               {"key": "phone", "value": "0984726714"},
                               {"key": "special_note", "value": "hoa@example.com"},
                           ]})
        tools = FakeTools({"crm.get_customer": {"found": True, "customer_id": "C001", "phone": "0984726714"}})
        await harness(model, tools, memory).run(turn(text="Chào shop"))
        self.assertEqual(memory.profile("C001"), {})

    async def test_name_and_email_are_masked_before_model(self):
        model = FakeModel({"action": "respond", "response": "Dạ, em đã nhận được ạ."})
        tools = FakeTools({"crm.get_customer": {"found": False}})
        await harness(model, tools).run(turn(text="Tên tôi là Hoa, email hoa@example.com"))
        self.assertNotIn("Hoa", model.seen[0][1].content)
        self.assertNotIn("hoa@example.com", model.seen[0][1].content)

    async def test_quote_price_cannot_be_written_as_customer_budget(self):
        memory = InMemoryStore()
        model = FakeModel(
            {"action": "tool", "tool_name": "pricing.get_quote", "tool_args": {"sku": "SKU-AP-Y"}},
            {"action": "respond", "response": "Giá là 5.200.000đ ạ.",
             "memory_writes": [{"key": "budget_vnd", "value": 5200000},
                               {"key": "price_quoted_vnd", "value": 5200000}]},
        )
        tools = FakeTools({
            "crm.get_customer": {"found": True, "customer_id": "C001", "phone": "0984726714"},
            "pricing.get_quote": {"sku": "SKU-AP-Y", "final_price_vnd": 5200000},
        })
        await harness(model, tools, memory).run(turn(text="Giá sao em?"))
        self.assertNotIn("budget_vnd", memory.profile("C001"))
        self.assertNotIn("price_quoted_vnd", memory.profile("C001"))

    async def test_rejects_price_claim_that_disagrees_with_quote(self):
        model = FakeModel(
            {"action": "tool", "tool_name": "pricing.get_quote", "tool_args": {"sku": "SKU-AP-Y"}},
            {"action": "respond", "response": "Giá là 5.300.000đ ạ."},
        )
        tools = FakeTools({
            "crm.get_customer": {"found": True, "customer_id": "C001", "phone": "0984726714"},
            "pricing.get_quote": {"sku": "SKU-AP-Y", "final_price_vnd": 5200000,
                                  "_internal_price_floor_vnd": 4500000},
        })
        response = await harness(model, tools).run(turn())
        self.assertEqual(response.agent_text, FALLBACK)
        self.assertEqual(tools.calls[1][1]["on"], "2026-10-17")
        self.assertNotIn("_internal_price_floor_vnd", model.seen[1][1].content)

    async def test_every_price_claim_and_stock_sku_must_match_tool_evidence(self):
        model = FakeModel(
            {"action": "tool", "tool_name": "pricing.get_quote", "tool_args": {"sku": "SKU-AP-Y"}},
            {"action": "respond", "response": "Giá 5.200.000đ, còn mẫu kia 5.300.000đ ạ."},
        )
        tools = FakeTools({
            "crm.get_customer": {"found": True, "customer_id": "C001", "phone": "0984726714"},
            "pricing.get_quote": {"sku": "SKU-AP-Y", "final_price_vnd": 5200000},
        })
        self.assertEqual((await harness(model, tools).run(turn())).agent_text, FALLBACK)

        model2 = FakeModel(
            {"action": "tool", "tool_name": "inventory.check", "tool_args": {"sku": "SKU-AP-Y"}},
            {"action": "respond", "response": "SKU-AP-X còn hàng ạ."},
        )
        tools2 = FakeTools({
            "crm.get_customer": {"found": False},
            "inventory.check": {"sku": "SKU-AP-Y", "in_stock": True, "qty": 3},
        })
        self.assertEqual((await harness(model2, tools2).run(turn())).agent_text, FALLBACK)

    def test_unverified_promotion_policy_and_delivery_claims_are_blocked(self):
        quote = [{"name": "pricing.get_quote", "args": {"sku": "SKU-AP-Y"},
                  "result": {"final_price_vnd": 5200000,
                             "applied_promos": [{"promo_code": "GIFT-FILTER"}], "freeship": False}}]
        self.assertEqual(verified_answer("Mã OTHER-10 đang khuyến mãi ạ.", quote), FALLBACK)
        self.assertEqual(verified_answer("Bảo hành 2 năm ạ.", quote), FALLBACK)
        self.assertEqual(verified_answer("Giao trong 2 ngày ạ.", quote), FALLBACK)

    def test_repeated_same_quote_from_call_brief_and_model_is_usable(self):
        call = {"name": "pricing.get_quote", "args": {"sku": "SKU-AP-X", "on": "2026-10-15"},
                "result": {"sku": "SKU-AP-X", "final_price_vnd": 4890000,
                           "applied_promos": [], "freeship": True}}
        self.assertEqual(verified_answer("SKU-AP-X giá 4.890.000đ ạ.", [call, call]),
                         "SKU-AP-X giá 4.890.000đ ạ.")


if __name__ == "__main__":
    unittest.main()
