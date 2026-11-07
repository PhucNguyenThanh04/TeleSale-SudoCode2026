"""Offline call preparation and first real-turn evidence boundaries."""

import unittest
import asyncio
from datetime import timedelta
from unittest.mock import patch

from langchain_core.messages import AIMessage

from app.agent.harness.runtime import AgentHarnessRuntime
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn


class ReturningMemory(FakeMemory):
    def __init__(self):
        super().__init__()
        self.reads = 0
        self.blocked = False
        self.profile = {
            "preferred_color": {"value": "trắng", "source_kind": "customer"},
            "product_advised": {"value": "SKU-AP-X", "source_kind": "tool"},
            "price_quoted_vnd": {"value": 1900000, "source_kind": "tool"},
        }

    async def read_context(self, session_id, customer_id):
        self.reads += 1
        if self.blocked:
            return {"error": "customer_erasure_in_progress"}
        result = await super().read_context(session_id, customer_id)
        result.update(turn_count=len(self.turns.get(session_id, [])),
            current_episode={} if self.turns.get(session_id) else None,
            episodes=[{"session_id": "previous-call", "channel": "hotline",
                "on": "2026-01-01", "summary": "Đã tư vấn máy lọc", "outcome": "khac"}])
        return result


class QuoteGateway(FakeGateway):
    async def invoke(self, name, args):
        if name == "catalog.search":
            self.calls.append((name, args))
            return {"items": [{"sku": "SKU-AP-X", "name": "Máy lọc AirPure X",
                               "variants": []}], "total": 1}
        if name == "pricing.get_quote":
            self.calls.append((name, args))
            return {"sku": args["sku"], "final_price_vnd": 2100000,
                    "applied_promos": []}
        return await super().invoke(name, args)


class SessionPreparationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.model = FakeToolModel(replies=[AIMessage(content="Dạ, em nghe ạ.")
                                            for _ in range(3)])
        self.memory = ReturningMemory()
        self.gateway = QuoteGateway()
        self.runtime = AgentHarnessRuntime(self.model, self.gateway, self.memory,
                                           agent_kind="react")
        self.request = turn("Alo")

    async def prepare(self, request=None):
        from app.schemas.agent import PrepareSessionRequest
        request = request or self.request
        return await self.runtime.prepare_session(PrepareSessionRequest.model_validate({
            key: getattr(request, key) for key in (
                "session_id", "channel", "channel_identity", "on",
                "verified_customer_id", "verified_phone")}))

    async def test_prepare_has_brief_without_model_turn_or_worker_job(self):
        prepared = await self.prepare()
        self.assertEqual(prepared.session_id, self.request.session_id)
        self.assertEqual(self.model.seen, [])
        self.assertEqual(self.memory.turns, {})
        self.assertEqual(self.memory.operations, {})
        brief = prepared.call_brief
        self.assertTrue(brief["is_returning"])
        self.assertIn("preferred_color", brief["must_not_ask"])
        self.assertEqual(brief["profile_facts"]["preferred_color"], "trắng")
        self.assertTrue(any("180" in warning for warning in brief["stale_warnings"]))

    async def test_first_turn_reuses_reads_but_revalidates_memory_and_brief(self):
        await self.prepare()
        response = await self.runtime.run(self.request)
        self.assertIsNotNone(response.call_brief)
        self.assertEqual(self.memory.reads, 2)
        self.assertEqual([name for name, _ in self.gateway.calls].count("crm.get_customer"), 1)
        self.assertEqual([name for name, _ in self.gateway.calls].count("pricing.get_quote"), 1)
        self.assertEqual(len(self.memory.turns[str(self.request.session_id)]), 1)
        self.assertNotIn('"customer": ""', self.model.seen[0])
        second = turn("Tôi muốn hỏi tiếp", self.request.session_id)
        next_response = await self.runtime.run(second)
        self.assertIsNone(next_response.call_brief)
        self.assertIn("Alo", self.model.seen[-1])

    async def test_memory_erasure_after_prepare_blocks_model_and_cached_profile(self):
        await self.prepare()
        self.memory.blocked = True
        response = await self.runtime.run(self.request)
        self.assertIsNone(response.call_brief)
        self.assertEqual(self.model.seen, [])
        self.assertIn("gián đoạn", response.agent_text)
        self.assertEqual(self.memory.turns, {})

    async def test_changed_date_or_expired_preparation_refreshes_commercial_reads(self):
        await self.prepare()
        later = self.request.model_copy(update={"on": self.request.on + timedelta(days=1)})
        response = await self.runtime.run(later)
        self.assertIsNotNone(response.call_brief)
        quotes = [args for name, args in self.gateway.calls if name == "pricing.get_quote"]
        self.assertEqual([quote["on"] for quote in quotes], ["2026-10-15", "2026-10-16"])

        another = turn("Alo")
        await self.prepare(another)
        with patch("app.agent.harness.runtime.time.perf_counter", return_value=10**12):
            await self.runtime.run(another)
        quotes = [args for name, args in self.gateway.calls if name == "pricing.get_quote"]
        self.assertEqual(len(quotes), 4)

    async def test_identity_mismatch_cannot_consume_prepared_customer(self):
        await self.prepare()
        other = self.request.model_copy(update={"channel_identity": "0900000999"})
        with self.assertRaises(ValueError):
            await self.runtime.run(other)
        self.assertEqual(self.model.seen, [])

    async def test_failed_prepare_does_not_publish_brief(self):
        self.memory.blocked = True
        with self.assertRaises(RuntimeError):
            await self.prepare()
        self.assertEqual(self.model.seen, [])
        self.assertEqual(self.memory.turns, {})

    async def test_first_utterance_quantity_does_not_reuse_unit_quote(self):
        await self.prepare()
        self.model.replies.insert(0, AIMessage(content="", tool_calls=[{
            "name": "catalog_search", "args": {"sku": "SKU-AP-X"}, "id": "catalog-1"}]))
        request = self.request.model_copy(update={"text": "Giá 2 chiếc SKU-AP-X bao nhiêu?"})
        await self.runtime.run(request)
        quotes = [args for name, args in self.gateway.calls if name == "pricing.get_quote"]
        self.assertTrue(any(args.get("qty") == 2 for args in quotes), quotes)

    async def test_unknown_customer_never_receives_returning_customer_brief(self):
        class UnknownGateway(QuoteGateway):
            async def invoke(self, name, args):
                if name == "crm.get_customer":
                    return {"found": False}
                return await super().invoke(name, args)

        self.runtime = AgentHarnessRuntime(self.model, UnknownGateway(), FakeMemory(),
                                           agent_kind="react")
        prepared = await self.prepare()
        self.assertIsNone(prepared.call_brief)
        response = await self.runtime.run(self.request)
        self.assertIsNone(response.call_brief)

    async def test_first_turn_brief_uses_memory_updated_after_preparation(self):
        prepared = await self.prepare()
        self.assertEqual(prepared.call_brief["profile_facts"]["preferred_color"], "trắng")
        self.memory.profile["preferred_color"] = {"value": "đen", "source_kind": "customer"}
        response = await self.runtime.run(self.request)
        self.assertEqual(response.call_brief["profile_facts"]["preferred_color"], "đen")

    async def test_cancelled_preparation_releases_session_for_real_turn(self):
        entered = asyncio.Event()
        original = self.memory.read_context

        async def pending(*args):
            entered.set()
            await asyncio.Event().wait()

        self.memory.read_context = pending
        task = asyncio.create_task(self.prepare())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.memory.read_context = original
        response = await asyncio.wait_for(self.runtime.run(self.request), 2)
        self.assertIsNotNone(response.call_brief)
        self.assertEqual(len(self.memory.turns[str(self.request.session_id)]), 1)
