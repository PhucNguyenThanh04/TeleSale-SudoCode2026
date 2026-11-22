
from datetime import date
from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt, StrictStr


AttributeFilters = dict[str, StrictStr | StrictInt | StrictFloat | StrictBool]


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
    attribute_filters: AttributeFilters | None = None


class InventoryInput(BaseModel):
    sku: str = Field(min_length=1)
    on: date


class DetailsInput(BaseModel):
    sku: str = Field(min_length=1)


class QuoteInput(InventoryInput):
    qty: int = Field(default=1, ge=1)
    customer_phone: str | None = None
    address: str | None = None
    basket_skus: list[str] | None = None
    source_channel: str | None = None
    source_identity: str | None = None
    trusted_identity: str | None = None


class QuoteLine(BaseModel):
    sku: str = Field(min_length=1)
    qty: int = Field(default=1, ge=1, strict=True)


class OrderQuoteInput(BaseModel):
    lines: list[QuoteLine] = Field(min_length=1)
    on: date
    customer_phone: str | None = None
    address: str | None = None
    source_channel: str | None = None
    source_identity: str | None = None
    trusted_identity: str | None = None
