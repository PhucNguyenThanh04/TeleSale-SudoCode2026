"""BTC product, promotion, inventory and price quote contracts."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from .common import NonNegativeVND, PhoneNumber


class ProductVariant(BaseModel):
    variant_sku: str
    size: int | str | None = None
    color: str | None = None
    price_delta_vnd: int = 0
    stock: int = Field(default=0, ge=0)


class Product(BaseModel):
    sku: str
    name: str
    category: str
    brand: str
    list_price_vnd: NonNegativeVND
    attributes: dict[str, Any] = Field(default_factory=dict)
    stock: int = Field(ge=0)
    variants: list[ProductVariant] = Field(default_factory=list)


class ProductCatalog(BaseModel):
    reference_date: date
    currency: Literal["VND"]
    products: list[Product]


class PromotionConditions(BaseModel):
    exclude_variant_size: list[int | str] | None = None
    once_per_customer: bool | None = None
    min_qty: int | None = Field(default=None, ge=1)
    region: list[str] | None = None
    requires_owned_sku: str | None = None


class Promotion(BaseModel):
    promo_code: str
    name: str
    applies_to: list[str]
    type: Literal["fixed", "percent", "percent_second_item", "gift", "freeship", "freecod"]
    discount_vnd: NonNegativeVND
    start: date
    end: date
    stackable: bool
    discount_percent: float | None = Field(default=None, ge=0, le=100)
    gift_sku: str | None = None
    min_order_vnd: NonNegativeVND | None = None
    conditions: PromotionConditions | None = None


class PromotionsCatalog(BaseModel):
    reference_date: date
    promotions: list[Promotion]


class InventoryEvent(BaseModel):
    sku: str
    date: date
    qty: int = Field(ge=0)
    note: str | None = None


class InventoryTimeline(BaseModel):
    reference_date: date
    rule: str
    events: list[InventoryEvent]


class CatalogSearch(BaseModel):
    query: str | None = None
    category: str | None = None
    sku: str | None = None
    max_price_vnd: NonNegativeVND | None = None
    min_room_area_m2: float | None = Field(default=None, ge=0)
    include_discontinued: bool = False


class CatalogItem(BaseModel):
    sku: str
    name: str
    category: str | None = None
    list_price_vnd: NonNegativeVND
    attributes: dict[str, Any] = Field(default_factory=dict)
    variants: list[ProductVariant] = Field(default_factory=list)


class CatalogSearchResult(BaseModel):
    items: list[CatalogItem]
    total: int = Field(ge=0)


class InventoryCheck(BaseModel):
    sku: str
    on: date


class InventoryResult(BaseModel):
    sku: str
    in_stock: bool
    qty: int = Field(ge=0)
    restock_expected: date | None = None
    discontinued: bool = False
    successor_sku: str | None = None


class PriceQuoteRequest(BaseModel):
    sku: str
    on: date
    qty: int = Field(default=1, ge=1)
    customer_phone: PhoneNumber | None = None
    address: str | None = None
    basket_skus: list[str] = Field(default_factory=list)


class AppliedPromotion(BaseModel):
    promo_code: str
    type: str
    discount_vnd: NonNegativeVND = 0
    gift_sku: str | None = None


class IneligiblePromotion(BaseModel):
    promo_code: str
    reason: str


class PriceQuote(BaseModel):
    sku: str
    list_price_vnd: NonNegativeVND
    final_price_vnd: NonNegativeVND
    applied_promos: list[AppliedPromotion] = Field(default_factory=list)
    expired_promos: list[str] = Field(default_factory=list)
    ineligible_promos: list[IneligiblePromotion] = Field(default_factory=list)
    not_applied_exclusive: list[str] = Field(default_factory=list)
    freeship: bool = False

    # The mock tool also returns _internal_price_floor_vnd. Pydantic ignores it:
    # it is not part of the agent/customer-facing quote contract.
