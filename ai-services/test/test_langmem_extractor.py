"""LangMem proposals remain typed and safe before admission."""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError


class SchemaTests(unittest.TestCase):
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
