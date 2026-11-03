"""Durable analysis worker. No approval or publication authority."""
from app.knowledge.config import configured_url
import asyncio
import re
import time
from app.knowledge.events.analysis import analyze_event
from app.knowledge.schemas import identifier, timestamp


async def claim_job(repo, worker_id, now=None):
    now = time.time() if now is None else now
    async with repo.transaction() as tx:
        for job in await tx.rows('jobs'):
            eligible = (job['status'] in {'pending', 'retry'} and job.get('available_at', 0) <= now
                        or job['status'] == 'running' and job.get('lease_until', 0) <= now)
            if eligible:
                job.update(status='running', owner=worker_id, lease_token=identifier(),
                           lease_until=now+300, attempts=job['attempts']+1)
                await tx.put('jobs', job['id'], job)
                return job
    return None


async def process_one(repo, worker_id, analyzer=analyze_event, now=None):
    now = time.time() if now is None else now
    job = await claim_job(repo, worker_id, now)
    if not job:
        return False
    try:
        async with repo.transaction() as tx:
            event = await tx.get('events', job['event_id'])
            sources = await tx.sources()
            if event.get('rating') is True or event.get('source') == 'business_outcome':
                current = await tx.get('jobs', job['id'])
                if current.get('lease_token') == job['lease_token']:
                    current.update(status='completed')
                    event.update(status='observed')
                    await tx.put('jobs', job['id'], current)
                    await tx.put('events', event['id'], event)
                return True
        analysis = await analyzer(event, sources)
        async with repo.transaction() as tx:
            current = await tx.get('jobs', job['id'])
            if current.get('lease_token') != job['lease_token']:
                return True
            if event.get('customer_id') and await tx.get('erasures', event['customer_id']):
                current.update(status='erased')
            else:
                gap_id = job['id']
                if not await tx.get('gaps', gap_id):
                    words = set(re.findall(r'\w+', str(analysis.get('title', '')).casefold()))
                    suggestions = []
                    for previous in await tx.rows('gaps'):
                        other = set(re.findall(r'\w+', previous.get('title', '').casefold()))
                        if (previous.get('category') == analysis['category'] and other and words
                                and len(words & other)/len(words | other) >= 0.6
                                and previous.get('status') not in {'erased', 'resolved', 'merged'}):
                            suggestions.append(previous['id'])
                    analysis['suggested_merge_ids'] = suggestions[:10]
                    await tx.put('gaps', gap_id, {'id': gap_id, 'version': 1, 'status': 'new',
                        'event_ids': [event['id']], 'created_at': timestamp(), **analysis})
                if analysis.get('suggested_source_ids') and analysis['category'] in {'retrieval', 'content', 'insufficient_evidence'}:
                    from app.knowledge.services.revisions import _draft
                    ids = analysis['suggested_source_ids'][:1]
                    try:
                        draft = await _draft(tx, worker_id, gap_id, {
                            'kind': 'faq' if analysis['category'] == 'content' else 'aliases',
                            'question': event['question'], 'aliases': [event['question']],
                            'answer': next((s.get('body', '') for s in sources if s['chunk_id'] == ids[0]), ''),
                            'source_ids': ids, 'source_review_note': 'Automatic draft; reviewer must verify source applicability.'})
                        gap = await tx.get('gaps', gap_id)
                        gap['draft_revision_id'] = draft['id']
                        await tx.put('gaps', gap_id, gap)
                    except ValueError:
                        pass  # A stale source leaves the gap available for manual review.
                current.update(status='completed', gap_id=gap_id)
                event.update(status='analyzed')
                await tx.put('events', event['id'], event)
            await tx.put('jobs', job['id'], current)
    except Exception as exc:
        async with repo.transaction() as tx:
            current = await tx.get('jobs', job['id'])
            if current and current.get('lease_token') == job['lease_token']:
                n = current['attempts']
                current.update(status='failed' if n >= 5 else 'retry',
                               available_at=now+[5, 30, 120, 600][min(n-1, 3)],
                               error_code=type(exc).__name__)
                await tx.put('jobs', job['id'], current)
    return True


async def main():
    from app.knowledge.repos.postgres import KnowledgeRepo
    dsn = configured_url('KNOWLEDGE_WORKER_DATABASE_URL')
    if not dsn:
        raise SystemExit('KNOWLEDGE_WORKER_DATABASE_URL required (restricted worker role)')
    repo = KnowledgeRepo(dsn)
    worker_id = identifier()
    try:
        while True:
            if not await process_one(repo, worker_id):
                await asyncio.sleep(1)
    finally:
        await repo.close()

