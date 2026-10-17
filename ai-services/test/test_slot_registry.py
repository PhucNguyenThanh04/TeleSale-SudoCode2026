"""The slot registry preserves the existing memory and brief contracts."""

import unittest
from dataclasses import FrozenInstanceError

from app.agent.guardrails.checks import fact_evidence
from app.agent.memory.fact_candidates import _CUSTOMER_KEYS, accepted_candidates
from app.constants import (
    BRIEF_MUST_NOT_ASK_KEYS, PROFILE_SLOT_KEYS, SLOT_REGISTRY,
    TOOL_ONLY_SLOT_KEYS, Slot,
)


class SlotRegistryTests(unittest.TestCase):
    def test_each_existing_slot_has_one_immutable_spec(self):
        declared = {value for name, value in vars(Slot).items()
                    if name.isupper() and isinstance(value, str)}
        keys = [spec.key for spec in SLOT_REGISTRY]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), declared)
        with self.assertRaises(FrozenInstanceError):
            SLOT_REGISTRY[0].key = "changed"

    def test_generated_views_keep_existing_keys_and_brief_order(self):
        self.assertEqual(PROFILE_SLOT_KEYS, {spec.key for spec in SLOT_REGISTRY})
        self.assertEqual(TOOL_ONLY_SLOT_KEYS, {
            Slot.PRODUCT_ADVISED, Slot.PRICE_QUOTED_VND, Slot.PROMO_CODE,
            Slot.PROMO_EXPIRY, Slot.ORDER_ID, Slot.IN_STOCK, Slot.VARIANT_SKU,
        })
        self.assertEqual(BRIEF_MUST_NOT_ASK_KEYS, (
            Slot.ROOM_AREA_M2, Slot.BUDGET_VND, Slot.HAS_CHILDREN,
            Slot.PRODUCT_ADVISED,
        ))
        self.assertEqual(_CUSTOMER_KEYS,
                         sorted(PROFILE_SLOT_KEYS - TOOL_ONLY_SLOT_KEYS))

    def test_customer_and_tool_evidence_gates_are_unchanged(self):
        self.assertEqual(fact_evidence(Slot.BUDGET_VND, 5_000_000, "set",
                                       "Ngân sách tôi 5 triệu", []), "customer")
        self.assertIsNone(fact_evidence(Slot.PRODUCT_ADVISED, "SKU-AP-X", "set",
                                        "Tôi thích SKU-AP-X", []))
        calls = [{"name": "catalog.search", "args": {"query": "máy lọc"},
                  "result": {"items": [{"sku": "SKU-AP-X", "name": "AirPure X"}]}}]
        proposals = [{"key": Slot.PRODUCT_ADVISED, "value": "SKU-AP-X"}]
        self.assertEqual(accepted_candidates("Tư vấn giúp tôi", calls, proposals,
                                             "Em gợi ý AirPure X ạ.")[0]["source_kind"],
                         "tool")
        self.assertEqual(accepted_candidates("Tư vấn giúp tôi", calls, proposals,
                                             "Em sẽ kiểm tra thêm ạ."), [])


if __name__ == "__main__":
    unittest.main()
