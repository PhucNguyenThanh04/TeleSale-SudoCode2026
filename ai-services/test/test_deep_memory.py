"""The production graph uses Deep Agent tool calls and commits cross-session facts."""

import unittest
from datetime import date
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.agent.harness.runtime import DeepHarnessRuntime
from app.agent.memory.fact_candidates import accepted_candidates
from app.agent.harness.context import _split_facts
from app.agent.implementations.deep_agent import BusinessTools
from app.schemas.agent import TextTurnRequest


class FakeToolModel(BaseChatModel):
    replies: list[AIMessage]
    extraction_replies: list[AIMessage] = []
    extraction_calls: int = 0
    seen: list[str] = []

    @property
    def _llm_type(self):
        return "fake_tool_model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if "MEMORY_FACT_EXTRACTION" in str(messages):
            self.extraction_calls += 1
            reply = (self.extraction_replies.pop(0) if self.extraction_replies else
                     AIMessage(content='{"fact_candidates":[]}'))
            return ChatResult(generations=[ChatGeneration(message=reply)])
        self.seen.append(str(messages))
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])


class FakeGateway:
    def __init__(self, customer_id="C001"):
        self.customer_id = customer_id
        self.calls = []

    async def invoke(self, name, args):
        self.calls.append((name, args))
        if name == "crm.get_customer":
            return {"found": True, "customer_id": self.customer_id,
                    "phone": "0984726714", "orders": [], "sessions": []}
        if name == "catalog.search":
            return {"items": [{"sku": "SKU-AP-X", "name": "Máy lọc AirPure X"}], "total": 1}
        if name == "inventory.check":
            return {"sku": args["sku"], "in_stock": True, "qty": 3}
        return {"error": "unavailable"}


class FakeMemory:
    include_prior = True

    def __init__(self):
        self.profile = {}
        self.writes = []
        self.operations = {}
        self.turns = {}
        self.pending = {}

    async def claim_pending(self, session_id, customer_id, client_msg_id):
        written = []
        for fact, source in self.pending.pop(session_id, []):
            old = self.profile.get(fact["key"])
            if old and old["value"] == fact.get("value"):
                continue
            self.profile[fact["key"]] = {"key": fact["key"],
                "value": fact.get("value"), "source": source,
                "source_kind": fact["source_kind"], "status": "active"}
            written.append({"key": fact["key"], "value": fact.get("value"),
                "op": "supersede" if old else "set", "source": source,
                "customer_id": customer_id})
        self.writes.extend(written)
        return {"memory_writes": written}

    async def read_context(self, session_id, customer_id):
        return {"history": self.turns.get(session_id, []),
                "profile": dict(self.profile) if customer_id else {},
                "episodes": [], "owned_order_ids": []}

    async def commit_turn(self, session_id, customer_id, customer_text, agent_text,
                          on, channel, client_msg_id, facts, orders=None):
        key = (session_id, client_msg_id)
        if key in self.operations:
            return self.operations[key]
        self.turns.setdefault(session_id, []).append(
            {"customer": customer_text, "agent": agent_text})
        written = []
        if not customer_id:
            self.pending.setdefault(session_id, []).extend(
                (fact, f"{session_id}:{client_msg_id}") for fact in facts)
            result = {"turn_no": len(self.turns[session_id]), "memory_writes": []}
            self.operations[key] = result
            return result
        for fact in facts:
            old = self.profile.get(fact["key"])
            if old and old["value"] == fact["value"]:
                continue
            op = "supersede" if old else "set"
            self.profile[fact["key"]] = {"key": fact["key"], "value": fact["value"],
                                         "source": f"{session_id}:{client_msg_id}",
                                         "status": "active"}
            written.append({"key": fact["key"], "value": fact["value"], "op": op,
                            "source": f"{session_id}:{client_msg_id}",
                            "customer_id": customer_id})
        self.writes.extend(written)
        result = {"turn_no": len(self.turns[session_id]), "memory_writes": written}
        self.operations[key] = result
        return result


def turn(text, session_id=None):
    return TextTurnRequest(client_msg_id=uuid4(), session_id=session_id or uuid4(),
                           channel="hotline", channel_identity="0984726714",
                           on=date(2026, 10, 15), text=text, input_mode="clean")


class DeepMemoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_extracts_second_fact_when_agent_proposes_first(self):
        model = FakeToolModel(replies=[
            AIMessage(content='{"answer":"Dạ, em ghi nhận ạ.","fact_candidates":'
                              '[{"key":"room_area_m2","value":25,"source":"customer"}]}'),
        ], extraction_replies=[AIMessage(content='{"fact_candidates":['
            '{"key":"budget_vnd","value":5000000,"source":"customer"}]}')])
        memory = FakeMemory()
        runtime = DeepHarnessRuntime(model, FakeGateway(), memory)
        await runtime.run(turn("Phòng anh 25 m², ngân sách anh 5 triệu."))
        self.assertEqual(model.extraction_calls, 1)
        self.assertEqual(memory.profile["room_area_m2"]["value"], 25)
        self.assertEqual(memory.profile["budget_vnd"]["value"], 5_000_000)

    async def test_pending_fact_flushes_after_late_verified_identity(self):
        class SharedPhoneGateway(FakeGateway):
            async def invoke(self, name, args):
                self.calls.append((name, args))
                if name == "crm.get_customer":
                    return {"found": True, "ambiguous": True, "candidates": [
                        {"customer_id": "C001", "name": "Hoa", "orders": [], "sessions": []},
                        {"customer_id": "C002", "name": "Nam", "orders": [], "sessions": []}]}
                return {"error": "unavailable"}

        model = FakeToolModel(replies=[
            AIMessage(content='{"answer":"Dạ, em ghi nhận ạ.","fact_candidates":'
                              '[{"key":"room_area_m2","value":25,"source":"customer"}]}'),
            AIMessage(content="Dạ, mình tiếp tục nhé."),
        ])
        memory = FakeMemory()
        runtime = DeepHarnessRuntime(model, SharedPhoneGateway(), memory)
        session_id = uuid4()
        first = turn("Phòng anh 25 m²", session_id)
        await runtime.run(first)
        self.assertEqual(memory.profile, {})
        self.assertEqual(len(memory.pending[str(session_id)]), 1)
        second = turn("Mình tiếp tục nhé", session_id).model_copy(update={
            "verified_customer_id": "C001", "verified_phone": "0984726714"})
        await runtime.run(second)
        self.assertEqual(memory.profile["room_area_m2"]["value"], 25)
        self.assertEqual(runtime.state_for(second)["memory_writes"][0]["op"], "set")

    def test_production_graph_has_one_agent_step(self):
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[]), FakeGateway(), FakeMemory())
        self.assertEqual(set(runtime.graph.nodes), {
            "__start__", "accept", "retrieve_context",
            "run_agent", "verify", "persist",
        })

    async def test_identity_is_initialized_once_for_multiple_turns(self):
        for agent_kind in ("deep", "react"):
            with self.subTest(agent_kind=agent_kind):
                session_id = uuid4()
                gateway, memory = FakeGateway(), FakeMemory()
                runtime = DeepHarnessRuntime(FakeToolModel(replies=[
                    AIMessage(content="Dạ, em đã ghi nhận ạ."),
                    AIMessage(content="Dạ, mình tiếp tục nhé."),
                ]), gateway, memory, agent_kind=agent_kind)
                first = turn("Tôi cần tư vấn", session_id)
                second = turn("Tư vấn tiếp", session_id)
                await runtime.run(first)
                await runtime.run(second)
                self.assertEqual([name for name, _ in gateway.calls], ["crm.get_customer"])
                self.assertEqual(runtime.state_for(first)["customer_id"], "C001")
                self.assertEqual(runtime.state_for(second)["customer_id"], "C001")
                self.assertEqual(len(memory.turns[str(session_id)]), 2)

    async def test_session_rejects_changed_channel_identity(self):
        session_id = uuid4()
        gateway = FakeGateway()
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[
            AIMessage(content="Dạ, em đã ghi nhận ạ."),
        ]), gateway, FakeMemory())
        await runtime.run(turn("Xin chào", session_id))
        changed = turn("Xin chào", session_id).model_copy(
            update={"channel_identity": "0999999999"})
        with self.assertRaisesRegex(ValueError, "Session channel identity mismatch"):
            await runtime.run(changed)
        self.assertEqual([name for name, _ in gateway.calls], ["crm.get_customer"])

    async def test_crm_failure_does_not_cache_unknown_identity(self):
        class FlakyGateway(FakeGateway):
            failures = 1

            async def invoke(self, name, args):
                if name == "crm.get_customer" and self.failures:
                    self.failures -= 1
                    return {"error": "unavailable"}
                return await super().invoke(name, args)

        gateway = FlakyGateway()
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[
            AIMessage(content="Dạ, em đã ghi nhận ạ."),
        ]), gateway, FakeMemory())
        request = turn("Xin chào")
        with self.assertRaisesRegex(RuntimeError, "CRM identity lookup failed"):
            await runtime.run(request)
        await runtime.run(request)
        self.assertEqual(runtime.state_for(request)["customer_id"], "C001")

    def test_business_tool_schema_exposes_fact_candidates(self):
        business = BusinessTools(FakeGateway(), {}, 3, lambda: None)
        search = next(tool for tool in business.langchain_tools()
                      if tool.name == "catalog.search")
        self.assertIn("fact_candidates", search.args_schema.model_fields)

    async def test_answer_guardrail_can_be_disabled_for_raw_agent_testing(self):
        text = "Dạ, giá là 9.999.999đ ạ."
        enabled = DeepHarnessRuntime(FakeToolModel(replies=[AIMessage(content=text)]),
                                     FakeGateway(), FakeMemory())
        disabled = DeepHarnessRuntime(FakeToolModel(replies=[AIMessage(content=text)]),
                                      FakeGateway(), FakeMemory(), guardrails_enabled=False)
        self.assertNotEqual((await enabled.run(turn("Giá mẫu này bao nhiêu?"))).agent_text, text)
        self.assertEqual((await disabled.run(turn("Giá mẫu này bao nhiêu?"))).agent_text, text)

    def test_model_proposed_profile_facts_are_grounded(self):
        text = "Nhà chị có bé nhỏ, ngân sách tầm 5 triệu thôi em. Để chị hỏi ông xã."
        proposals = [{"key": "budget_vnd", "value": 5_000_000},
                     {"key": "has_children", "value": True},
                     {"key": "blocker", "value": "hỏi ông xã"}]
        facts = {item["key"]: item["value"] for item in accepted_candidates(
            text, [], proposals)}
        self.assertEqual(facts["budget_vnd"], 5_000_000)
        self.assertTrue(facts["has_children"])
        self.assertEqual(facts["blocker"], "hỏi ông xã")
        text = "Ngân sách anh tầm 5,5 triệu thôi, để anh hỏi vợ đã."
        facts = {item["key"]: item["value"] for item in accepted_candidates(
            text, [], [{"key": "budget_vnd", "value": 5_500_000}])}
        self.assertEqual(facts["budget_vnd"], 5_500_000)

    def test_price_question_or_product_price_is_not_customer_budget(self):
        quote = [{"name": "pricing.get_quote", "args": {"sku": "SKU-XM-4P"},
                  "result": {"sku": "SKU-XM-4P", "final_price_vnd": 5_490_000}}]
        for text in ("Máy này giá bao nhiêu?", "Máy này giá tầm 5 triệu à?"):
            proposed = [{"key": "budget_vnd", "value": 5_490_000,
                         "source": "customer", "origin": "model"}]
            facts = accepted_candidates(text, quote, proposed)
            self.assertNotIn("budget_vnd", {fact["key"] for fact in facts})
        text = "Ngân sách tôi 5 triệu; mẫu này giá 5,49 triệu à?"
        proposed = [{"key": "budget_vnd", "value": 5_000_000,
                     "source": "customer", "origin": "model"},
            {"key": "budget_vnd", "value": 5_490_000,
             "source": "customer", "origin": "model"}]
        facts = {fact["key"]: fact["value"] for fact in accepted_candidates(text, quote, proposed)}
        self.assertEqual(facts["budget_vnd"], 5_000_000)

    def test_customer_profile_and_sales_history_are_separate(self):
        customer, sales = _split_facts({
            "room_area_m2": {"value": 25, "source_kind": "customer"},
            "price_quoted_vnd": {"value": 5_490_000, "source_kind": "tool"},
            "product_advised": {"value": "SKU-XM-4P", "source_kind": "tool"},
        })
        self.assertEqual(set(customer), {"room_area_m2"})
        self.assertEqual(set(sales), {"price_quoted_vnd", "product_advised"})

    def test_model_proposed_competitor_price_and_shoe_preferences(self):
        text = "Bên kia chị thấy đang bán 4590k thôi, sao bên em đắt hơn?"
        facts = {item["key"]: item["value"] for item in accepted_candidates(
            text, [], [{"key": "competitor_price_vnd", "value": 4_590_000},
                       {"key": "objection", "value": "dat_qua"}])}
        self.assertEqual(facts["competitor_price_vnd"], 4_590_000)
        self.assertNotIn("objection", facts)  # The objection appears only in a question.
        self.assertNotIn("budget_vnd", facts)
        text = "Giày còn size 39 màu den không? Em lên đơn, thanh toán COD nhé."
        facts = {item["key"]: item["value"] for item in accepted_candidates(
            text, [], [{"key": "size", "value": 39},
                       {"key": "color", "value": "den"},
                       {"key": "payment", "value": "COD"}])}
        self.assertNotIn("size", facts)
        self.assertNotIn("color", facts)
        self.assertEqual(facts["payment"], "COD")

    def test_variant_is_saved_only_when_selected_from_catalog(self):
        calls = [{"name": "catalog.search", "args": {"sku": "SKU-SN-CAS"},
                  "result": {"items": [{"sku": "SKU-SN-CAS", "name": "Urban Classic",
                                       "variants": [
                                           {"variant_sku": "SKU-SN-CAS-39-DEN"},
                                           {"variant_sku": "SKU-SN-CAS-40-DEN"}]}]}}]
        chosen = [{"key": "product_advised", "value": "SKU-SN-CAS"},
                  {"key": "variant_sku", "value": "SKU-SN-CAS-39-DEN"}]
        facts = {item["key"]: item["value"] for item in accepted_candidates(
            "Size 39 màu den nhé", calls, chosen)}
        self.assertEqual(facts["variant_sku"], "SKU-SN-CAS-39-DEN")

    def test_unproposed_fact_is_not_written(self):
        self.assertEqual(accepted_candidates("Phòng anh 25 m²", [], []), [])

    def test_spoken_room_area_proposal_requires_matching_customer_evidence(self):
        text = "phòng anh ba mươi lăm mét vuông có được không"
        proposed = [{"key": "room_area_m2", "value": 35, "source": "customer"}]
        self.assertEqual(accepted_candidates(text, [], proposed), [])
        self.assertEqual(accepted_candidates("phòng anh ba mươi lăm mét vuông, tư vấn giúp", [],
                                             proposed)[0]["value"], 35)
        self.assertEqual(accepted_candidates(text, [], [
            {"key": "room_area_m2", "value": 25, "source": "customer"}]), [])
        self.assertEqual(accepted_candidates("Ngân sách 35k", [], [
            {"key": "room_area_m2", "value": 35_000, "source": "customer"}]), [])

    async def test_spoken_room_area_from_tool_plan_is_committed(self):
        model = FakeToolModel(replies=[
            AIMessage(content="", tool_calls=[{
                "name": "catalog.search",
                "args": {"query": "Xiaomi Smart 4 Pro", "fact_candidates": [{
                    "key": "room_area_m2", "value": 35, "source": "customer"}]},
                "id": "call_area"}]),
            AIMessage(content="Dạ, phòng 35 m² dùng được ạ."),
        ])
        memory = FakeMemory()
        runtime = DeepHarnessRuntime(model, FakeGateway(), memory)
        request = turn("phòng anh ba mươi lăm mét vuông có được không")
        await runtime.run(request)
        self.assertNotIn("room_area_m2", memory.profile)
        self.assertEqual(runtime.state_for(request)["memory_writes"], [])

    async def test_model_proposal_is_validated_without_exposing_memory_write(self):
        model = FakeToolModel(replies=[
            AIMessage(content="", tool_calls=[{
                "name": "memory.propose_fact",
                "args": {"key": "blocker", "value": "hỏi thêm người nhà",
                         "source": "customer"}, "id": "call_memory"}]),
            AIMessage(content="Dạ, anh cứ hỏi thêm người nhà rồi báo em ạ."),
        ])
        gateway, memory = FakeGateway(), FakeMemory()
        runtime = DeepHarnessRuntime(model, gateway, memory)
        request = turn("Anh sẽ hỏi thêm người nhà rồi quyết định")
        await runtime.run(request)
        self.assertEqual(memory.profile["blocker"]["value"], "hỏi thêm người nhà")
        self.assertEqual([name for name, _ in gateway.calls], ["crm.get_customer"])

    async def test_dated_tool_uses_request_day_and_extra_model_fact_is_rejected(self):
        model = FakeToolModel(replies=[
            AIMessage(content='{"fact_candidates":[{"key":"room_area_m2","value":99,"source":"customer"}]}',
                      tool_calls=[{"name": "inventory.check",
                                   "args": {"sku": "SKU-AP-X"}, "id": "call_2"}]),
            AIMessage(content="Dạ, SKU-AP-X còn hàng ạ."),
        ])
        gateway, memory = FakeGateway(), FakeMemory()
        runtime = DeepHarnessRuntime(model, gateway, memory)
        request = turn("SKU-AP-X còn hàng không?", uuid4())
        await runtime.run(request)
        self.assertEqual(gateway.calls[-1],
                         ("inventory.check", {"sku": "SKU-AP-X", "on": "2026-10-15"}))
        self.assertNotIn("room_area_m2", memory.profile)

    async def test_tool_call_and_fact_candidate_are_committed(self):
        model = FakeToolModel(replies=[
            AIMessage(content="", tool_calls=[{"name": "catalog.search",
                                               "args": {"category": "air_purifier",
                                                        "fact_candidates": [{
                                                            "key": "room_area_m2",
                                                            "value": 25,
                                                            "source": "customer"}]},
                                               "id": "call_1"}]),
            AIMessage(content="Dạ, em tìm thấy Máy lọc AirPure X ạ."),
        ])
        gateway, memory = FakeGateway(), FakeMemory()
        runtime = DeepHarnessRuntime(model, gateway, memory)
        request = turn("Phòng anh 25 m², tư vấn máy lọc không khí nhé")
        response = await runtime.run(request)
        state = runtime.state_for(request)
        self.assertIn("AirPure X", response.agent_text)
        self.assertEqual(memory.profile["room_area_m2"]["value"], 25)
        self.assertEqual(state["memory_writes"][0]["key"], "room_area_m2")
        self.assertEqual(state["plan_envelopes"][0]["tool_name"], "catalog.search")
        self.assertEqual(state["plan_envelopes"][0]["fact_candidates"][0]["value"], 25)
        self.assertEqual([name for name, _ in gateway.calls],
                         ["crm.get_customer", "catalog.search"])
        self.assertEqual(gateway.calls[-1][1], {"category": "air_purifier"})

    async def test_customer_fact_is_saved_when_sales_agent_omits_candidates(self):
        model = FakeToolModel(
            replies=[AIMessage(content="Dạ, em ghi nhận phòng 25 m² ạ.")],
            extraction_replies=[AIMessage(content='```json\n{"fact_candidates":['
                                                '{"key":"room_area_m2","value":25,'
                                                '"source":"customer"}]}\n```')],
        )
        memory = FakeMemory()
        runtime = DeepHarnessRuntime(model, FakeGateway(), memory)
        response = await runtime.run(turn("Phòng anh 25 m²"))
        self.assertEqual(response.agent_text, "Dạ, em ghi nhận phòng 25 m² ạ.")
        self.assertEqual(memory.profile["room_area_m2"]["value"], 25)
        self.assertEqual(model.extraction_calls, 1)

    async def test_fenced_final_answer_and_fact_candidates_are_parsed(self):
        model = FakeToolModel(replies=[AIMessage(content=(
            '```json\n{"answer":"Dạ em ghi nhận phòng 28 m² ạ.",'
            '"fact_candidates":[{"key":"room_area_m2","value":28,'
            '"source":"customer"}]}\n```'))])
        memory = FakeMemory()
        runtime = DeepHarnessRuntime(model, FakeGateway(), memory)
        response = await runtime.run(turn("Phòng anh 28 m²"))
        self.assertEqual(response.agent_text, "Dạ em ghi nhận phòng 28 m² ạ.")
        self.assertEqual(memory.profile["room_area_m2"]["value"], 28)
        self.assertEqual(model.extraction_calls, 0)

    async def test_react_agent_uses_same_fact_and_memory_path(self):
        model = FakeToolModel(replies=[AIMessage(content=(
            '{"answer":"Dạ em đã ghi nhận 28 m² ạ.",'
            '"fact_candidates":[{"key":"room_area_m2","value":28,'
            '"source":"customer"}]}'))])
        memory = FakeMemory()
        runtime = DeepHarnessRuntime(model, FakeGateway(), memory,
                                     agent_kind="react", fact_extraction_mode="off")
        response = await runtime.run(turn("Phòng anh 28 m²"))
        self.assertEqual(response.agent_text, "Dạ em đã ghi nhận 28 m² ạ.")
        self.assertEqual(memory.profile["room_area_m2"]["value"], 28)

    async def test_json_fact_does_not_require_a_second_model_call(self):
        model = FakeToolModel(replies=[AIMessage(content=(
            '{"answer":"Dạ em đã ghi nhận 28 m² ạ.",'
            '"fact_candidates":[{"key":"room_area_m2","value":28,'
            '"source":"customer"}]}'))])
        runtime = DeepHarnessRuntime(model, FakeGateway(), FakeMemory(),
                                     fact_extraction_mode="fallback")
        await runtime.run(turn("Phòng anh 28 m²"))
        self.assertEqual(len(model.seen), 1)
        self.assertEqual(model.extraction_calls, 0)

    async def test_tool_call_rejects_unsupported_model_fact_candidate(self):
        model = FakeToolModel(replies=[
            AIMessage(content="", tool_calls=[{"name": "catalog.search",
                                               "args": {"category": "air_purifier",
                                                        "fact_candidates": [{
                                                            "key": "budget_vnd",
                                                            "value": 5_490_000,
                                                            "source": "customer"}]},
                                               "id": "call_1"}]),
            AIMessage(content="Dạ, em tìm thấy Máy lọc AirPure X ạ."),
        ])
        gateway, memory = FakeGateway(), FakeMemory()
        runtime = DeepHarnessRuntime(model, gateway, memory)
        request = turn("Máy lọc này giá bao nhiêu?")
        await runtime.run(request)
        self.assertNotIn("budget_vnd", memory.profile)
        self.assertEqual(runtime.state_for(request)["plan_envelopes"][0]
                         ["fact_candidates"][0]["value"], 5_490_000)

    async def test_order_tool_still_requires_current_stock_and_quote(self):
        model = FakeToolModel(replies=[
            AIMessage(content="", tool_calls=[{
                "name": "order.create",
                "args": {"sku": "SKU-AP-X", "qty": 1,
                         "price_vnd": 4_890_000, "payment": "COD"},
                "id": "call_order"}]),
            AIMessage(content="Dạ, em cần kiểm tra lại sản phẩm trước khi lên đơn ạ."),
        ])
        gateway = FakeGateway()
        runtime = DeepHarnessRuntime(model, gateway, FakeMemory())
        await runtime.run(turn("Em lên đơn giúp anh nhé"))
        self.assertEqual([name for name, _ in gateway.calls], ["crm.get_customer"])

    async def test_cross_session_recall_and_supersede(self):
        model = FakeToolModel(replies=[
            AIMessage(content='{"answer":"Dạ, em đã ghi nhận ạ.","fact_candidates":'
                              '[{"key":"room_area_m2","value":25,"source":"customer"}]}'),
            AIMessage(content='{"answer":"Dạ, em đã cập nhật ạ.","fact_candidates":'
                              '[{"key":"room_area_m2","value":28,"source":"customer"}]}'),
        ])
        memory = FakeMemory()
        runtime = DeepHarnessRuntime(model, FakeGateway(), memory)
        first = turn("Phòng anh 25 m²")
        second = turn("À phòng anh 28 m²", uuid4())
        await runtime.run(first)
        await runtime.run(second)
        self.assertEqual(memory.profile["room_area_m2"]["value"], 28)
        self.assertEqual([item["op"] for item in memory.writes], ["set", "supersede"])
        self.assertIn("25", model.seen[1])


if __name__ == "__main__":
    unittest.main()
