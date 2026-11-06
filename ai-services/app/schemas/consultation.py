"""Versioned consultation evidence; customer purchase permission is turn-local."""
import re
from datetime import date
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.mcp_servers.mcp_shared.pii import mask_pii


_REDACTION = re.compile(r'(\[(?:ĐỊA CHỈ|SỐ|TÊN|EMAIL|PII) ĐÃ ẨN\])')


def mask_evidence(text: str) -> str:
    """Preserve existing redactions when masking evidence repeatedly."""
    return ''.join(part if _REDACTION.fullmatch(part) else mask_pii(part)
                   for part in _REDACTION.split(text))


class ConsultationModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SourceRef(ConsultationModel):
    customer_id: str | None
    session_id: str
    source_turn_id: str
    source_kind: Literal['customer','agent','tool']
    evidence_quote: str = Field(max_length=200)

    @model_validator(mode='after')
    def safe_evidence(self):
        if mask_evidence(self.evidence_quote)!=self.evidence_quote:
            raise ValueError('consultation evidence contains PII')
        return self


class SpendingLimit(ConsultationModel):
    limit_vnd: int | None = Field(default=None,ge=0)
    mode: Literal['hard','approx','unknown'] = 'unknown'
    basis: Literal['unit','total','unknown'] = 'unknown'


class ObservationRef(ConsultationModel):
    customer_id: str
    session_id: str
    source_turn_id: str
    tool_name: Literal['pricing.get_quote'] = 'pricing.get_quote'
    observation_index: int = Field(ge=0, lt=20)


class OfferComponentSource(ConsultationModel):
    agent: SourceRef
    observation: ObservationRef

    @model_validator(mode='after')
    def same_owner(self):
        if self.agent.source_kind != 'agent' or self.agent.customer_id != self.observation.customer_id:
            raise ValueError('invalid offer source')
        if self.agent.session_id != self.observation.session_id:
            raise ValueError('invalid offer session')
        return self


class PresentedOffer(ConsultationModel):
    sku: str
    variant: str | None = None
    qty: int | None = Field(default=None, ge=1)
    price_vnd: int | None = Field(default=None, ge=0)
    basis: Literal['unit', 'total', 'unknown'] = 'unknown'
    on: date | None = None
    promo_terms: list[dict[str, Any]] = Field(default_factory=list, max_length=11)
    coverage: Literal['unknown', 'partial', 'complete'] = 'unknown'
    sources: dict[str, OfferComponentSource] = Field(default_factory=dict, max_length=12)



class AcceptedOffer(ConsultationModel):
    presented_basis: Literal['unit', 'total', 'unknown'] = 'unknown'
    basis: Literal['unit', 'total', 'unknown'] = 'unit'
    presented_source: SourceRef | None = None
    sku: str
    variant: str | None = None
    qty: int = Field(default=1,ge=1)
    price_vnd: int = Field(ge=0)
    on: date | None = None
    promo_terms: list[dict[str,Any]] = Field(default_factory=list)


class Delegation(ConsultationModel):
    status: Literal['active','revoked','unknown'] = 'unknown'
    constraints: dict[str,Any] = Field(default_factory=dict)


class ConsultationSnapshot(ConsultationModel):
    schema_version: Literal[2] = 2

    @model_validator(mode='before')
    @classmethod
    def legacy(cls, value):
        if isinstance(value, dict) and value.get('schema_version') == 1:
            value = {**value, 'schema_version': 2}
        return value

    presented_offer: PresentedOffer | None = None
    candidates: list[str] = Field(default_factory=list,max_length=16)
    recommended_sku: str | None = None
    selected_sku: str | None = None
    budget: SpendingLimit = Field(default_factory=SpendingLimit)
    accepted_offer: AcceptedOffer | None = None
    delegation: Delegation = Field(default_factory=Delegation)
    source_refs: dict[str,SourceRef] = Field(default_factory=dict)


class ConsultationDecision(ConsultationModel):
    snapshot: ConsultationSnapshot = Field(default_factory=ConsultationSnapshot)
    focus_sku: str | None = None
    purchase_intent: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    next_action: Literal['search','clarify','quote','purchase','pause','confirm_terms'] = 'clarify'


def mask_consultation(value: Any, field: str = '') -> Any:
    """Mask content while preserving typed business/provenance identifiers."""
    opaque={'candidates','recommended_sku','selected_sku','sku','variant','gift_sku','promo_code',
            'customer_id','session_id','source_turn_id'}
    if isinstance(value,dict):return {key:mask_consultation(item,key) for key,item in value.items()}
    if isinstance(value,list):return [mask_consultation(item,field) for item in value]
    if isinstance(value,str):return value if field in opaque else mask_evidence(value)
    return value
