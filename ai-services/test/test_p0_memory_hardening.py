import asyncio
from datetime import date
from uuid import uuid4

import pytest

from app.agent.guardrails.checks import safe_tool_result
from app.agent.harness.context import _split_facts
from app.agent.memory.deterministic_tool_facts import (
    deterministic_episode_tools,
    verified_order_details,
)
from app.mcp_servers.mcp_memory.repos.langmem_projection import LangMemProjection
from eval_harness.benchmark_runner import assert_trace_ready


def test_p0b_order_create_emits_deterministic_facts_and_episode_details():
    call_non_variant = {
        "name": "order.create",
        "args": {"sku": "SKU-AP-X", "qty": 1, "price_vnd": 4890000, "payment": "COD"},
        "result": {
            "order_id": "OD10001",
            "status": "created",
            "total_vnd": 4890000,
            "estimated_delivery": "2026-10-20",
        },
    }
    facts = verified_order_details(call_non_variant, None, str(uuid4()))
    keys = {(f["scope_type"], f["key"]): f["value"] for f in facts}
    assert keys[("global", "order_id")] == "OD10001"
    assert keys[("product", "product_advised")] == "SKU-AP-X"
    assert keys[("product", "payment")] == "COD"

    call_variant = {
        "name": "order.create",
        "args": {"sku": "SKU-SN-CAS-39-DEN", "qty": 1, "price_vnd": 890000, "payment": "bank"},
        "result": {
            "order_id": "OD10002",
            "status": "created",
            "total_vnd": 890000,
            "estimated_delivery": "2026-10-22",
        },
    }
    variant = {"variant_sku": "SKU-SN-CAS-39-DEN", "parent_sku": "SKU-SN-CAS", "size": "39", "color": "den"}
    v_facts = verified_order_details(call_variant, variant, str(uuid4()))
    v_keys = {(f["scope_type"], f["key"]): f["value"] for f in v_facts}
    assert v_keys[("global", "order_id")] == "OD10002"
    assert v_keys[("product", "size")] == 39
    assert v_keys[("product", "color")] == "den"
    assert v_keys[("product", "payment")] == "bank"

    actions, _ = deterministic_episode_tools([call_non_variant], "2026-10-15")
    assert len(actions) == 1
    assert actions[0]["order_id"] == "OD10001"
    assert actions[0]["status"] == "created"
    assert actions[0]["total_vnd"] == 4890000
    assert actions[0]["estimated_delivery"] == "2026-10-20"


def test_p0c_supersede_marks_old_version_and_skips_identical_value():
    class FakeItem:
        def __init__(self, namespace, key, value):
            self.namespace = namespace
            self.key = key
            self.value = value

    class FakeStore:
        def __init__(self):
            self.data = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def asearch(self, namespace, limit=200, offset=0):
            items = [FakeItem(ns, k, v) for (ns, k), v in self.data.items() if ns == namespace]
            return items[offset:offset + limit]

        async def aget(self, namespace, key):
            v = self.data.get((namespace, key))
            return FakeItem(namespace, key, v) if v is not None else None

        async def aput(self, namespace, key, value, index=False):
            self.data[(namespace, key)] = value

    store = FakeStore()
    proj = LangMemProjection("postgresql://u:p@localhost:5432/db")

    from unittest.mock import patch

    async def run():
        fact_v1 = {"key": "budget_vnd", "value": 5000000, "op": "set", "source_kind": "customer",
                   "scope_type": "global", "scope_id": "", "evidence_quote": "5 triệu"}
        fact_same = {**fact_v1}
        fact_v2 = {**fact_v1, "value": 6000000, "evidence_quote": "6 triệu"}
        with patch("app.mcp_servers.mcp_memory.repos.langmem_projection.AsyncPostgresStore.from_conn_string", return_value=store):
            w1 = await proj.put_facts("C1", "S1", str(uuid4()), "2026-10-15", [fact_v1], revision=1, completed_revisions={1})
            assert len(w1) == 1
            assert w1[0]["op"] == "set"

            w_same = await proj.put_facts("C1", "S1", str(uuid4()), "2026-10-16", [fact_same], revision=2, completed_revisions={1, 2})
            assert w_same == []

            w2 = await proj.put_facts("C1", "S1", str(uuid4()), "2026-10-17", [fact_v2], revision=3, completed_revisions={1, 2, 3})
            assert len(w2) == 1
            assert w2[0]["op"] == "supersede"

        ns = proj.fact_namespace("C1")
        v1_key = '["global","","budget_vnd",1]'
        v2_key = '["global","","budget_vnd",2]'
        v3_key = '["global","","budget_vnd",3]'
        assert (ns, v2_key) not in store.data
        assert store.data[(ns, v1_key)].get("status") == "superseded"
        assert store.data[(ns, v1_key)].get("superseded_by_revision") == 3
        assert store.data[(ns, v3_key)]["value"] == 6000000

    asyncio.run(run())


def test_p0d_fact_ttl_expires_old_facts_by_business_date():
    profile = {
        "budget_vnd": {"key": "budget_vnd", "value": 5000000, "status": "active", "source_kind": "customer", "on": "2026-01-01"},
        "room_area_m2": {"key": "room_area_m2", "value": 25, "status": "active", "source_kind": "customer", "on": "2026-09-01"},
    }
    customer_default, _ = _split_facts(profile, on=date(2026, 10, 15))
    assert "budget_vnd" not in customer_default
    assert "room_area_m2" in customer_default

    customer_long_ttl, _ = _split_facts(profile, on=date(2026, 10, 15), fact_ttl_days=365)
    assert "budget_vnd" in customer_long_ttl
    assert "room_area_m2" in customer_long_ttl


def test_p0e_assert_trace_ready_does_not_crash_on_memory_error():
    scenarios = {
        "S1": {"calls": {"call_1": {"customer_turns": ["Hi"]}}}
    }
    trace = {
        ("S1", "call_1"): [
            {"scenario_id": "S1", "call": "call_1", "turn": 1, "agent_text": "Chào bạn.", "memory_error": "job_failed"}
        ]
    }
    assert_trace_ready(scenarios, trace)


def test_p0f_safe_tool_result_enforces_per_tool_allowlist():
    raw = {
        "sku": "SKU-AP-X",
        "in_stock": True,
        "qty": 5,
        "internal_cost_vnd": 1200000,
        "supplier_secret": "ACME",
        "_debug": "hidden",
    }
    filtered = safe_tool_result(raw, tool_name="inventory.check")
    assert filtered == {"sku": "SKU-AP-X", "in_stock": True, "qty": 5}
