
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from app.mcp_servers.mcp_catalog.schemas import QuoteLine


class Context(BaseModel):
    source_channel: str | None = None
    source_identity: str | None = None
    operation_key: str | None = None


class WriteInput(Context):
    trusted_authorization: str | None = None


class OrderLine(QuoteLine):
    price_vnd: int = Field(ge=0, strict=True)


class CreateInput(WriteInput):
    customer_phone: str
    sku: str | None = Field(default=None, min_length=1)
    qty: int = Field(default=1, ge=1, strict=True)
    price_vnd: int | None = Field(default=None, ge=0, strict=True)
    lines: list[OrderLine] | None = Field(default=None, min_length=1)
    payment: Literal["COD", "bank", "momo", "zalopay"]
    on: date
    promo_code: str | None = None
    address: str | None = None
    basket_skus: list[str] | None = None

    @model_validator(mode='after')
    def require_one_order_form(self):
        if self.lines is not None:
            if self.sku is not None or self.price_vnd is not None or self.basket_skus or self.qty != 1:
                raise ValueError('Use either single SKU or lines')
        elif self.sku is None or self.price_vnd is None:
            raise ValueError('Single SKU requires price_vnd')
        return self


class StatusInput(Context):
    order_id: str | None = None
    customer_phone: str | None = None

class UpdateInput(WriteInput):
    order_id: str
    action: Literal["exchange_size", "exchange_product", "return", "update_address"]
    on: date
    new_variant_sku: str | None = None
    reason: str | None = None


class CallbackInput(WriteInput):
    customer_phone: str
    callback_at: datetime
    note: str | None = None


class HandoffInput(WriteInput):
    brief: dict
