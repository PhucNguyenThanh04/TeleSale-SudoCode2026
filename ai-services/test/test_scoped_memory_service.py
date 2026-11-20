
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from app.mcp_servers.mcp_memory.services.memory import read
from app.schemas.trace import TraceMemoryWrite
from test_mcp_memory import TurnRepo


class ScopedMemoryServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_trace_keeps_scope_for_a_real_memory_write(self):
        trace = TraceMemoryWrite.model_validate({
            "customer_id": "C901", "key": "room_area_m2", "value": 12,
            "op": "set", "source": "session:turn", "scope_type": "room",
            "scope_id": "phong_ngu"})
        self.assertEqual(trace.model_dump()["scope_id"], "phong_ngu")

    async def test_room_and_product_facts_are_read_from_store(self):
        class Repo(TurnRepo):
            async def order_links(self, *_):
                return []

        session = str(uuid4())
        projection = AsyncMock()
        projection.list_fact_versions.return_value = [
            {"key": "room_area_m2", "value": 12, "scope_type": "room",
             "scope_id": "phong_ngu", "source_kind": "customer", "schema_version": 1,
             "session_id": session},
            {"key": "price_quoted_vnd", "value": 2_000_000, "scope_type": "product",
             "scope_id": "SKU-AP-MINI", "source_kind": "tool", "schema_version": 1,
             "session_id": session},
        ]
        projection.list_episode_versions.return_value = []
        loaded = await read(Repo(), "C901", session, projector=projection)
        self.assertEqual(loaded["scoped_facts"]["room"]["phong_ngu"]
                         ["room_area_m2"]["value"], 12)
        self.assertEqual(loaded["scoped_facts"]["product"]["SKU-AP-MINI"]
                         ["price_quoted_vnd"]["value"], 2_000_000)

    async def test_valid_until_and_widened_product_room_scopes_round_trip(self):
        from app.constants import BRIEF_MUST_NOT_ASK_KEYS, Slot
        from app.mcp_servers.mcp_memory.services.memory import _valid_fact

        class Repo(TurnRepo):
            async def order_links(self, *_):
                return []

        session = str(uuid4())
        projection = AsyncMock()
        projection.list_fact_versions.return_value = [
            {"key": "promo_expiry", "value": "2026-10-20", "valid_until": "2026-10-20",
             "scope_type": "product", "scope_id": "SKU-AP-X", "source_kind": "tool",
             "source_tool": "pricing.get_quote", "schema_version": 1, "session_id": session},
            {"key": "preferred_size", "value": 39, "scope_type": "product",
             "scope_id": "SKU-SN-CAS", "source_kind": "customer", "schema_version": 1,
             "session_id": session},
            {"key": "preferred_color", "value": "den", "scope_type": "product",
             "scope_id": "SKU-SN-CAS", "source_kind": "customer", "schema_version": 1,
             "session_id": session},
            {"key": "has_children", "value": True, "scope_type": "room",
             "scope_id": "phong_ngu", "source_kind": "customer", "schema_version": 1,
             "session_id": session},
        ]
        projection.list_episode_versions.return_value = []
        loaded = await read(Repo(), "C901", session, projector=projection)
        self.assertEqual(loaded["scoped_facts"]["product"]["SKU-AP-X"]
                         ["promo_expiry"]["valid_until"], "2026-10-20")
        self.assertEqual(loaded["scoped_facts"]["product"]["SKU-SN-CAS"]
                         ["preferred_size"]["value"], 39)
        self.assertEqual(loaded["scoped_facts"]["product"]["SKU-SN-CAS"]
                         ["preferred_color"]["value"], "den")
        self.assertIs(loaded["scoped_facts"]["room"]["phong_ngu"]
                      ["has_children"]["value"], True)
        self.assertFalse(_valid_fact({
            "key": "promo_expiry", "value": "2026-10-20", "op": "set",
            "source_kind": "tool", "source_tool": "pricing.get_quote",
            "scope_type": "product", "scope_id": "SKU-AP-X",
            "valid_until": "not-a-date"}))
        for expected in (Slot.PRICE_QUOTED_VND, Slot.COMPETITOR_PRICE_VND,
                         Slot.ORDER_ID, Slot.SIZE, Slot.PREFERRED_SIZE,
                         Slot.COLOR, Slot.PREFERRED_COLOR, Slot.PAYMENT):
            self.assertIn(expected, BRIEF_MUST_NOT_ASK_KEYS)
        for excluded in (Slot.BLOCKER, Slot.OBJECTION, Slot.IN_STOCK):
            self.assertNotIn(excluded, BRIEF_MUST_NOT_ASK_KEYS)
