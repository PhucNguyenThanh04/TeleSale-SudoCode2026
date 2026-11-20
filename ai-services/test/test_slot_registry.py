
import unittest
from dataclasses import FrozenInstanceError

from app.agent.guardrails.checks import fact_evidence
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
            Slot.OWNED_SKU, Slot.CALLBACK_SCHEDULED, Slot.ALT_SUGGESTED,
        })
        self.assertEqual(BRIEF_MUST_NOT_ASK_KEYS, (
            Slot.ROOM_AREA_M2, Slot.BUDGET_VND, Slot.HAS_CHILDREN,
            Slot.PRODUCT_ADVISED, Slot.PRICE_QUOTED_VND,
            Slot.PREFERRED_SIZE, Slot.PREFERRED_COLOR, Slot.ORDER_ID,
            Slot.COMPETITOR_PRICE_VND, Slot.SIZE, Slot.COLOR, Slot.PAYMENT,
        ))



if __name__ == "__main__":
    unittest.main()
