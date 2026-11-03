"""Reviewer-controlled triage and provenance-preserving merge/split."""
from app.knowledge.events.evidence import safe_text
from app.knowledge.services.permissions import require_permission
from app.knowledge.schemas import CATEGORIES, Conflict, KnowledgeError, Missing, identifier, timestamp


async def update_gap(repo, gap_id, actor_id, expected_version, action, payload):
    async with repo.transaction() as tx:
        await require_permission(tx, actor_id)
        gap = await tx.get('gaps', gap_id)
        if not gap:
            raise Missing('Gap not found')
        if gap['version'] != expected_version:
            raise Conflict('Gap changed; refresh before editing')
        if action == 'classify':
            if payload.get('category') not in CATEGORIES or not payload.get('reason', '').strip():
                raise KnowledgeError('Category and reason required')
            gap.update(category=payload['category'], reason=safe_text(payload['reason'])[:2000], status='triaged')
            if payload['category'] in {'technical', 'generation'}:
                gap['status'] = 'technical_followup'
            elif payload['category'] == 'correct_refusal':
                gap['status'] = 'closed_correct_refusal'
            elif payload['category'] == 'insufficient_evidence':
                gap['status'] = 'waiting_for_source'
        elif action == 'merge':
            other = await tx.get('gaps', payload.get('other_id'))
            if not other or other['id'] == gap_id or other.get('status') == 'merged':
                raise KnowledgeError('Invalid merge target')
            gap['event_ids'] = sorted(set(gap['event_ids'] + other['event_ids']))
            other.update(status='merged', merged_into=gap_id, version=other['version']+1)
            await tx.put('gaps', other['id'], other)
        elif action == 'split':
            selected = set(payload.get('event_ids', []))
            if not selected or not selected < set(gap['event_ids']):
                raise KnowledgeError('Split requires a proper nonempty subset')
            new_id = identifier()
            new = dict(gap, id=new_id, event_ids=sorted(selected), version=1, status='new')
            gap['event_ids'] = sorted(set(gap['event_ids'])-selected)
            await tx.put('gaps', new_id, new)
        else:
            raise KnowledgeError('Unknown gap action')
        gap['version'] += 1
        await tx.put('gaps', gap_id, gap)
        aid = identifier()
        await tx.put('audit', aid, {'id': aid, 'actor_id': actor_id, 'action': action,
                                  'gap_id': gap_id, 'at': timestamp()})
        return gap
