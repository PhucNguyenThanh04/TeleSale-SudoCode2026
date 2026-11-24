
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
            current_episode={'session_id': session_id} if self.turns.get(session_id) else None,
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
        self.runtime = AgentHarnessRuntime(self.model, self.gateway, self.memory)
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
        self.assertEqual([(name, args['on']) for name, args in self.gateway.calls
                          if name in {'inventory.check', 'pricing.get_quote'}],
                         [('inventory.check', self.request.on.isoformat()),
                          ('pricing.get_quote', self.request.on.isoformat())])

    async def test_first_turn_reuses_reads_but_revalidates_memory_and_brief(self):
        await self.prepare()
        response = await self.runtime.run(self.request)
        self.assertIsNotNone(response.call_brief)
        self.assertEqual(self.memory.reads, 2)
        self.assertEqual([name for name, _ in self.gateway.calls].count("crm.get_customer"), 1)
        self.assertEqual([name for name, _ in self.gateway.calls].count("pricing.get_quote"), 1)
        self.assertEqual([call['name'] for call in self.runtime.state_for(self.request)['prepared_tool_calls']],
                         ['crm.get_customer', 'inventory.check', 'pricing.get_quote'])
        self.assertEqual(len(self.memory.turns[str(self.request.session_id)]), 1)
        self.assertNotIn('"customer": ""', self.model.seen[0])
        second = turn("Tôi muốn hỏi tiếp", self.request.session_id)
        next_response = await self.runtime.run(second)
        self.assertIsNotNone(next_response.call_brief)
        self.assertEqual([name for name, _ in self.gateway.calls].count('pricing.get_quote'), 1)
        self.assertIn("Alo", self.model.seen[-1])

    async def test_later_brief_uses_updated_facts_without_repricing_every_turn(self):
        self.memory.profile.update({
            'budget_vnd': {'value': 5000000, 'source_kind': 'customer'},
            'blocker': {'value': 'cần hỏi chồng', 'source_kind': 'customer'}})
        await self.prepare()
        first = await self.runtime.run(self.request)
        self.assertEqual(first.call_brief['profile_facts']['budget_vnd'], 5000000)
        self.memory.profile['budget_vnd']['value'] = 4000000
        self.memory.profile.pop('blocker')
        second = await self.runtime.run(turn('Ông xã đồng ý rồi, em nói tiếp nhé.', self.request.session_id))
        self.assertIsNotNone(second.call_brief)
        self.assertEqual(second.call_brief['profile_facts']['budget_vnd'], 4000000)
        self.assertEqual(second.call_brief['open_blockers'], [])
        self.assertEqual([name for name, _ in self.gateway.calls].count('pricing.get_quote'), 1)
        third = await self.runtime.run(turn('Tôi nghe đây.', self.request.session_id))
        self.assertEqual(third.call_brief['profile_facts']['budget_vnd'], 4000000)
        self.assertIn('4000000', self.model.seen[-1])

    async def test_erasure_after_first_response_never_reuses_the_old_brief(self):
        await self.prepare()
        await self.runtime.run(self.request)
        calls_before = len(self.model.seen)
        self.memory.blocked = True
        response = await self.runtime.run(turn('Em nói tiếp nhé.', self.request.session_id))
        self.assertIsNone(response.call_brief)
        self.assertEqual(len(self.model.seen), calls_before + 1)
        self.assertNotIn('preferred_color', self.model.seen[-1])

    async def test_cached_retry_rechecks_erasure_without_rerunning_model(self):
        await self.prepare()
        first = await self.runtime.run(self.request)
        calls_before = len(self.model.seen)
        retry = await self.runtime.run(self.request)
        self.assertEqual(retry, first)
        self.assertEqual(len(self.memory.turns[str(self.request.session_id)]), 1)
        self.memory.blocked = True
        with self.assertRaisesRegex(RuntimeError, 'memory_unavailable'):
            await self.runtime.run(self.request)
        self.assertEqual(len(self.model.seen), calls_before)
        self.assertFalse(self.runtime._session_states.get(str(self.request.session_id)))

    async def test_retry_cannot_change_the_original_turn_date_or_text(self):
        await self.runtime.run(self.request)
        for update in ({'text': 'Mua mẫu khác.'}, {'on': self.request.on + timedelta(days=1)}):
            with self.assertRaisesRegex(ValueError, 'Conflicting turn retry'):
                await self.runtime.run(self.request.model_copy(update=update))

    async def test_memory_outage_invalidates_session_view_until_fresh_recovery(self):
        from unittest.mock import AsyncMock
        await self.runtime.run(self.request)
        calls_before = len(self.model.seen)
        with patch.object(self.memory, 'read_context', AsyncMock(side_effect=ConnectionError('private'))):
            response = await self.runtime.run(turn('Em nói tiếp nhé.', self.request.session_id))
        self.assertIsNone(response.call_brief)
        self.assertEqual(len(self.model.seen), calls_before + 1)
        self.assertNotIn('preferred_color', self.model.seen[-1])
        session = self.runtime._session_states[str(self.request.session_id)]
        self.assertEqual(session.context, {})
        self.memory.profile['preferred_color']['value'] = 'đen'
        recovered = await self.runtime.run(turn('Tôi nghe đây.', self.request.session_id))
        self.assertEqual(recovered.call_brief['profile_facts']['preferred_color'], 'đen')

    async def test_cached_full_response_cannot_be_retried_in_baseline_mode(self):
        await self.runtime.run(self.request)
        self.memory.include_prior = False
        with self.assertRaisesRegex(ValueError, 'Conflicting turn retry'):
            await self.runtime.run(self.request)

    async def test_pending_erasure_after_prepare_allows_model_without_cached_profile(self):
        await self.prepare()
        self.memory.blocked = True
        response = await self.runtime.run(self.request)
        self.assertIsNone(response.call_brief)
        self.assertEqual(len(self.model.seen), 1)
        self.assertNotIn('preferred_color', self.model.seen[-1])
        self.assertEqual(response.memory_update.status, 'unavailable')
        self.assertEqual(self.memory.turns, {})

    async def test_changed_date_or_expired_preparation_refreshes_call_brief(self):
        await self.prepare()
        later = self.request.model_copy(update={"on": self.request.on + timedelta(days=1)})
        response = await self.runtime.run(later)
        self.assertIsNotNone(response.call_brief)
        quotes = [args for name, args in self.gateway.calls if name == "pricing.get_quote"]
        self.assertEqual([args['on'] for args in quotes], [self.request.on.isoformat(), later.on.isoformat()])

        another = turn("Alo")
        await self.prepare(another)
        with patch("app.agent.harness.runtime.time.perf_counter", return_value=10**12):
            await self.runtime.run(another)
        quotes = [args for name, args in self.gateway.calls if name == "pricing.get_quote"]
        self.assertEqual([args['on'] for args in quotes[2:]], [another.on.isoformat()] * 2)
        self.assertEqual(self.memory.reads, 4)

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
        self.model.replies.insert(1, AIMessage(content='', tool_calls=[{
            'name': 'pricing_get_quote', 'args': {'sku': 'SKU-AP-X', 'qty': 2}, 'id': 'quote-2'}]))
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

        self.runtime = AgentHarnessRuntime(self.model, UnknownGateway(), FakeMemory())
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
