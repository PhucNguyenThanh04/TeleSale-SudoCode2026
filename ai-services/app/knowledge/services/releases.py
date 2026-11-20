from app.knowledge.services.permissions import require_permission
from app.knowledge.schemas import Conflict, KnowledgeError, Missing, digest, identifier, timestamp
from app.knowledge.services.source_validation import validate_sources


async def _active(tx):
    return (await tx.get('active', 'current') or {}).get('release_id')


async def prepare_release(repo, revision_ids, expected_active_id, actor_id):
    from app.configs import get_settings
    settings = get_settings()
    if settings.knowledge_policy_config_file:
        from app.knowledge.services.publish import build_configured_policy_release
        return await build_configured_policy_release(repo, revision_ids, expected_active_id, actor_id)
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
            from app.knowledge.services.regression import check_offline_retrieval
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
            baseline = await tx.get('active', 'policy-btc') or {}
            if baseline.get('release_id'):
                release_id = baseline['release_id']
                release = await tx.get('releases', release_id)
            else:
                manifest = {'items': []}
                release = {'id': 'btc-only', 'status': 'ready', 'manifest': manifest, 'manifest_hash': digest(manifest)}
        if not release:
            raise Missing('Release not found')
        if release['status'] != 'ready' or digest(release['manifest']) != release['manifest_hash']:
            raise Conflict('Release index is not ready or manifest is corrupt')
        from app.configs import get_settings
        settings = get_settings()
        if settings.knowledge_policy_config_file:
            from app.mcp_servers.mcp_knowledge.config import load_policy_config
            runtime_config = load_policy_config(settings)
            if (release['manifest'].get('index_kind') != 'hybrid'
                    or release['manifest'].get('model_fingerprint') != runtime_config.fingerprint()
                    or release['manifest'].get('config_hash') != digest(runtime_config.model_dump(mode='json'))):
                raise Conflict('Release is incompatible with configured knowledge runtime')
        if release['manifest'].get('index_kind') == 'hybrid':
            from app.knowledge.services.publish import validate_hybrid_release
            await validate_hybrid_release(tx, release)
        for item in release['manifest']['items']:
            await validate_sources(tx, item['sources'])
        await tx.put('active', 'current', {'id': 'current', 'release_id': release_id,
                                          'actor_id': actor_id, 'previous_release_id': current, 'at': timestamp()})
        if release['manifest'].get('index_kind') == 'hybrid' and not release['manifest']['items']:
            await tx.put('active', 'policy-btc', {'id': 'policy-btc', 'release_id': release_id})
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
    return await activate_release(repo, target_id, expected_active_id, actor_id, 'rollback_release')
