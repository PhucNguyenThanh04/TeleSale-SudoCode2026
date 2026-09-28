"""Call and human handoff briefs matching the BTC JSON Schema fields."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

PhoneNumber = str  # Call Brief permits a broader string; Handoff Brief validates below.
Channel = Literal["hotline", "chat_fanpage", "zalo_oa", "web_chat", "other"]


class PreviousSession(BaseModel):
    session_id: str
    date: date
    channel: Channel
    summary: str
    outcome: Literal["hen_goi_lai", "chot_don", "tu_choi", "chuyen_may", "khac"]


class AdvisedProduct(BaseModel):
    sku: str
    price_quoted_vnd: int | None = Field(default=None, ge=0)
    promo_code: str | None = None
    promo_still_active: bool | None = None
    quoted_on: date | None = None


class BriefOrder(BaseModel):
    order_id: str
    variant_sku: str | None = None
    status: str


class CallBrief(BaseModel):
    customer_phone: PhoneNumber
    is_returning: bool
    n_previous_sessions: int = Field(ge=0)
    last_session: PreviousSession | None
    products_advised: list[AdvisedProduct]
    open_blockers: list[str]
    must_not_ask: list[str]
    suggested_opening: str
    generated_at: datetime
    latency_ms: int = Field(ge=0)
    customer_name: str | None = None
    honorific: str | None = None
    profile_facts: dict[str, Any] = Field(default_factory=dict)
    orders: list[BriefOrder] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    stale_warnings: list[str] = Field(default_factory=list)
    suggested_next_action: str | None = None
    precomputed_parts: list[str] = Field(default_factory=list)


class HandoffBrief(BaseModel):
    customer_phone: str = Field(pattern=r"^0[0-9]{9}$")
    customer_name: str | None
    escalation_reason: Literal[
        "cau_hoi_y_te", "ngoai_pham_vi_tai_lieu", "khach_yeu_cau_gap_nguoi",
        "khieu_nai_nghiem_trong", "loi_he_thong", "khach_mat_kien_nhan", "khac",
    ]
    conversation_summary: str = Field(min_length=20, max_length=800)
    product_advised: str | None
    price_quoted_vnd: int | None = Field(ge=0)
    open_questions: list[str]
    next_action: str
    generated_at: datetime
    customer_id: str | None = None
    channel: Channel | None = None
    escalation_reason_detail: str | None = None
    promo_code: str | None = None
    facts_confirmed: dict[str, Any] = Field(default_factory=dict)
    sentiment: Literal["binh_thuong", "hai_long", "kho_chiu", "gian"] | None = None
    history_refs: list[str] = Field(default_factory=list)
