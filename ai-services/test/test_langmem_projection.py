"""Namespace and serialization boundaries for the derived LangGraph store."""

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

from app.mcp_servers.mcp_memory.repos.langmem_projection import LangMemProjection


class FakeStore:
    def __init__(self):
        self.rows = {}

    async def aput(self, namespace, key, value, index=False):
        self.rows[namespace, key] = value

    async def asearch(self, namespace_prefix, *, limit=10, offset=0):
        return [SimpleNamespace(namespace=ns, key=key, value=value)
                for (ns, key), value in self.rows.items()
                if ns[:len(namespace_prefix)] == namespace_prefix][offset:offset + limit]

    async def adelete(self, namespace, key):
        self.rows.pop((namespace, key), None)

    async def aget(self, namespace, key):
        value = self.rows.get((namespace, key))
        return SimpleNamespace(namespace=namespace, key=key, value=value) if value else None


class ProjectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_job_retry_keeps_original_write_operation(self):
        store = FakeStore()
        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield store
        projection = LangMemProjection("postgresql://user:pass@localhost/test")
        fact = {"key": "preferred_color", "value": "xanh", "op": "set",
                "scope_type": "global", "scope_id": "", "source_kind": "customer",
                "evidence_quote": "màu xanh"}
        with patch("app.mcp_servers.mcp_memory.repos.langmem_projection.AsyncPostgresStore.from_conn_string", connect):
            await projection.put_facts("C1", "s1", "t1", "2026-10-15", [fact], revision=7)
            retry = await projection.put_facts("C1", "s1", "t1", "2026-10-15",
                                               [fact], revision=7)
        self.assertEqual(retry[0]["op"], "set")

    async def test_opaque_ids_survive_masking_while_summary_is_masked(self):
        store = FakeStore()
        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield store
        projection = LangMemProjection("postgresql://user:pass@localhost/test")
        session_id = "00000000-0000-0000-0000-0912345678ab"
        with patch("app.mcp_servers.mcp_memory.repos.langmem_projection.AsyncPostgresStore.from_conn_string", connect):
            await projection.put_episode("C1", session_id, {"summary": "Gọi 0912345678"})
            value = await projection.get_episode("C1", session_id)
        self.assertEqual(value["session_id"], session_id)
        self.assertNotIn("0912345678", value["summary"])

    async def test_customer_namespace_upsert_and_delete(self):
        store = FakeStore()
        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield store
        projection = LangMemProjection("postgresql://user:pass@localhost/test")
        with patch("app.mcp_servers.mcp_memory.repos.langmem_projection.AsyncPostgresStore.from_conn_string", connect):
            canonical = {"summary": "Đang chờ tư vấn", "outcome": "khac",
                         "topics": [], "resolved_prior_items": [], "status": "active"}
            await projection.put_episode("C1", "session-1", canonical)
            await projection.put_episode("C1", "session-1", canonical)
            await projection.put_episode("C2", "session-2", canonical)
            self.assertEqual(len(await projection.list_episodes("C1", 5)), 1)
            self.assertEqual(await projection.delete_customer("C1"), 1)
            self.assertEqual(await projection.delete_customer("C1"), 0)
            self.assertEqual(len(await projection.list_episodes("C2", 5)), 1)

    async def test_primary_fact_upsert_supersedes_and_delete_removes(self):
        store = FakeStore()
        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield store
        projection = LangMemProjection("postgresql://user:pass@localhost/test")
        with patch("app.mcp_servers.mcp_memory.repos.langmem_projection.AsyncPostgresStore.from_conn_string", connect):
            source = {"key": "preferred_color", "value": "xanh", "op": "set",
                      "scope_type": "global", "scope_id": "", "source_kind": "customer",
                      "evidence_quote": "màu xanh"}
            await projection.put_facts("C1", "session-1", "turn-1", "2026-10-15", [source])
            await projection.put_facts("C1", "session-2", "turn-2", "2026-10-16",
                                       [{**source, "value": "trắng", "op": "supersede"}])
            self.assertEqual((await projection.list_facts("C1"))[0]["value"], "trắng")
            self.assertEqual(await projection.list_facts("C2"), [])
            await projection.put_facts("C1", "session-3", "turn-3", "2026-10-17",
                                       [{**source, "op": "delete"}])
            self.assertEqual(await projection.list_facts("C1"), [])

    async def test_older_retry_cannot_revive_deleted_fact(self):
        store = FakeStore()
        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield store
        projection = LangMemProjection("postgresql://user:pass@localhost/test")
        source = {"key": "preferred_color", "value": "xanh", "op": "set",
                  "scope_type": "global", "scope_id": "", "source_kind": "customer",
                  "evidence_quote": "màu xanh"}
        with patch("app.mcp_servers.mcp_memory.repos.langmem_projection.AsyncPostgresStore.from_conn_string", connect):
            self.assertEqual(len(await projection.put_facts("C1", "session-1", "turn-1",
                "2026-10-15", [source], revision=1)), 1)
            self.assertEqual(len(await projection.put_facts("C1", "session-2", "turn-2",
                "2026-10-16", [{**source, "op": "delete"}], revision=2)), 1)
            self.assertEqual(await projection.put_facts("C1", "session-1", "turn-1",
                "2026-10-15", [source], revision=1), [])
            self.assertEqual(await projection.list_facts("C1"), [])
