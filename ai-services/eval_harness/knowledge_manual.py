import asyncio
import time

from app.knowledge.events.analysis import analyze_event
from app.knowledge.events.ingest import record_event
from app.knowledge.events.worker import process_one
from app.knowledge.schemas import KnowledgeError, digest
from app.knowledge.services.permissions import require_permission
from app.knowledge.services.revisions import content_hash
from app.knowledge.services.source_validation import validate_sources
from eval_harness.knowledge_auto_review import locator, retrieved_ids

MODE = 'manual_frontend_review'


async def analyze(evidence, sources):
    result = await analyze_event(evidence, sources)
    if evidence.get('signal') == 'evaluation_failure' and (
            evidence.get('retrieved_ids') or not any(
                t['name'] == 'policy.search' for t in evidence['tool_calls'])):
        result.update(category='generation', suggested_source_ids=[],
                      source_review='Review generation/tools before changing knowledge.')
    return result


async def propose(repo, worker_repo, rows, feedback, *, actor, run_id, release_id,
                  score_sha256, timeout=60):
    async with repo.transaction() as tx:
        await require_permission(tx, actor)
    failures = {}
    for exported in feedback:
        event = exported['event']
        failures.setdefault((event['scenario_id'], event['call'], int(event['turn'])), []).append(event)
    result = {'approval_mode': MODE, 'run_id': run_id, 'proposed': [], 'skipped': []}
    for row in rows:
        key = locator(row)
        lookups = [t.get('result', {}) for t in row.get('tool_calls', []) if t.get('name') == 'policy.search']
        failed = failures.get(key, [])
        missing = any(r.get('retrieval_status') == 'no_evidence' for r in lookups)
        if row.get('config') != 'full' or not (failed or missing):
            result['skipped'].append({'locator': list(key), 'reason': 'no_full_k0_failure_signal'})
            continue
        if any(r.get('context', {}).get('knowledge_release_id') != release_id for r in lookups):
            raise KnowledgeError('Manual proposal lookup release differs from K0')
        event = (dict(failed[0]) if failed else {
            'source': 'runtime_signal', 'signal': 'no_evidence',
            'question': row.get('user_text', row.get('customer_text', '')),
            'answer': row.get('agent_text', ''), 'tool_calls': row.get('tool_calls', []),
            'reason': 'Full K0 policy search returned no evidence; reviewer must check the cause.'})
        event.update(actor_id=actor, run_id=run_id, release_id=release_id,
            scenario_id=key[0], call=key[1], turn=key[2], score_sha256=score_sha256,
            retrieved_ids=sorted(retrieved_ids(row)), context=digest(row))
        if missing:
            event['signal'] = 'no_evidence'
        if failed:
            event['reason'] = '; '.join(e['reason'] for e in failed)[:2000]
        recorded = await record_event(repo, event, f'{run_id}:manual:{digest(key)[:24]}')
        deadline = time.monotonic() + timeout
        while True:
            await process_one(worker_repo, 'experiment-proposals', analyzer=analyze, event_ids={recorded['id']})
            async with repo.transaction() as tx:
                job = await tx.get('jobs', recorded['id'])
            if job['status'] == 'completed': break
            if job['status'] in {'failed', 'erased'} or time.monotonic() >= deadline:
                raise KnowledgeError('Scoped proposal analysis failed/timed out; resume without rerunning K0')
            await asyncio.sleep(.2)
        async with repo.transaction() as tx:
            gap = await tx.get('gaps', job['gap_id'])
        result['proposed'].append({'locator': list(key), 'event_id': recorded['id'],
            'gap_id': gap['id'], 'draft_revision_id': gap.get('draft_revision_id'), 'category': gap['category']})
    return result


async def collect_review(repo, proposals, *, actor, run_id, base):
    async with repo.transaction() as tx:
        await require_permission(tx, actor)
        active = (await tx.get('active', 'current') or {}).get('release_id')
        if active == base: return None
        previous, release = await tx.get('releases', base), await tx.get('releases', active)
        if (not previous or not release or release.get('status') != 'ready'
                or release.get('base_release_id') != base
                or release.get('manifest_hash') != digest(release['manifest'])):
            raise KnowledgeError('Publish a ready K1 release before resuming')
        old = {i['id'] for i in previous['manifest']['items']}
        scoped = {p['gap_id']: p for p in proposals['proposed']}
        approved = []
        decisions = await tx.rows('decisions')
        for snapshot in release['manifest']['items']:
            if snapshot['id'] in old: continue
            revision = await tx.get('revisions', snapshot['id'])
            proposal = scoped.get((revision or {}).get('gap_id'))
            if not proposal:
                raise KnowledgeError('K1 contains a revision outside this experiment')
            event = await tx.get('events', proposal['event_id'])
            gap = await tx.get('gaps', proposal['gap_id'])
            case = await tx.get('regression_cases', revision['id'])
            decision = next((d for d in decisions if d['revision_id'] == revision['id']
                and d['decision'] == 'approve' and d['content_hash'] == revision['content_hash']
                and d['actor_id'] == revision.get('approved_by')
                and d['reason'] == revision.get('approval_reason')), None)
            if (not event or event.get('run_id') != run_id or event.get('release_id') != base
                    or not gap or proposal['event_id'] not in gap['event_ids']
                    or gap['category'] in {'technical', 'generation', 'correct_refusal'}
                    or revision.get('status') != 'approved' or not decision or not decision['reason'].strip()
                    or revision['content_hash'] != content_hash(revision)
                    or any(snapshot.get(k) != revision.get(k) for k in
                           ('gap_id', 'kind', 'sources', 'content_hash', 'test_hash'))
                    or not case or not case.get('approved') or revision.get('test_hash') != digest(case)):
                raise KnowledgeError('K1 review/source/test provenance is missing or changed')
            await validate_sources(tx, revision['sources'])
            approved.append({'case_id': digest(proposal['locator'])[:24], **proposal,
                'revision_id': revision['id'], 'kind': revision['kind'], 'question': revision['question'],
                'content_hash': revision['content_hash'], 'test_hash': revision['test_hash'],
                'sources': revision['sources'], 'approved_by': revision['approved_by'],
                'approval_reason': revision['approval_reason'], 'decision': decision})
        if not approved:
            raise KnowledgeError('K1 has no new approved revisions from this experiment')
        return {'approval_mode': MODE, 'approved': approved, 'skipped': proposals['skipped'],
                'proposed': proposals['proposed']}, release
