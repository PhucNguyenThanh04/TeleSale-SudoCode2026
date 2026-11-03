import asyncio
from qdrant_client import AsyncQdrantClient
from test_policy_embedding import runtime_config
from test_policy_rules import chunk
from app.knowledge.schemas import HybridVector


def test_hybrid_index_filters_both_branches_and_checks_full_manifest():
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
    async def run():
        client = AsyncQdrantClient(':memory:')
        index = HybridPolicyIndex(client)
        config = runtime_config()
        row = chunk()
        release = {'id':'r1', 'manifest': {'collection':'policy_test', 'model_fingerprint':config.fingerprint(),
            'source_hashes':{row.chunk_id:row.source_hash}, 'content_hashes':{row.chunk_id:row.content_hash}}}
        vector = HybridVector(dense=[1,0], sparse_indices=[1], sparse_values=[1])
        await index.upsert(release, [row], [vector], config=config)
        await index.verify(release, config)
        hits = await index.query(vector, release=release, access_filter='public', config=config)
        assert [h.chunk_id for h in hits] == ['DT-01']
        other = {'id':'forged', 'manifest':release['manifest']}
        assert await index.query(vector, release=other, access_filter='public', config=config) == []
        release['manifest']['source_hashes']['DT-01'] = 'wrong'
        try:
            await index.verify(release, config)
        except ValueError:
            pass
        else:
            raise AssertionError('Corrupt manifest accepted')
        await client.close()
    asyncio.run(run())
