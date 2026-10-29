"""LangMem proposals remain typed and safe before admission."""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError


class SchemaTests(unittest.TestCase):
    def test_unknown_model_slot_is_rejected(self):
        from app.schemas.langmem import ProfileFactCandidate
        with self.assertRaises(ValidationError):
            ProfileFactCandidate(key="has_small_children", value=True,
                source_kind="customer", source_turn_id="turn-1",
                evidence_quote="có bé nhỏ", observed_on=date(2026, 10, 15))

    def test_opaque_turn_id_does_not_trigger_customer_pii_rule(self):
        from app.schemas.langmem import ProfileFactCandidate
        candidate = ProfileFactCandidate(key="preferred_color", value="xanh",
            source_kind="customer", source_turn_id="00000000-0000-0000-0000-0912345678ab",
            evidence_quote="màu xanh", observed_on=date(2026, 10, 15))
        self.assertEqual(candidate.value, "xanh")

    def test_rejects_raw_phone_in_evidence(self):
        from app.schemas.langmem import ProfileFactCandidate

        with self.assertRaises(ValidationError):
            ProfileFactCandidate(key="budget_vnd", value=5000000, op="set",
                                 source_kind="customer", source_turn_id="turn-1",
                                 evidence_quote="Gọi cho tôi 0912345678",
                                 observed_on=date(2026, 10, 15))

    def test_price_in_episode_is_historical_and_sourced(self):
        from app.schemas.langmem import CustomerCallEpisodeCandidate, QuotedPrice

        episode = CustomerCallEpisodeCandidate(
            customer_id="C001", session_id="session-1", channel="hotline",
            on=date(2026, 10, 15), source_turn_ids=["turn-1"],
            quoted_prices=[QuotedPrice(sku="SKU-AP-X", price_vnd=4890000,
                                       quoted_on=date(2026, 10, 15),
                                       source_tool="pricing.get_quote")])
        self.assertEqual(episode.quoted_prices[0].quoted_on,
                         date(2026, 10, 15))


class ExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def test_masking_keeps_opaque_source_ids(self):
        import json
        from app.agent.memory.langmem_extractor import extract_candidates
        seen = {}
        class Manager:
            async def ainvoke(self, payload):
                seen.update(payload)
                return []
        source_id = "00000000-0000-0000-0000-0912345678ab"
        with patch("app.agent.memory.langmem_extractor.create_memory_manager",
                   return_value=Manager()):
            await extract_candidates(object(), [{"role": "user", "content": json.dumps({
                "turn_id": source_id, "session_id": source_id,
                "customer_text": "Gọi tôi 0912345678"})}], [])
        content = json.loads(seen["messages"][0]["content"])
        self.assertEqual(content["turn_id"], source_id)
        self.assertNotIn("0912345678", content["customer_text"])

    async def test_existing_store_records_are_typed_for_manager(self):
        from app.agent.memory.langmem_extractor import extract_candidates
        seen = {}
        class Manager:
            async def ainvoke(self, payload):
                seen.update(payload)
                return []
        with patch("app.agent.memory.langmem_extractor.create_memory_manager",
                   return_value=Manager()):
            await extract_candidates(object(), [], [{"key": "preferred_color",
                "value": "xanh", "source_kind": "customer",
                "source_turn_id": "turn-1", "evidence_quote": "màu xanh",
                "on": "2026-10-15", "scope_type": "global", "scope_id": ""}])
        self.assertEqual(seen["existing"][0][1].value, "xanh")

    async def test_returns_correction_proposal_and_open_blocker(self):
        from app.agent.memory.langmem_extractor import extract_candidates
        from app.schemas.langmem import ProfileFactCandidate, CustomerCallEpisodeCandidate

        fact = ProfileFactCandidate(key="color", value="trang", op="supersede",
                                    source_kind="customer", source_turn_id="turn-2",
                                    evidence_quote="Thôi anh lấy màu trắng",
                                    observed_on=date(2026, 10, 15))
        episode = CustomerCallEpisodeCandidate(
            customer_id="C001", session_id="session-1", channel="hotline",
            on=date(2026, 10, 15), source_turn_ids=["turn-2"],
            open_blockers=["chờ hỏi chồng"])

        class Manager:
            async def ainvoke(self, payload):
                return [SimpleNamespace(content=fact), SimpleNamespace(content=episode)]

        with patch("app.agent.memory.langmem_extractor.create_memory_manager",
                   return_value=Manager()):
            facts, result = await extract_candidates(object(),
                [{"role": "user", "content": "Thôi anh lấy màu trắng"}], [])
        self.assertEqual(facts[0].op, "supersede")
        self.assertEqual(result.open_blockers, ["chờ hỏi chồng"])

    async def test_noisy_empty_result_proposes_nothing(self):
        from app.agent.memory.langmem_extractor import extract_candidates

        class Manager:
            async def ainvoke(self, payload):
                return [SimpleNamespace(content="not structured")]

        with patch("app.agent.memory.langmem_extractor.create_memory_manager",
                   return_value=Manager()):
            self.assertEqual(await extract_candidates(object(), [], []), ([], None))
