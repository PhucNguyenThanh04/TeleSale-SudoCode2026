"""BTC catalog tool input validation."""

from datetime import date
from pydantic import BaseModel, Field


class CRMInput(BaseModel):
    phone: str | None = None
    zalo_id: str | None = None
    fb_id: str | None = None

class SearchInput(BaseModel):
    query: str | None = None
    category: str | None = None
    sku: str | None = None
    max_price_vnd: int | None = Field(default=None, ge=0)
    min_room_area_m2: float | None = Field(default=None, ge=0)
    include_discontinued: bool = False


class InventoryInput(BaseModel):
    sku: str = Field(min_length=1)
    on: date


class QuoteInput(InventoryInput):
    qty: int = Field(default=1, ge=1)
    customer_phone: str | None = None
    address: str | None = None
    basket_skus: list[str] | None = None
    source_channel: str | None = None
    source_identity: str | None = None


class PolicySearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    on: date
    order_date: date | None = None
