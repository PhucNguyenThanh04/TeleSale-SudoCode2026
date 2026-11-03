"""Immutable lexical generations with transactional compare-and-swap activation."""
from app.knowledge.permissions import require_permission
from app.knowledge.schemas import Conflict, KnowledgeError, Missing, digest, identifier, timestamp
from app.knowledge.sources import validate_sources


async def _active(tx):
    return (await tx.get('active', 'current') or {}).get('release_id')


async def prepare_release(repo, revision_ids, expected_active_id, actor_id):
    if not revision_ids or len(revision_ids) > 100 or len(set(revision_ids)) != len(revision_ids):
        raise KnowledgeError('One to one hundred distinct revisions required')
    async with repo.transaction() as tx:
        await require_permission(tx, actor_id)
        if await _active(tx) != expected_active_id:
            raise Conflict('Active release changed')
        items = []
        checks = []
        for rid in revision_ids:
            revision = await tx.get('revisions', rid)
            case = await tx.get('regression_cases', rid)
            if not revision or revision['status'] != 'approved' or not case or not case['approved']:
                raise KnowledgeError('Approved revision and reviewed test required')
            if revision['test_hash'] != digest(case):
                raise Conflict('Reviewed test changed')
            await validate_sources(tx, revision['sources'])
            from app.knowledge.regression import check_offline_retrieval
            checks.append(check_offline_retrieval(revision, case, await tx.sources()))
            items.append(revision)
        manifest = {'items': items, 'index_kind': 'lexical', 'schema_version': 1, 'offline_checks': checks}
        for previous in await tx.rows('releases'):
            if (previous.get('manifest_hash') == digest(manifest) and previous.get('status') == 'ready'
                    and previous.get('base_release_id') == expected_active_id):
                return previous
        release = {'id': identifier(), 'manifest': manifest, 'manifest_hash': digest(manifest),
                   'status': 'ready', 'prepared_by': actor_id, 'created_at': timestamp(),
                   'base_release_id': expected_active_id}
        await tx.put('releases', release['id'], release)
        return release


async def activate_release(repo, release_id, expected_active_id, actor_id, operation='activate_release'):
    async with repo.transaction() as tx:
        await require_permission(tx, actor_id)
        active = await tx.get('active', 'current') or {}
        current = active.get('release_id')
        if (current == release_id and active.get('previous_release_id') == expected_active_id
                and active.get('actor_id') == actor_id):
            return {'release_id': release_id, 'previous_release_id': expected_active_id}
        if current != expected_active_id:
            raise Conflict('Active release changed; refresh')
        release = await tx.get('releases', release_id)
        if release_id == 'btc-only':
            manifest = {'items': []}
            release = {'id': 'btc-only', 'status': 'ready', 'manifest': manifest, 'manifest_hash': digest(manifest)}
        if not release:
            raise Missing('Release not found')
        if release['status'] != 'ready' or digest(release['manifest']) != release['manifest_hash']:
            raise Conflict('Release index is not ready or manifest is corrupt')
        for item in release['manifest']['items']:
            await validate_sources(tx, item['sources'])
        await tx.put('active', 'current', {'id': 'current', 'release_id': release_id,
                                          'actor_id': actor_id, 'previous_release_id': current, 'at': timestamp()})
        for item in release['manifest']['items']:
            gap = await tx.get('gaps', item['gap_id'])
            if gap:
                gap.update(status='awaiting_verification', release_id=release_id,
                           version=gap['version']+1)
                await tx.put('gaps', gap['id'], gap)
        aid = identifier()
        await tx.put('audit', aid, {'id': aid, 'action': operation, 'release_id': release_id,
                                  'previous_release_id': current, 'actor_id': actor_id, 'at': timestamp()})
        return {'release_id': release_id, 'previous_release_id': current}


async def rollback_release(repo, target_id, expected_active_id, actor_id):
    # Restoring a generation validates it against today's sources again.
    return await activate_release(repo, target_id, expected_active_id, actor_id, 'rollback_release')
