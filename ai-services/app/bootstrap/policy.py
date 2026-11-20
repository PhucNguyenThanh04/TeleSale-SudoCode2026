from app.knowledge.policy.source import parse_policy_sources
from app.knowledge.schemas import digest, timestamp
from app.knowledge.services.publish import build_policy_release
from app.knowledge.services.releases import activate_release
from qdrant_client.http.exceptions import UnexpectedResponse


async def capture_base(repo):
    try:
        release = await repo.resolve_release('btc-only')
        if release['manifest']['items']:
            return None
        return release
    except ValueError:
        return None


async def initialize_base(repo, encoder, index, *, source_dir, metadata, actor_id, cache=None):
    config = encoder.config
    chunks = sorted(parse_policy_sources(source_dir, metadata), key=lambda c: c.chunk_id)
    expected = digest([c.model_dump(mode='json') for c in chunks])
    usable = bool(cache and not cache['manifest']['items']
        and cache['manifest'].get('snapshot_hash') == expected
        and cache['manifest'].get('config_hash') == digest(config.model_dump(mode='json'))
        and cache['manifest'].get('metadata_hash') == digest(metadata))
    if usable:
        try:
            await index.verify(cache, config, chunks=chunks)
        except ValueError:
            usable = False
            name = cache['manifest']['collection']
            if name.startswith('policy_') and await index.client.collection_exists(name):
                await index.client.delete_collection(name)
        except UnexpectedResponse as exc:
            if exc.status_code != 404: raise
            usable = False
    if usable:
        release = dict(cache, prepared_by=actor_id, created_at=timestamp(), base_release_id=None)
        async with repo.transaction() as tx:
            await tx.put('releases', release['id'], release)
            for chunk in chunks:
                key = release['id'] + ':' + chunk.chunk_id
                await tx.put('policy_sources', key, {'id': key, 'release_id': release['id'],
                                                   'chunk': chunk.model_dump(mode='json')})
    else:
        release = await build_policy_release(repo, encoder, index, source_dir=source_dir, metadata=metadata,
            revision_ids=[], expected_active_id=None, actor_id=actor_id)
    await activate_release(repo, release['id'], None, actor_id)
    return release
