"""Accepted recall stays within canonical customer and source boundaries."""

import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from app.agent.harness.context import rank_episodes
from app.mcp_servers.mcp_memory.services.memory import read
from test_mcp_memory import TurnRepo


def episode(session, summary, on="2026-10-15", topics=None):
    return {"session_id": session, "channel": "hotline", "on": on,
            "summary": summary, "outcome": "khac", "status": "active",
            "topics": topics or [], "resolved_prior_items": []}


class RecallTests(unittest.IsolatedAsyncioTestCase):
    async def test_primary_store_episode_is_served_without_legacy_episode_query(self):
        class Repo(TurnRepo):
            def __init__(self):
                super().__init__()
                del self.facts
            async def facts(self, *_):
                return []
            async def episodes(self, *_):
                raise AssertionError("legacy episodes queried")
            async def order_links(self, *_):
                return []
        repo = Repo()
        projection = AsyncMock()
        projection.list_fact_versions.return_value = []
        projection.list_episode_versions.return_value = [
            {**episode("prior", "đúng"), "schema_version": 1}]
        result = await read(repo, "C1", str(uuid4()),
                            langmem_mode="enabled", projector=projection)
        self.assertEqual([item["session_id"] for item in result["episodes"]], ["prior"])
        projection.list_episode_versions.assert_awaited_once_with("C1")

    async def test_primary_store_outage_fails_closed(self):
        class Repo(TurnRepo):
            def __init__(self):
                super().__init__()
                del self.facts
            async def facts(self, *_):
                return []
            async def episodes(self, *_):
                return []
            async def order_links(self, *_):
                return []
        projection = AsyncMock()
        projection.list_fact_versions.return_value = []
        projection.list_episode_versions.side_effect = OSError("offline")
        result = await read(Repo(), "C1", str(uuid4()),
                            langmem_mode="enabled", projector=projection)
        self.assertEqual(result, {"error": "memory_store_unavailable"})

    def test_product_and_open_blocker_outrank_recent_unrelated_episode(self):
        older = episode("old", "SKU-A cần xác nhận", "2026-10-15",
            [{"scope_type": "product", "scope_id": "SKU-A", "items": [
                {"kind": "blocker", "text": "chờ hỏi vợ", "status": "open"}]}])
        recent = episode("new", "SKU-B", "2026-10-20")
        ranked = rank_episodes([recent, older], "SKU-A còn không?", 5)
        self.assertEqual(ranked[0]["session_id"], "old")
