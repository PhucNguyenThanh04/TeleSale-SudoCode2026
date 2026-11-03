"""The production graph uses Deep Agent tool calls and commits cross-session facts."""

import unittest
import asyncio
from datetime import date
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ValidationError

from app.constants import PROFILE_SLOT_KEYS
from app.agent.harness.runtime import DeepHarnessRuntime
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
        self.scoped_facts = {"product": {}, "room": {}}
        self.writes = []
        self.operations = {}
        self.turns = {}

    async def read_context(self, session_id, customer_id):
        return {"history": self.turns.get(session_id, []),
                "profile": dict(self.profile) if customer_id else {},
                "scoped_facts": self.scoped_facts if customer_id else {"product": {}, "room": {}},
                "episodes": [], "owned_order_ids": []}

    async def commit_turn(self, session_id, customer_id, customer_text, agent_text,
                          on, channel, client_msg_id, facts=None, orders=None,
                          episode_delta=None, outcome="khac", tool_observations=None):
        key = (session_id, client_msg_id)
        if key in self.operations:
            return self.operations[key]
        self.turns.setdefault(session_id, []).append(
            {"customer": customer_text, "agent": agent_text})
        written = []
        if not customer_id:
            result = {"turn_no": len(self.turns[session_id]), "memory_writes": []}
            self.operations[key] = result
            return result
        for fact in facts or []:
            if fact.get("scope_type") in {"product", "room"} and fact.get("scope_id"):
                bucket = self.scoped_facts[fact["scope_type"]].setdefault(fact["scope_id"], {})
                if fact.get("op") == "delete":
                    bucket.pop(fact["key"], None)
                else:
                    bucket[fact["key"]] = {"key": fact["key"], "value": fact["value"],
                                           "source_kind": fact.get("source_kind"),
                                           "status": "active", "on": on}
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

    async def test_failed_ordinary_transfer_has_explicit_failure_reply(self):
        class Gateway(FakeGateway):
            async def invoke(self, name, args):
                if name == "handoff.transfer":
                    self.calls.append((name, args))
                    return {"ticket_id": "HT0042", "status": "failed"}
                return await super().invoke(name, args)

        model = FakeToolModel(replies=[
            AIMessage(content="", tool_calls=[{"name": "handoff.transfer",
                "args": {"brief": {"escalation_reason": "khach_yeu_cau_gap_nguoi"}},
                "id": "handoff_attempt"}]),
            AIMessage(content="Dạ, em đã chuyển yêu cầu đến nhân viên tư vấn ạ.")])
        runtime = DeepHarnessRuntime(model, Gateway(), FakeMemory())
        response = await runtime.run(turn("Tôi muốn gặp nhân viên tư vấn"))
        self.assertFalse(response.needs_handoff)
        self.assertIn("chưa chuyển được", response.agent_text)

    async def test_call_brief_latency_includes_identity_lookup(self):
        class SlowGateway(FakeGateway):
            async def invoke(self, name, args):
                if name == "crm.get_customer":
                    await asyncio.sleep(0.05)
                return await super().invoke(name, args)

        class PriorMemory(FakeMemory):
            async def read_context(self, session_id, customer_id):
                result = await super().read_context(session_id, customer_id)
                result["episodes"] = [{"session_id": "old-call", "channel": "hotline",
                    "on": "2026-10-14", "summary": "Khách hỏi mẫu khác", "outcome": "khac"}]
                return result

        runtime = DeepHarnessRuntime(FakeToolModel(replies=[AIMessage(content="Dạ, em nghe ạ.")]),
                                     SlowGateway(), PriorMemory())
        response = await runtime.run(turn("Tôi hỏi tiếp sản phẩm hôm qua"))
        self.assertGreaterEqual(response.call_brief["latency_ms"], 40)

    async def test_shared_phone_does_not_load_either_candidate_memory(self):
        class SharedGateway(FakeGateway):
            async def invoke(self, name, args):
                if name == "crm.get_customer":
                    return {"found": True, "ambiguous": True, "candidates": [
                        {"customer_id": "C021", "name": "Mai", "sessions": [
                            {"session_id": "mai-prior", "channel": "hotline",
                             "date": "2026-10-12", "summary": "Hỏi máy lọc", "outcome": "khac"}]},
                        {"customer_id": "C022", "name": "Sơn", "sessions": [
                            {"session_id": "son-prior", "channel": "hotline",
                             "date": "2026-10-13", "summary": "Hỏi giày", "outcome": "khac"}]}]}
                return {"error": "unavailable"}

        class ScopedMemory(FakeMemory):
            async def read_context(self, session_id, customer_id):
                assert customer_id is None
                return {"history": self.turns.get(session_id, []), "profile": {},
                        "episodes": [], "owned_order_ids": []}

        model = FakeToolModel(replies=[AIMessage(content="Dạ, em nghe ạ.")])
        runtime = DeepHarnessRuntime(model, SharedGateway(), ScopedMemory())
        request = turn("Tôi hỏi tiếp món hôm trước", uuid4()).model_copy(update={
            "channel_identity": "0912283456"})
        response = await runtime.run(request)
        self.assertIsNone(response.call_brief)
        self.assertEqual(runtime.state_for(request)["identity_status"], "ambiguous")
        self.assertNotIn("Hỏi máy lọc", model.seen[0])
        self.assertNotIn("Hỏi giày", model.seen[0])

    async def test_same_customer_memory_is_available_after_channel_change(self):
        class MultiChannelGateway(FakeGateway):
            async def invoke(self, name, args):
                if name == "crm.get_customer":
                    assert args in ({"fb_id": "fb.thao.37"}, {"phone": "0934567812"})
                    return {"found": True, "customer_id": "C037", "phone": "0934567812",
                            "name": "Thảo", "orders": [], "sessions": []}
                return {"error": "unavailable"}

        class ScopedMemory(FakeMemory):
            async def read_context(self, session_id, customer_id):
                assert customer_id == "C037"
                return {"history": self.turns.get(session_id, []),
                        "profile": {"room_area_m2": {"value": 32,
                                                       "source_kind": "customer"}},
                        "episodes": [{"session_id": "prior-fanpage", "channel": "chat_fanpage",
                                      "on": "2026-10-14", "summary": "Quan tâm máy lọc yên tĩnh",
                                      "outcome": "khac"}], "owned_order_ids": []}

        model = FakeToolModel(replies=[AIMessage(content="Dạ, em ghi nhận ạ."),
                                       AIMessage(content="Dạ, em tiếp tục tư vấn ạ.")])
        runtime = DeepHarnessRuntime(model, MultiChannelGateway(), ScopedMemory())
        fanpage = turn("Tôi muốn xem thêm mẫu máy", uuid4()).model_copy(update={
            "channel": "chat_fanpage", "channel_identity": "fb.thao.37"})
        await runtime.run(fanpage)
        request = turn("Hôm trước tôi nhắn Fanpage", uuid4()).model_copy(update={
            "channel_identity": "0934567812"})
        response = await runtime.run(request)
        self.assertEqual(runtime.state_for(fanpage)["customer_id"], "C037")
        self.assertEqual(runtime.state_for(request)["customer_id"], "C037")
        self.assertEqual(response.call_brief["last_session"]["channel"], "chat_fanpage")
        self.assertEqual(response.call_brief["profile_facts"]["room_area_m2"], 32)




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

    def test_business_tools_expose_no_legacy_fact_proposals(self):
        business = BusinessTools(FakeGateway(), {}, 3, lambda: None)
        tools = business.langchain_tools()
        self.assertNotIn("memory.propose_fact", [tool.name for tool in tools])
        for tool in tools:
            self.assertNotIn("fact_candidates", tool.args_schema.model_fields)

    async def test_answer_guardrail_can_be_disabled_for_raw_agent_testing(self):
        text = "Dạ, giá là 9.999.999đ ạ."
        enabled = DeepHarnessRuntime(FakeToolModel(replies=[AIMessage(content=text)]),
                                     FakeGateway(), FakeMemory())
        disabled = DeepHarnessRuntime(FakeToolModel(replies=[AIMessage(content=text)]),
                                      FakeGateway(), FakeMemory(), guardrails_enabled=False)
        self.assertNotEqual((await enabled.run(turn("Giá mẫu này bao nhiêu?"))).agent_text, text)
        self.assertEqual((await disabled.run(turn("Giá mẫu này bao nhiêu?"))).agent_text, text)


    def test_customer_profile_and_sales_history_are_separate(self):
        customer, sales = _split_facts({
            "room_area_m2": {"value": 25, "source_kind": "customer"},
            "price_quoted_vnd": {"value": 5_490_000, "source_kind": "tool"},
            "product_advised": {"value": "SKU-XM-4P", "source_kind": "tool"},
        })
        self.assertEqual(set(customer), {"room_area_m2"})
        self.assertEqual(set(sales), {"price_quoted_vnd", "product_advised"})














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
        self.assertEqual([name for name, _ in gateway.calls], ["crm.get_customer", "catalog.search"])



if __name__ == "__main__":
    unittest.main()
