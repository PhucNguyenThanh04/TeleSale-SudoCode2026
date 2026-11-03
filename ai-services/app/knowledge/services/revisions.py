"""Immutable content versions; approvals are tied to exact content and test hashes."""
import re
from app.knowledge.events.evidence import safe_text
from app.knowledge.services.permissions import require_permission
from app.knowledge.services.regression import build_regression_draft
from app.knowledge.schemas import Conflict, KnowledgeError, Missing, digest, identifier, timestamp
from app.knowledge.services.source_validation import validate_sources


def content_hash(revision):
    return digest({k: v for k, v in revision.items() if k not in
                   {'status', 'content_hash', 'created_at', 'approved_by', 'approval_reason', 'test_hash'}})


async def _draft(tx, actor_id, gap_id, payload, revision_id=None):
    gap = await tx.get('gaps', gap_id)
    if not gap:
        raise Missing('Gap not found')
    if gap['category'] in {'technical', 'generation', 'correct_refusal'}:
        raise KnowledgeError('This category requires technical follow-up or no content change')
    kind = payload.get('kind')
    question, answer = safe_text(payload.get('question', '')).strip(), safe_text(payload.get('answer', '')).strip()
    aliases = [safe_text(v).strip() for v in payload.get('aliases', [])]
    if kind not in {'faq', 'aliases'} or not question or not payload.get('source_review_note', '').strip():
        raise KnowledgeError('Kind, question and source review note required')
    if kind == 'faq' and (not answer or re.search(r'\d[\d., ]*\s*(?:đ|vnd|triệu|nghìn|k\b)', answer, re.I)):
        raise KnowledgeError('FAQ requires an answer without dynamic price commitments')
    if kind == 'aliases' and (not aliases or len(aliases) > 20):
        raise KnowledgeError('One to twenty aliases required')
    ids = payload.get('source_ids', [])
    rows = await tx.sources(ids)
    refs = [{'chunk_id': r['chunk_id'], 'source_hash': r['source_hash']} for r in rows]
    if set(ids) != {r['chunk_id'] for r in rows}:
        raise KnowledgeError('Unknown source')
    metadata = await validate_sources(tx, refs)
    rid = revision_id or identifier()
    draft = {'id': rid, 'gap_id': gap_id, 'kind': kind, 'question': question, 'answer': answer,
             'aliases': aliases, 'source_ids': ids, 'sources': refs, 'author_id': actor_id,
             'source_review_note': safe_text(payload['source_review_note']), 'status': 'draft',
             'scope': safe_text(payload.get('scope', '')), 'created_at': timestamp(), **metadata}
    draft['content_hash'] = content_hash(draft)
    await tx.put('revisions', rid, draft)
    await tx.put('regression_cases', rid, build_regression_draft(draft))
    return draft


async def create_revision(repo, actor_id, gap_id, payload):
    async with repo.transaction() as tx:
        await require_permission(tx, actor_id)
        return await _draft(tx, actor_id, gap_id, payload)


async def edit_revision(repo, actor_id, revision_id, expected_hash, changes):
    async with repo.transaction() as tx:
        await require_permission(tx, actor_id)
        old = await tx.get('revisions', revision_id)
        if not old:
            raise Missing('Revision not found')
        if old['content_hash'] != expected_hash:
            raise Conflict('Revision changed')
        # Published or approved bytes are retained; edits create a new revision.
        return await _draft(tx, actor_id, old['gap_id'], old | changes)


async def decide_revision(repo, actor_id, revision_id, expected_hash, decision, reason, approve_test=False):
    async with repo.transaction() as tx:
        await require_permission(tx, actor_id)
        revision = await tx.get('revisions', revision_id)
        if not revision:
            raise Missing('Revision not found')
        if revision['content_hash'] != expected_hash:
            raise Conflict('Revision changed')
        if decision not in {'approve', 'reject'} or not reason.strip():
            raise KnowledgeError('Decision and reason required')
        if decision == 'approve':
            await validate_sources(tx, revision['sources'])
            if not approve_test:
                raise KnowledgeError('Explicit test review required')
        for release in await tx.rows('releases'):
            if any(item.get('id') == revision_id for item in release.get('manifest', {}).get('items', [])):
                if decision == 'approve' and revision.get('status') == 'approved':
                    return revision
                raise Conflict('Prepared revision is immutable; create a new revision or roll back')
        case = await tx.get('regression_cases', revision_id)
        case['approved'] = decision == 'approve' and approve_test
        revision.update(status='approved' if decision == 'approve' else 'rejected',
                        approved_by=actor_id, approval_reason=safe_text(reason), test_hash=digest(case))
        did = digest([revision_id, expected_hash, decision, digest(case)])
        await tx.put('decisions', did, {'id': did, 'revision_id': revision_id, 'content_hash': expected_hash,
                                      'decision': decision, 'actor_id': actor_id, 'reason': safe_text(reason),
                                      'at': timestamp()})
        await tx.put('regression_cases', revision_id, case)
        await tx.put('revisions', revision_id, revision)
        return revision
