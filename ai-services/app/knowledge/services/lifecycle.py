"""Knowledge management use cases shared by API and administrative CLI."""
from app.knowledge.events.evidence import safe_text
from app.knowledge.services.permissions import require_permission
from app.knowledge.schemas import Conflict, KnowledgeError, Missing, digest
from app.knowledge.services.gaps import update_gap
from app.knowledge.services.revisions import create_revision, edit_revision, decide_revision
from app.knowledge.services.releases import prepare_release, activate_release, rollback_release

RESOURCES = {'events', 'gaps', 'revisions', 'regression_cases', 'releases', 'jobs', 'audit', 'verification_runs', 'sources', 'backend_outbox'}


async def query(repo, actor_id, resource, offset=0, limit=30, status=None, source=None, item_id=None):
    if resource not in RESOURCES or offset < 0 or not 1 <= limit <= 100:
        raise KnowledgeError('Invalid query')
    async with repo.transaction() as tx:
        await require_permission(tx, actor_id)
        rows = ([dict(r, id=r['chunk_id']) for r in await tx.sources() if r.get('access_level') == 'public']
                if resource == 'sources' else await tx.rows(resource))
        if item_id:
            rows = [r for r in rows if r['id'] == item_id]
        if status:
            rows = [r for r in rows if r.get('status') == status]
        if source:
            rows = [r for r in rows if r.get('source') == source]
        rows.sort(key=lambda r: (r.get('created_at', ''), r['id']), reverse=True)
        if resource == 'regression_cases':
            rows = [dict(r, record_hash=digest(r)) for r in rows]
        active = await tx.get('active', 'current')
        return {'items': rows[offset:offset+limit], 'total': len(rows), 'offset': offset,
                'active_release_id': (active or {}).get('release_id')}


async def command(repo, actor_id, action, p):
    if action in {'classify', 'merge', 'split'}:
        return await update_gap(repo, p['id'], actor_id, p['version'], action, p)
    if action == 'create_revision':
        return await create_revision(repo, actor_id, p['gap_id'], p)
    if action == 'edit_revision':
        return await edit_revision(repo, actor_id, p['id'], p['content_hash'], p['changes'])
    if action in {'approve', 'reject'}:
        return await decide_revision(repo, actor_id, p['id'], p['content_hash'], action,
                                     p.get('reason', ''), p.get('approve_test') is True)
    if action == 'prepare_release':
        return await prepare_release(repo, p['revision_ids'], p.get('expected_active_id'), actor_id)
    if action in {'activate_release', 'rollback_release'}:
        fn = activate_release if action == 'activate_release' else rollback_release
        return await fn(repo, p['id'], p.get('expected_active_id'), actor_id)
    async with repo.transaction() as tx:
        await require_permission(tx, actor_id)
        if action == 'retry_outbox':
            row = await tx.get('backend_outbox', p['id'])
            if not row or row.get('status') != 'failed':
                raise Conflict('Only failed deliveries can be retried')
            row.update(status='pending', attempts=0)
            await tx.put('backend_outbox', row['id'], row)
            return {'id': row['id'], 'status': 'pending'}
        if action == 'retry_job':
            job = await tx.get('jobs', p['id'])
            if not job:
                raise Missing('Job not found')
            if job['status'] != 'failed':
                raise Conflict('Only exhausted jobs can be retried')
            job.update(status='pending', attempts=0, available_at=0)
            await tx.put('jobs', job['id'], job)
            return job
        if action == 'edit_test':
            case = await tx.get('regression_cases', p['id'])
            if not case:
                raise Missing('Test not found')
            if digest(case) != p['test_hash']:
                raise Conflict('Test changed')
            if not isinstance(p.get('expected'), dict) or not isinstance(p.get('variations'), list):
                raise KnowledgeError('Expected assertions and variations required')
            from app.knowledge.services.revisions import _draft
            old = await tx.get('revisions', case['id'])
            # Editing reviewed test creates a new revision; released snapshots stay immutable.
            new = await _draft(tx, actor_id, old['gap_id'], old)
            updated = await tx.get('regression_cases', new['id'])
            updated['expected'] = {'answer': safe_text(p['expected'].get('answer', '')),
                'source_ids': new['source_ids'], 'must_abstain_without_valid_sources': True}
            updated['variations'] = [safe_text(v) for v in p['variations'][:20]]
            if not updated['variations']:
                raise KnowledgeError('At least one test variation required')
            await tx.put('regression_cases', new['id'], updated)
            return new
        if action == 'verify_gap':
            gap = await tx.get('gaps', p['id'])
            run = await tx.get('verification_runs', p['verification_run_id'])
            if not gap or not run:
                raise Missing('Gap or verification run not found')
            if gap['version'] != p['version'] or gap.get('release_id') != run.get('release_id'):
                raise Conflict('Verification does not match gap release')
            if not run.get('complete') or not run.get('comparability_valid'):
                raise KnowledgeError('Complete comparable verification required')
            # A reviewer must inspect per-case evidence, not just an aggregate delta.
            if not p.get('reason', '').strip() or p.get('resolved') is not True:
                raise KnowledgeError('Explicit resolution decision and reason required')
            gap.update(status='resolved', verification_run_id=run['id'],
                       resolution_reason=safe_text(p['reason'])[:2000], version=gap['version']+1)
            await tx.put('gaps', gap['id'], gap)
            return gap
        raise KnowledgeError('Unknown command')
