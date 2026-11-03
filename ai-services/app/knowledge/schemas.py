"""Shared lifecycle values and safe error contracts."""
import hashlib
import json
from datetime import datetime, timezone
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
    'releases', 'active', 'jobs', 'audit', 'permissions', 'verification_runs', 'erasures', 'backend_outbox'})
CATEGORIES = frozenset({'content', 'retrieval', 'source_conflict', 'generation',
                        'technical', 'correct_refusal', 'insufficient_evidence'})
