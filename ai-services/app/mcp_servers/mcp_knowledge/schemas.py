"""MCP request, trusted context, response and serving configuration contracts."""
from datetime import date
from typing import Literal
from pydantic import Field, field_validator, model_validator
from app.knowledge.schemas import Contract, Evidence, EvidenceSet


class PolicySearchInput(Contract):
    query: str = Field(min_length=1)
    on: date
    order_date: date | None = None
    customer_reported_order_date: date | None = None
    top_k: int = Field(default=5, ge=1, le=10)

    @field_validator('query')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Query required')
        return value.strip()


class TrustedPolicyContext(Contract):
    request_id: str = Field(min_length=1)
    principal: str = Field(min_length=1)
    on: date
    release_id: str | None = None
    verified_order_date: date | None = None
    date_source: str | None = None
    purpose: Literal['customer'] = 'customer'
    include_supplements: bool = True

    @model_validator(mode='after')
    def date_provenance(self):
        if self.verified_order_date and not self.date_source:
            raise ValueError('Verified date requires provenance')
        return self


class PolicySearchResult(Contract):
    retrieval_status: Literal['ok', 'no_evidence', 'unavailable', 'timeout', 'overloaded']
    context: dict = Field(default_factory=dict)
    truncated: Literal[False] = False
    evidence_set: EvidenceSet = Field(default_factory=EvidenceSet)
    evidence: list[Evidence] = Field(default_factory=list)
    error: str | None = None


class PolicyRuntimeConfig(Contract):
    model_name: str = 'BAAI/bge-m3'
    model_revision: str = Field(min_length=1)
    tokenizer_revision: str = Field(min_length=1)
    max_tokens: int = Field(gt=0)
    batch_size: int = Field(default=1, gt=0)
    dimension: int = Field(default=1024, gt=0)
    device: str = 'cuda:0'
    dtype: Literal['float16'] = 'float16'
    normalization: Literal['l2'] = 'l2'
    prefix: str = ''
    dense_candidates: int = Field(gt=10)
    sparse_candidates: int = Field(gt=10)
    hard_limit: int = Field(ge=10)
    dense_threshold: float = Field(ge=-1, le=1)
    sparse_threshold: float = Field(gt=0)
    relevance_verified: bool = False
    queue_capacity: int = Field(gt=0)
    deadline_seconds: float = Field(gt=0)
    dependency_timeout_seconds: float = Field(gt=0)
    breaker_failures: int = Field(gt=0)
    breaker_cooldown_seconds: float = Field(gt=0)

    @model_validator(mode='after')
    def limits(self):
        if min(self.dense_candidates, self.sparse_candidates) <= self.hard_limit:
            raise ValueError('Candidate depths must exceed evidence hard limit')
        return self

    def fingerprint(self):
        from app.knowledge.schemas import digest
        return digest({key: getattr(self, key) for key in (
            'model_name', 'model_revision', 'tokenizer_revision', 'max_tokens',
            'dimension', 'dtype', 'normalization', 'prefix')})
