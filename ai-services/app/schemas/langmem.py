"""Typed, untrusted proposals from long-term memory distillation."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.mcp_servers.mcp_shared.pii import mask_pii
from app.constants import PROFILE_SLOT_KEYS


FactKey = Literal.__getitem__(tuple(sorted(PROFILE_SLOT_KEYS)))


_IDENTIFIER_FIELDS = {"source_turn_id", "source_turn_ids", "session_id",
                      "customer_id", "scope_id", "sku", "source_tool", "item_id"}


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


class EvidencedText(SafeProposal):
    text: str = Field(min_length=1, max_length=300)
    evidence_quote: str = Field(min_length=8, max_length=200)

    @model_validator(mode="before")
    @classmethod
    def coerce_str(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"text": data, "evidence_quote": data}
        return data


class OpenItemProposal(EvidencedText):
    kind: Literal["blocker", "question"] = "blocker"


class ResolvedItem(SafeProposal):
    item_id: str = Field(min_length=1, max_length=80)
    evidence_quote: str = Field(min_length=8, max_length=200)


class TopicProposal(SafeProposal):
    scope_type: Literal["global", "product", "room"] = "global"
    scope_id: str = ""
    customer_goal: EvidencedText | None = None
    advice_given: EvidencedText | None = None
    next_step: EvidencedText | None = None
    open_items: list[OpenItemProposal] = Field(default_factory=list)
    resolved_items: list[ResolvedItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope_type == "global" and self.scope_id:
            raise ValueError("global topic must not have scope_id")
        if self.scope_type in {"product", "room"} and (
                not self.scope_id or len(self.scope_id) > 80 or mask_pii(self.scope_id) != self.scope_id):
            raise ValueError("product/room topic requires a safe non-empty scope_id")
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
    valid_until: date | None = Field(
        default=None,
        description="Set only by deterministic code from verified promo/TTL sources; leave null in LLM proposals.",
    )

    @model_validator(mode="after")
    def check_valid_until(self):
        if self.valid_until is not None and self.valid_until < self.observed_on:
            raise ValueError("valid_until must be on or after observed_on")
        return self


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
    customer_goal: EvidencedText | None = None
    topics: list[TopicProposal] = Field(default_factory=list)
    open_blockers: list[EvidencedText] = Field(
        default_factory=list,
        description="Unresolved customer dependencies before a decision, each with a concise text and literal customer evidence_quote.",
    )
    open_questions: list[EvidencedText] = Field(default_factory=list)
    outcome: Literal["hen_goi_lai", "chot_don", "tu_choi", "chuyen_may", "khac"] = "khac"
