"""Typed, untrusted proposals from long-term memory distillation."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.mcp_servers.mcp_shared.pii import mask_pii
from app.constants import PROFILE_SLOT_KEYS


FactKey = Literal.__getitem__(tuple(sorted(PROFILE_SLOT_KEYS)))


_IDENTIFIER_FIELDS = {"source_turn_id", "source_turn_ids", "session_id",
                      "customer_id", "scope_id", "sku", "source_tool"}


def _safe_strings(value: Any) -> bool:
    if isinstance(value, str):
        return mask_pii(value) == value
    if isinstance(value, dict):
        return all(_safe_strings(item) for key, item in value.items()
                   if key not in _IDENTIFIER_FIELDS)
    if isinstance(value, (list, tuple)):
        return all(_safe_strings(item) for item in value)
    return True


class SafeProposal(BaseModel):
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def reject_raw_pii(self):
        if not _safe_strings(self.model_dump(mode="json")):
            raise ValueError("proposal contains unmasked PII")
        return self


class ProfileFactCandidate(SafeProposal):
    key: FactKey = Field(description="Use only a supported profile slot. has_children means the customer has a child; budget_vnd and room_area_m2 are numeric slots.")
    value: str | int | float | bool = Field(description="Use integer VND for budget_vnd and prices, integer square meters for room_area_m2, and boolean for has_children or in_stock.")
    op: Literal["set", "supersede", "delete"] = "set"
    scope_type: Literal["global", "product", "room"] = "global"
    scope_id: str = ""
    source_kind: Literal["customer", "tool"]
    source_turn_id: str
    source_tool: str | None = None
    evidence_quote: str
    observed_on: date
    valid_until: date | None = None


class QuotedPrice(SafeProposal):
    sku: str
    price_vnd: int = Field(ge=0)
    quoted_on: date
    source_tool: str


class CustomerCallEpisodeCandidate(SafeProposal):
    customer_id: str
    session_id: str
    channel: Literal["hotline", "chat_fanpage", "zalo_oa", "web_chat", "other"]
    on: date
    source_turn_ids: list[str] = Field(min_length=1)
    customer_goal: str | None = None
    topics: list[dict[str, Any]] = Field(default_factory=list)
    products_discussed: list[str] = Field(default_factory=list)
    quoted_prices: list[QuotedPrice] = Field(default_factory=list)
    open_blockers: list[str] = Field(default_factory=list,
        description="Literal customer phrases naming unresolved dependencies before a decision; do not paraphrase.")
    open_questions: list[str] = Field(default_factory=list)
    actions_completed: list[dict[str, Any]] = Field(default_factory=list)
    outcome: Literal["hen_goi_lai", "chot_don", "tu_choi", "chuyen_may", "khac"] = "khac"
