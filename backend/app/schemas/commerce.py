"""Order and callback tool boundaries owned by the backend."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from .common import NonNegativeVND, PaymentMethod, PhoneNumber


class OrderCreate(BaseModel):
    customer_phone: PhoneNumber
    sku: str
    qty: int = Field(default=1, ge=1)
    price_vnd: NonNegativeVND | None = None
    promo_code: str | None = None
    payment: PaymentMethod = "COD"
    address: str | None = None
    on: dt.date
    basket_skus: list[str] = Field(default_factory=list)


class OrderCreated(BaseModel):
    order_id: str
    status: str
    total_vnd: NonNegativeVND
    needs_confirmation_call: bool = False
    estimated_delivery: str | None = None


class OrderStatusQuery(BaseModel):
    order_id: str | None = None
    customer_phone: PhoneNumber | None = None


class OrderStatusRecord(BaseModel):
    order_id: str
    sku: str
    status: str
    price_vnd: NonNegativeVND
    customer_phone: PhoneNumber | None = None
    qty: int | None = None
    total_vnd: NonNegativeVND | None = None
    date: dt.date | None = None
    created_on: dt.date | None = None
    tracking: str | None = None


class OrderStatusResult(BaseModel):
    orders: list[OrderStatusRecord]


class OrderUpdate(BaseModel):
    order_id: str
    action: Literal["exchange_size", "exchange_product", "return", "update_address"]
    new_variant_sku: str | None = None
    reason: str | None = None
    on: dt.date


class OrderUpdateResult(BaseModel):
    order_id: str
    status: str
    fee_vnd: NonNegativeVND | None = None
    price_diff_vnd: int | None = None
    refund_vnd: NonNegativeVND | None = None
    extra_payment_vnd: NonNegativeVND | None = None
    refund_days: str | None = None


class CallbackSchedule(BaseModel):
    customer_phone: PhoneNumber
    callback_at: dt.datetime
    note: str | None = None


class CallbackScheduled(BaseModel):
    callback_id: str
    customer_phone: PhoneNumber
    callback_at: dt.datetime
    moved_from: dt.datetime | None = None
    note: str | None = None
