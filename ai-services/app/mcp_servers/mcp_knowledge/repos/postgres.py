from app.knowledge.repos.postgres import KnowledgeRepo
from app.knowledge.schemas import digest
from app.knowledge.schemas import SourceChunk


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
            rows = []
            for key in release['manifest']['source_hashes']:
                if await tx.get('policy_revocations',key):
                    raise ValueError('Policy source revoked')
                row = await tx.get('policy_sources',release['id']+':'+key)
                if not row:
                    raise ValueError('Missing policy snapshot')
                chunk = SourceChunk.model_validate(row['chunk'])
                if chunk.source_hash != release['manifest']['source_hashes'][key] or chunk.content_hash != release['manifest']['content_hashes'][key]:
                    raise ValueError('Policy snapshot hash mismatch')
                from app.knowledge.policy.source import content_hash
                if content_hash(chunk.content) != chunk.content_hash:
                    raise ValueError('Serving content corrupt')
                for ref in chunk.source_references:
                    if await tx.get('policy_revocations',ref['chunk_id']):
                        raise ValueError('Supplement source revoked')
                rows.append(chunk)
            if digest(sorted([c.model_dump(mode='json') for c in rows],key=lambda row:row['chunk_id'])) != release['manifest'].get('snapshot_hash'):
                raise ValueError('Serving snapshot metadata hash mismatch')
            return rows

    async def release_ref(self, release_id=None):
        row = await self.resolve_release(release_id)
        return {'release_id':row['id'],'manifest_hash':row['manifest_hash']}
