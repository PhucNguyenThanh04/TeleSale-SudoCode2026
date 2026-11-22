from app.knowledge.repos.postgres import KnowledgeRepo
from app.knowledge.schemas import digest
from app.knowledge.schemas import SourceChunk
from collections import OrderedDict


class PolicyRepository(KnowledgeRepo):
    async def resolve_release(self, release_id=None):
        async with self.transaction() as tx:
            if release_id is None:
                release_id = (await tx.get('active','current') or {}).get('release_id')
            if release_id == 'btc-only':
                active = await tx.get('active', 'policy-btc') or {}
                release_id = active.get('release_id')
                if not release_id:
                    raise ValueError('BTC hybrid release unavailable')
            row = await tx.get('releases', release_id) if release_id else None
            if not row or row.get('status') != 'ready':
                raise ValueError('Hybrid release unavailable')
            manifest = row['manifest']
            if manifest.get('index_kind') != 'hybrid' or digest(manifest) != row.get('manifest_hash'):
                raise ValueError('Hybrid manifest invalid')
            return row

    async def snapshot(self, release):
        async with self.transaction() as tx:
            current = await tx.get('releases',release['id'])
            if not current or current.get('status') != 'ready' or current.get('manifest_hash') != release['manifest_hash'] or digest(current.get('manifest')) != release['manifest_hash']:
                raise ValueError('Pinned release revoked or changed')
            keys = list(release['manifest']['source_hashes'])
            stored = await tx.get_many('policy_sources', [release['id']+':'+key for key in keys])
            raw = [stored.get(release['id']+':'+key, {}).get('chunk') for key in keys]
            if any(row is None for row in raw):
                raise ValueError('Missing policy snapshot')
            references = set(keys)
            for row in raw:
                references.update(ref['chunk_id'] for ref in row.get('source_references', []))
            if await tx.get_many('policy_revocations', references):
                raise ValueError('Policy source revoked')
            cache = getattr(self, '_validated_snapshots', None)
            if cache is None:
                cache = self._validated_snapshots = OrderedDict()
            cache_key = (release['manifest_hash'], digest(raw))
            if cache_key in cache:
                cache.move_to_end(cache_key)
                return [chunk.model_copy(deep=True) for chunk in cache[cache_key]]
            rows = []
            for key, row in zip(keys, raw):
                chunk = SourceChunk.model_validate(row)
                if chunk.source_hash != release['manifest']['source_hashes'][key] or chunk.content_hash != release['manifest']['content_hashes'][key]:
                    raise ValueError('Policy snapshot hash mismatch')
                from app.knowledge.policy.source import content_hash
                if content_hash(chunk.content) != chunk.content_hash:
                    raise ValueError('Serving content corrupt')
                rows.append(chunk)
            if digest(sorted([c.model_dump(mode='json') for c in rows],key=lambda row:row['chunk_id'])) != release['manifest'].get('snapshot_hash'):
                raise ValueError('Serving snapshot metadata hash mismatch')
            cache[cache_key] = [chunk.model_copy(deep=True) for chunk in rows]
            while len(cache) > 8:
                cache.popitem(last=False)
            return rows

    async def release_ref(self, release_id=None):
        row = await self.resolve_release(release_id)
        return {'release_id':row['id'],'manifest_hash':row['manifest_hash']}
