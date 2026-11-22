
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.mcp_servers.mcp_memory.distiller_worker import process_one
from app.mcp_servers.mcp_memory.services.memory import write
from app.agent.memory.store import safe_observations


class QueueTests(unittest.IsolatedAsyncioTestCase):
    def test_memory_observations_allowlist_order_and_quote_fields(self):
        calls = [
            {"name": "order.create", "args": {"sku": "SKU-SN-CAS-39-DEN",
                "payment": "COD", "customer_phone": "0912345678",
                "address": "Số 1", "internal_cost_vnd": 300000},
             "result": {"status": "created", "order_id": "OD682761",
                "total_vnd": 890000, "supplier": "Nội bộ"}},
            {"name": "pricing.get_quote", "args": {"sku": "SKU-SN-CAS",
                "on": "2026-10-15", "customer_phone": "0912345678"},
             "result": {"sku": "SKU-SN-CAS", "final_price_vnd": 890000,
                "internal_cost_vnd": 300000, "applied_promos": [
                    {"promo_code": "RUN-10", "valid_until": "2026-10-20",
                     "supplier": "Nội bộ"}]}},
        ]
        safe = safe_observations(calls)
        self.assertEqual(safe[0], {"name": "order.create",
            "args": {"sku": "SKU-SN-CAS-39-DEN", "payment": "COD"},
            "result": {"status": "created", "order_id": "OD682761",
                       "total_vnd": 890000}})
        self.assertEqual(safe[1]["result"]["applied_promos"],
                         [{"promo_code": "RUN-10", "valid_until": "2026-10-20"}])

    def test_memory_observations_ignore_malformed_nested_tool_fields(self):
        calls = [{"name": "catalog.search", "args": {},
                  "result": {"items": [None, {"sku": "SKU-A",
                      "variants": [None, {"variant_sku": "SKU-A-39"}]}]}},
                 {"name": "pricing.get_quote", "args": {"sku": "SKU-A"},
                  "result": {"sku": "SKU-A", "applied_promos": None}}]
        safe = safe_observations(calls)
        self.assertEqual(safe[0]["result"]["items"], [{"sku": "SKU-A",
            "attributes": {}, "variants": [{"variant_sku": "SKU-A-39"}]}])
        self.assertEqual(safe[1]["result"]["applied_promos"], [])

    def repo(self):
        repo = MagicMock()
        @asynccontextmanager
        async def transaction():
            yield object()
        repo.transaction = transaction
        for name in ("lock_key", "is_erasure_blocked", "owner", "next_turn",
                     "customer_turns", "session_facts", "episode_state",
                     "insert_turn", "attribute_anonymous_turns",
                     "upsert_episode_state",
                     "enqueue_distillation", "claim_distillation",
                     "distillation_turn", "save_distillation_proposals",
                     "finish_distillation", "enqueue_knowledge_event"):
            setattr(repo, name, AsyncMock())
        repo.attribute_anonymous_turns.return_value = []
        repo.distillation_claim_current = AsyncMock(return_value=True)
        return repo

    async def test_commit_queues_distillation(self):
        repo = self.repo()
        repo.owner.return_value = None
        repo.next_turn.return_value = 1
        repo.customer_turns.return_value = []
        repo.session_facts.return_value = []
        repo.episode_state.return_value = None
        repo.claim_operation.return_value = None
        repo.is_erasure_blocked.return_value = False
        repo.turn_count.return_value = 0
        session, turn = str(uuid4()), str(uuid4())
        data = {"client_msg_id": turn, "customer_text": "Tôi thích màu xanh",
                "agent_text": "Dạ", "channel": "hotline", "on": "2026-10-15",
                "tool_observations": [{"name": "pricing.get_quote",
                    "args": {"sku": "SKU-A"}, "result": {"final_price_vnd": 5000000}}]}
        await write(repo, "commit_turn", "C1", session, data)
        repo.enqueue_distillation.assert_awaited_once()

    async def test_worker_timeout_does_not_mark_complete(self):
        repo = self.repo()
        repo.claim_distillation.return_value = {"job_id": 1, "customer_id": "C1",
            "session_id": str(uuid4()), "source_turn_id": str(uuid4()), "attempts": 1}
        repo.distillation_turn.return_value = {"customer_text": "Tôi thích màu xanh",
            "agent_text": "Dạ", "on_date": "2026-10-15", "channel": "hotline"}
        repo.is_erasure_blocked.return_value = False
        extractor = AsyncMock(side_effect=TimeoutError())
        self.assertTrue(await process_one(repo, extractor, None))
        repo.finish_distillation.assert_awaited_once()
        self.assertEqual(repo.finish_distillation.await_args.args[2], "pending")

    async def test_extractor_internal_type_error_does_not_invoke_it_twice(self):
        repo = self.repo()
        repo.claim_distillation.return_value = {'job_id': 1, 'customer_id': 'C1',
            'session_id': str(uuid4()), 'source_turn_id': str(uuid4()), 'attempts': 1}
        repo.distillation_turn.return_value = {'customer_text': 'Tôi thích màu xanh',
            'agent_text': 'Dạ', 'on_date': '2026-10-15', 'channel': 'hotline'}
        repo.is_erasure_blocked.return_value = False
        extractor = AsyncMock(side_effect=TypeError('internal extraction failure'))
        await process_one(repo, extractor, None)
        assert extractor.await_count == 1
        assert repo.finish_distillation.await_args.args[2:] == ('pending', 'TypeError')

    async def test_expired_claim_cannot_extract_or_change_new_claim(self):
        repo = self.repo()
        repo.claim_distillation.return_value = {'job_id': 1, 'customer_id': 'C1',
            'session_id': str(uuid4()), 'source_turn_id': str(uuid4()), 'attempts': 1}
        repo.is_erasure_blocked.return_value = False
        repo.distillation_claim_current = AsyncMock(return_value=False)
        extractor = AsyncMock(return_value=([], None))
        await process_one(repo, extractor, AsyncMock())
        extractor.assert_not_awaited()
        repo.finish_distillation.assert_not_awaited()

    async def test_projection_retry_reuses_saved_proposals_without_model_call(self):
        repo = self.repo()
        repo.claim_distillation.return_value = {'job_id': 1, 'customer_id': 'C1',
            'session_id': str(uuid4()), 'source_turn_id': str(uuid4()), 'attempts': 2,
            'accepted_proposals': {'facts': [], 'delta': None, 'outcome': 'khac'}}
        repo.distillation_turn.return_value = {'customer_text': 'Chào',
            'agent_text': 'Dạ', 'on_date': '2026-10-15', 'channel': 'hotline'}
        repo.is_erasure_blocked.return_value = False
        extractor, projector = AsyncMock(), AsyncMock()
        projector.list_fact_versions.return_value = []
        projector.put_facts.return_value = []
        await process_one(repo, extractor, projector)
        extractor.assert_not_awaited()
        projector.put_facts.assert_awaited_once()
        assert repo.finish_distillation.await_args.args[2] == 'completed'

    async def test_lost_claim_before_projection_cannot_publish_saved_proposals(self):
        repo = self.repo()
        repo.claim_distillation.return_value = {'job_id': 1, 'customer_id': 'C1',
            'session_id': str(uuid4()), 'source_turn_id': str(uuid4()), 'attempts': 2,
            'accepted_proposals': {'facts': [], 'delta': None, 'outcome': 'khac'}}
        repo.distillation_turn.return_value = {'customer_text': 'Chào',
            'agent_text': 'Dạ', 'on_date': '2026-10-15', 'channel': 'hotline'}
        repo.is_erasure_blocked.return_value = False
        repo.distillation_claim_current.side_effect = [True, False]
        extractor, projector = AsyncMock(), AsyncMock()
        await process_one(repo, extractor, projector)
        extractor.assert_not_awaited()
        projector.put_facts.assert_not_awaited()
        repo.finish_distillation.assert_not_awaited()

    async def test_reclaimed_exhausted_lease_fails_without_another_extraction(self):
        repo = self.repo()
        repo.claim_distillation.return_value = {'job_id': 1, 'customer_id': 'C1',
            'session_id': str(uuid4()), 'source_turn_id': str(uuid4()), 'attempts': 6}
        repo.is_erasure_blocked.return_value = False
        repo.distillation_turn.return_value = {'customer_text': 'Chào',
            'agent_text': 'Dạ', 'on_date': '2026-10-15', 'channel': 'hotline'}
        extractor, projector = AsyncMock(return_value=([], None)), AsyncMock()
        projector.list_fact_versions.return_value = []
        projector.list_episode_versions.return_value = []
        await process_one(repo, extractor, projector)
        extractor.assert_not_awaited()
        projector.put_facts.assert_not_awaited()
        assert repo.finish_distillation.await_args.args[2:] == ('failed', 'lease_attempts_exhausted')
