"""Pure commerce rules and service replay checks."""

import importlib.util
import json
import unittest
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

from app.mcp_servers.mcp_shared.commerce_rules import _catalog, _inventory, quote
from app.mcp_servers.mcp_order.services.order import invoke as invoke_order

BTC = Path(__file__).resolve().parents[3] / "BTC-Data-Vong1-TEAMS"


class FakeOrderRepo:
    def __init__(self):
        self.operations = {}
        self.handoffs = 0

    @asynccontextmanager
    async def transaction(self):
        yield object()

    async def identity_matches(self, *_):
        return [{"customer_id": "C001", "phone": "0984726714"}]

    async def claim_operation(self, _session, key, name, digest):
        previous = self.operations.get(key)
        if previous and previous[0:2] != (name, digest):
            return {"error": "operation_key_conflict"}
        return previous[2] if previous else None

    async def finish_operation(self, _session, key, result):
        self.operations[key] = ("handoff.transfer", self.digest, result)

    async def insert_handoff(self, _session, _brief):
        self.handoffs += 1
        return self.handoffs


class BusinessTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("btc_mock_for_mcp", BTC / "eval/mock_tools.py")
        cls.mock = importlib.util.module_from_spec(spec)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            spec.loader.exec_module(cls.mock)
        cls.products = json.loads((BTC / "catalog/products.json").read_text())["products"]
        cls.events = json.loads((BTC / "catalog/inventory_timeline.json").read_text())["events"]
        cls.promos = json.loads((BTC / "catalog/promotions.json").read_text())["promotions"]

    async def test_catalog_inventory_and_quote_match_btc(self):
        self.assertEqual(_catalog(self.products, {"sku": "SKU-AP-X"}),
                         self.mock.catalog_search(sku="SKU-AP-X"))
        self.assertEqual(_inventory(self.products, self.events, "SKU-AP-X", "2026-10-15"),
                         self.mock.inventory_check("SKU-AP-X", "2026-10-15"))
        args = {"sku": "SKU-AP-X", "on": "2026-10-15", "basket_skus": ["SKU-SS-AX40"]}
        expected = self.mock.pricing_get_quote(**args)
        expected.pop("_internal_price_floor_vnd")
        self.assertEqual(quote(self.products, self.promos, args), expected)

    async def test_handoff_replay_does_not_write_twice(self):
        repo = FakeOrderRepo()
        args = {"brief": {"customer_phone": "0984726714", "customer_name": "Lan",
            "escalation_reason": "test", "conversation_summary": "test",
            "product_advised": [], "price_quoted_vnd": None, "open_questions": [],
            "next_action": "call", "generated_at": "2026-10-15T10:00:00"},
            "source_channel": "hotline", "source_identity": "0984726714", "operation_key": "key-1"}
        import hashlib
        clean = {k: v for k, v in args.items() if k != "operation_key"}
        repo.digest = hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        first = await invoke_order(repo, "handoff.transfer", args)
        second = await invoke_order(repo, "handoff.transfer", args)
        self.assertEqual(first, second)
        self.assertEqual(repo.handoffs, 1)

    async def test_ambiguous_order_identity_is_rejected(self):
        repo = FakeOrderRepo()
        async def ambiguous(*_):
            return [{"customer_id": "C001", "phone": "0958421083"},
                    {"customer_id": "C002", "phone": "0958421083"}]
        repo.identity_matches = ambiguous
        result = await invoke_order(repo, "order.status", {"order_id": "OD600001",
            "source_channel": "hotline", "source_identity": "0958421083"})
        self.assertEqual(result, {"error": "identity_required"})


if __name__ == "__main__":
    unittest.main()
