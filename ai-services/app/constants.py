"""Shared non-policy limits for the AI service and MCP catalog."""

from dataclasses import dataclass
from typing import Literal

CATALOG_RESULT_LIMIT = 20
DEFAULT_MAX_TOOL_CALLS = 3
DEFAULT_PROMPT_HISTORY_TURNS = 6


class Slot:
    ROOM_AREA_M2 = "room_area_m2"
    HAS_CHILDREN = "has_children"
    BUDGET_VND = "budget_vnd"
    PRODUCT_ADVISED = "product_advised"
    PRICE_QUOTED_VND = "price_quoted_vnd"
    PROMO_CODE = "promo_code"
    PROMO_EXPIRY = "promo_expiry"
    BLOCKER = "blocker"
    PREFERRED_SIZE = "preferred_size"
    PREFERRED_COLOR = "preferred_color"
    ORDER_ID = "order_id"
    IN_STOCK = "in_stock"
    COMPETITOR_PRICE_VND = "competitor_price_vnd"
    OBJECTION = "objection"
    VARIANT_SKU = "variant_sku"
    SIZE = "size"
    COLOR = "color"
    PAYMENT = "payment"


@dataclass(frozen=True)
class SlotSpec:
    """One slot's declared contract; admission rules remain in fact_evidence."""

    key: str
    value_type: type | tuple[type, ...]
    evidence_source: Literal["customer", "tool"]
    store_in_profile: bool = True
    brief_must_not_ask: bool = False
    supersede: Literal["replace", "append"] = "replace"
    context_negation: Literal["none", "polar", "selection", "obstacle"] = "none"


# Keep brief-marked entries in their existing display order. Types and supersede
# are descriptive until the validator and storage are migrated in later steps.
SLOT_REGISTRY = (
    SlotSpec(Slot.ROOM_AREA_M2, int, "customer", brief_must_not_ask=True),
    SlotSpec(Slot.BUDGET_VND, int, "customer", brief_must_not_ask=True),
    SlotSpec(Slot.HAS_CHILDREN, bool, "customer", brief_must_not_ask=True,
             context_negation="polar"),
    SlotSpec(Slot.PRODUCT_ADVISED, str, "tool", brief_must_not_ask=True),
    SlotSpec(Slot.PRICE_QUOTED_VND, int, "tool"),
    SlotSpec(Slot.PROMO_CODE, str, "tool"),
    SlotSpec(Slot.PROMO_EXPIRY, str, "tool"),
    SlotSpec(Slot.BLOCKER, str, "customer", context_negation="obstacle"),
    SlotSpec(Slot.PREFERRED_SIZE, (str, int), "customer", context_negation="selection"),
    SlotSpec(Slot.PREFERRED_COLOR, str, "customer", context_negation="selection"),
    SlotSpec(Slot.ORDER_ID, str, "tool"),
    SlotSpec(Slot.IN_STOCK, bool, "tool", context_negation="polar"),
    SlotSpec(Slot.COMPETITOR_PRICE_VND, int, "customer"),
    SlotSpec(Slot.OBJECTION, str, "customer"),
    SlotSpec(Slot.VARIANT_SKU, str, "tool"),
    SlotSpec(Slot.SIZE, (str, int), "customer", context_negation="selection"),
    SlotSpec(Slot.COLOR, str, "customer", context_negation="selection"),
    SlotSpec(Slot.PAYMENT, str, "customer", context_negation="selection"),
)

SLOT_SPEC_BY_KEY = {spec.key: spec for spec in SLOT_REGISTRY}

PROFILE_SLOT_KEYS = frozenset(spec.key for spec in SLOT_REGISTRY
                              if spec.store_in_profile)
BRIEF_MUST_NOT_ASK_KEYS = tuple(spec.key for spec in SLOT_REGISTRY
                                if spec.brief_must_not_ask)
TOOL_ONLY_SLOT_KEYS = frozenset(spec.key for spec in SLOT_REGISTRY
                                if spec.evidence_source == "tool")
