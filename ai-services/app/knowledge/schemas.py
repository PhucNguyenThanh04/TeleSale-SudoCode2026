import hashlib
import json
from datetime import date, datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from uuid import uuid4


class KnowledgeError(ValueError):
    status = 422


class Conflict(KnowledgeError):
    status = 409


class Forbidden(KnowledgeError):
    status = 403


class Missing(KnowledgeError):
    status = 404


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str, separators=(',', ':')).encode()).hexdigest()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def identifier():
    return str(uuid4())


TABLES = frozenset({'events', 'gaps', 'revisions', 'decisions', 'regression_cases',
    'releases', 'active', 'jobs', 'audit', 'permissions', 'verification_runs', 'erasures', 'backend_outbox', 'policy_sources', 'policy_revocations'})
CATEGORIES = frozenset({'content', 'retrieval', 'source_conflict', 'generation',
                        'technical', 'correct_refusal', 'insufficient_evidence'})


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PolicyRule(Contract):
    scope: str
    date_basis: Literal['on', 'order_date'] = 'on'
    effective_from: date | None = None
    effective_until: date | None = None
    required_context: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    description: str = ''

    @model_validator(mode='after')
    def valid_interval(self):
        if self.effective_from and self.effective_until and self.effective_from > self.effective_until:
            raise ValueError('Invalid policy date interval')
        return self


class SourceChunk(Contract):
    model_config = ConfigDict(extra='forbid', frozen=True)
    chunk_id: str
    section_id: str
    document_id: str
    content: str = Field(min_length=1)
    source: dict
    source_hash: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    access_level: Literal['public'] = 'public'
    evidence_type: Literal['business_rule', 'knowledge_limit', 'disclosure_limit', 'handoff_guidance'] = 'business_rule'
    date_basis: Literal['on', 'order_date'] = 'on'
    effective_from: date | None = None
    effective_until: date | None = None
    required_context: list[str] = Field(default_factory=list)
    required_links: list[str] = Field(default_factory=list)
    rules: list[PolicyRule] = Field(default_factory=list)
    conflict: bool = False
    transformation: str = 'identity'
    supplement: bool = False
    source_references: list[dict] = Field(default_factory=list)
    search_aliases: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_interval(self):
        if self.effective_from and self.effective_until and self.effective_from > self.effective_until:
            raise ValueError('Invalid policy date interval')
        return self


class Applicability(Contract):
    status: Literal['applicable', 'conditional', 'conflict'] = 'applicable'
    date_basis: Literal['on', 'order_date'] = 'on'
    date_used: date | None = None
    date_source: str | None = None
    effective_from: date | None = None
    effective_until: date | None = None
    required_context: list[str] = Field(default_factory=list)
    missing_required_section_ids: list[str] = Field(default_factory=list)
    rules: list[PolicyRule] = Field(default_factory=list)


class Evidence(Contract):
    chunk_id: str
    section_id: str
    document_id: str
    content: str
    source: dict
    evidence_type: Literal['business_rule', 'knowledge_limit', 'disclosure_limit', 'handoff_guidance'] = 'business_rule'
    applicability: Applicability = Field(default_factory=Applicability)
    retrieved_via: Literal['vector', 'linked'] = 'vector'


class EvidenceSet(Contract):
    required_dependencies_complete: bool = True
    missing_required_section_ids: list[str] = Field(default_factory=list)


class HybridVector(Contract):
    dense: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]
