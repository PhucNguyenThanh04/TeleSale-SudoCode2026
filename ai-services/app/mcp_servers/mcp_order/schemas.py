"""Validated BTC order tool inputs and private operation context."""

from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field


class Context(BaseModel):
    source_channel: str | None = None
    source_identity: str | None = None
    operation_key: str | None = None


class CreateInput(Context):
    customer_phone: str
    sku: str = Field(min_length=1)
    qty: int = Field(ge=1)
    price_vnd: int = Field(ge=0)
    payment: Literal["COD", "bank", "momo", "zalopay"]
    on: date
    promo_code: str | None = None
    address: str | None = None
    basket_skus: list[str] | None = None


class StatusInput(Context):
    order_id: str | None = None
    customer_phone: str | None = None

class UpdateInput(Context):
    order_id: str
    action: Literal["exchange_size", "exchange_product", "return", "update_address"]
    on: date
    new_variant_sku: str | None = None
    reason: str | None = None


class CallbackInput(Context):
    customer_phone: str
    callback_at: datetime
    note: str | None = None


class HandoffInput(Context):
    brief: dict
