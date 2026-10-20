"""Scoped facts keep independent product and room histories."""

import json
import unittest
from contextlib import asynccontextmanager
from uuid import uuid4

from app.mcp_servers.mcp_memory.services.memory import read, write
from app.schemas.trace import TraceMemoryWrite


class ScopedRepo:
    def __init__(self):
        self.records = {}
        self.turns = []

    @asynccontextmanager
    async def transaction(self):
        yield object()

    async def lock_key(self, *_):
        pass

    async def active_fact_record(self, _conn, customer_id, key, scope_type="global", scope_id=""):
        return self.records.get((customer_id, scope_type, scope_id, key))

    async def set_fact_status(self, _conn, fact_id, status):
        for record in self.records.values():
            if record["fact_id"] == fact_id:
                record["status"] = status

    async def insert_fact(self, _conn, fact_id, customer_id, key, value, source,
                          session_id, previous, **metadata):
        scope_type = metadata.get("scope_type", "global")
        scope_id = metadata.get("scope_id", "")
        self.records[(customer_id, scope_type, scope_id, key)] = {
            "fact_id": fact_id, "key": key, "value": json.dumps(value),
            "source": source, "status": "active", "on_date": metadata.get("on_date"),
            "source_kind": metadata.get("source_kind"),
            "source_tool": metadata.get("source_tool"),
            "evidence_quote": metadata.get("evidence_quote"),
            "scope_type": scope_type, "scope_id": scope_id,
        }

    async def owner(self, *_):
        return None

    async def recent_customer_turns(self, *_):
        return []

    async def turn_count(self, *_):
        return 0

    async def facts(self, _conn, customer_id, _session_id, _include_prior):
        return [row for (owner, *_), row in self.records.items()
                if owner == customer_id and row["status"] == "active"]

    async def episodes(self, *_):
        return []

    async def order_links(self, *_):
        return []


class ScopedMemoryServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_trace_keeps_scope_for_a_real_memory_write(self):
        trace = TraceMemoryWrite.model_validate({
            "customer_id": "C901", "key": "room_area_m2", "value": 12,
            "op": "set", "source": "session:turn", "scope_type": "room",
            "scope_id": "phong_ngu"})
        self.assertEqual(trace.model_dump()["scope_id"], "phong_ngu")

    async def test_two_products_and_rooms_remain_separate_and_one_supersedes(self):
        repo = ScopedRepo()
        session = str(uuid4())
        for scope_type, scope_id, key, value in (
            ("product", "SKU-AP-MINI", "price_quoted_vnd", 2_000_000),
            ("product", "SKU-AP-PRO", "price_quoted_vnd", 4_000_000),
            ("room", "phong_ngu", "room_area_m2", 12),
            ("room", "phong_khach", "room_area_m2", 45),
        ):
            result = await write(repo, "fact", "C901", session, {
                "key": key, "value": value, "op": "set", "source": "test",
                "scope_type": scope_type, "scope_id": scope_id})
            self.assertEqual(result["op"], "set")
        await write(repo, "fact", "C901", session, {
            "key": "room_area_m2", "value": 14, "op": "set", "source": "test",
            "scope_type": "room", "scope_id": "phong_ngu"})
        loaded = await read(repo, "C901", session)
        products = loaded["scoped_facts"]["product"]
        rooms = loaded["scoped_facts"]["room"]
        self.assertEqual(products["SKU-AP-MINI"]["price_quoted_vnd"]["value"], 2_000_000)
        self.assertEqual(products["SKU-AP-PRO"]["price_quoted_vnd"]["value"], 4_000_000)
        self.assertEqual(rooms["phong_ngu"]["room_area_m2"]["value"], 14)
        self.assertEqual(rooms["phong_khach"]["room_area_m2"]["value"], 45)

    async def test_global_fact_still_uses_profile_and_invalid_scope_is_rejected(self):
        repo = ScopedRepo()
        session = str(uuid4())
        await write(repo, "fact", "C902", session, {
            "key": "preferred_color", "value": "xanh", "op": "set", "source": "test"})
        loaded = await read(repo, "C902", session)
        self.assertEqual(loaded["profile"]["preferred_color"]["value"], "xanh")
        invalid = await write(repo, "fact", "C902", session, {
            "key": "price_quoted_vnd", "value": 1_000_000, "op": "set",
            "source": "test", "scope_type": "product", "scope_id": ""})
        self.assertEqual(invalid, {"error": "invalid_scope"})
