"""Namespace and serialization boundaries for the derived LangGraph store."""

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

from app.mcp_servers.mcp_memory.repos.langmem_projection import LangMemProjection


class FakeStore:
    def __init__(self):
        self.rows = {}

    async def put(self, namespace, key, value, index=False):
        self.rows[namespace, key] = value

    async def search(self, namespace_prefix, *, limit=10):
        return [SimpleNamespace(namespace=ns, key=key, value=value)
                for (ns, key), value in self.rows.items()
                if ns[:len(namespace_prefix)] == namespace_prefix][:limit]

    async def delete(self, namespace, key):
        self.rows.pop((namespace, key), None)


class ProjectionTests(unittest.IsolatedAsyncioTestCase):
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
