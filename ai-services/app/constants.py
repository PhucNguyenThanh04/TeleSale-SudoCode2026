"""Shared non-policy limits for the AI service and MCP catalog."""

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


PROFILE_SLOT_KEYS = frozenset({
    Slot.ROOM_AREA_M2, Slot.HAS_CHILDREN, Slot.BUDGET_VND, Slot.PRODUCT_ADVISED,
    Slot.PRICE_QUOTED_VND, Slot.PROMO_CODE, Slot.PROMO_EXPIRY, Slot.BLOCKER,
    Slot.PREFERRED_SIZE, Slot.PREFERRED_COLOR, Slot.ORDER_ID, Slot.IN_STOCK,
    Slot.COMPETITOR_PRICE_VND, Slot.OBJECTION, Slot.VARIANT_SKU,
    Slot.SIZE, Slot.COLOR, Slot.PAYMENT,
})
BRIEF_MUST_NOT_ASK_KEYS = (
    Slot.ROOM_AREA_M2, Slot.BUDGET_VND, Slot.HAS_CHILDREN, Slot.PRODUCT_ADVISED,
)
TOOL_ONLY_SLOT_KEYS = frozenset({
    Slot.PRICE_QUOTED_VND, Slot.PROMO_CODE, Slot.ORDER_ID, Slot.IN_STOCK,
    Slot.VARIANT_SKU,
})
