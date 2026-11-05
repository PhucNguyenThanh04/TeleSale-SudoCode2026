import asyncio
import pytest
from qdrant_client import AsyncQdrantClient
from test_policy_embedding import runtime_config
from test_policy_rules import chunk
from app.knowledge.schemas import HybridVector, digest


@pytest.mark.parametrize('field,value,remove', [
    ('effective_until',None,True), ('effective_until','2099-12-31',False),
    ('date_basis','on',False), ('source',None,True), ('content','tampered',False),
    ('rules',None,True), ('required_links',None,True), ('model_fingerprint','wrong',False),
    ('release_id','wrong',False), ('source_hash','wrong',False),
])
def test_verify_rejects_metadata_tampering_even_when_hash_fields_match(field,value,remove):
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex,point_id
    async def run():
        client=AsyncQdrantClient(':memory:');index=HybridPolicyIndex(client);config=runtime_config()
        row=chunk(effective_until=None)
        release={'id':'r','manifest':{'collection':'tamper','model_fingerprint':config.fingerprint(),
            'source_hashes':{row.chunk_id:row.source_hash},'content_hashes':{row.chunk_id:row.content_hash},
            'snapshot_hash':digest([row.model_dump(mode='json')])}}
        try:
            await upsert_bm25(index, release,[row],[HybridVector(dense=[1,0],sparse_indices=[1],sparse_values=[1])],config=config)
            await index.verify(release,config,chunks=[row])  # Present null expiry is valid.
            ids=[point_id('r',row.chunk_id)]
            if remove:
                await client.delete_payload('tamper',[field],ids)
            else:
                await client.set_payload('tamper',{field:value},ids)
            with pytest.raises(ValueError):
                await index.verify(release,config,chunks=[row])
        finally:await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('fault',['missing','extra','access','dimension','dense_vector','sparse_vector'])
def test_index_verification_rejects_wrong_points_and_schema(fault):
    from qdrant_client import models
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex,point_id
    async def run():
        client=AsyncQdrantClient(':memory:');index=HybridPolicyIndex(client);config=runtime_config()
        row=chunk()
        release={'id':'r','manifest':{'collection':'points','model_fingerprint':config.fingerprint(),
            'source_hashes':{row.chunk_id:row.source_hash},'content_hashes':{row.chunk_id:row.content_hash},
            'snapshot_hash':digest([row.model_dump(mode='json')])}}
        try:
            size=3 if fault=='dimension' else 2
            if fault=='dimension':
                await client.create_collection('points',vectors_config={'dense':models.VectorParams(size=3,distance=models.Distance.COSINE)},
                    sparse_vectors_config={'sparse':models.SparseVectorParams()})
            await upsert_bm25(index, release,[row],[HybridVector(dense=[1]+[0]*(size-1),sparse_indices=[1],sparse_values=[1])],config=config)
            ids=[point_id('r',row.chunk_id)]
            if fault=='missing':await client.delete('points',ids)
            if fault=='extra':
                await client.upsert('points',[models.PointStruct(id=point_id('r','extra'),vector={'dense':[1,0]},payload={})])
            if fault=='access':await client.set_payload('points',{'access_level':'restricted'},ids)
            if fault in ['dense_vector','sparse_vector']:
                await client.delete_vectors('points',vectors=[fault.split('_')[0]],points=ids)
            with pytest.raises(ValueError):await index.verify(release,config,chunks=[row])
        finally:await client.close()
    asyncio.run(run())


def test_payload_shows_safe_btc_text_source_dates_and_conditions():
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex, point_id
    async def run():
        client = AsyncQdrantClient(':memory:')
        index = HybridPolicyIndex(client)
        config = runtime_config()
        row = chunk(effective_from='2026-10-01', effective_until='2026-12-31',
            required_context=['order_date'], required_links=['DT-OLD-01'])
        release = {'id':'r1', 'manifest': {'collection':'policy_payload', 'model_fingerprint':config.fingerprint(),
            'source_hashes':{row.chunk_id:row.source_hash}, 'content_hashes':{row.chunk_id:row.content_hash}}}
        vector = HybridVector(dense=[1,0], sparse_indices=[1], sparse_values=[1])
        try:
            await upsert_bm25(index, release, [row], [vector], config=config)
            points = await client.retrieve('policy_payload', [point_id('r1', row.chunk_id)], with_vectors=True)
            payload = points[0].payload
            assert payload['content'] == row.content
            assert payload['source'] == row.source
            assert payload['section_id'] == row.section_id
            assert payload['document_id'] == row.document_id
            assert payload['effective_from'] == '2026-10-01'
            assert payload['effective_until'] == '2026-12-31'
            assert payload['date_basis'] == row.date_basis
            assert payload['required_context'] == ['order_date']
            assert payload['required_links'] == ['DT-OLD-01']
            assert payload['rules'] == []
            assert payload['transformation'] == 'identity'
        finally:
            await client.close()
    asyncio.run(run())


def test_refresh_payload_adds_missing_fields_without_replacing_vectors():
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex, point_id
    async def run():
        client = AsyncQdrantClient(':memory:')
        index = HybridPolicyIndex(client)
        config = runtime_config()
        row = chunk(effective_from=None, effective_until=None)
        release = {'id':'r1', 'manifest': {'collection':'policy_refresh', 'model_fingerprint':config.fingerprint(),
            'source_hashes':{row.chunk_id:row.source_hash}, 'content_hashes':{row.chunk_id:row.content_hash},
            'snapshot_hash':digest([row.model_dump(mode='json')])}}
        vector = HybridVector(dense=[1,0], sparse_indices=[1], sparse_values=[1])
        try:
            await upsert_bm25(index, release, [row], [vector], config=config)
            ids = [point_id('r1', row.chunk_id)]
            await client.delete_payload('policy_refresh', ['content','source','effective_from','effective_until'], ids)
            before = (await client.retrieve('policy_refresh', ids, with_vectors=True))[0]
            await index.refresh_payloads(release, [row], config=config)
            after = (await client.retrieve('policy_refresh', ids, with_vectors=True))[0]
            assert after.vector == before.vector
            assert after.payload['content'] == row.content
            assert after.payload['effective_from'] is None
            assert after.payload['effective_until'] is None
            import pytest
            with pytest.raises(ValueError, match='snapshot'):
                await index.refresh_payloads(release, [row.model_copy(update={'source_hash':'stale'})], config=config)
            with pytest.raises(ValueError, match='snapshot'):
                await index.refresh_payloads(release, [row.model_copy(update={'conflict':True})], config=config)
            assert (await client.retrieve('policy_refresh', ids))[0].payload == after.payload
        finally:
            await client.close()
    asyncio.run(run())


def test_customer_derived_supplement_content_stays_in_postgres():
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex, point_id
    async def run():
        client = AsyncQdrantClient(':memory:')
        config = runtime_config()
        row = chunk(chunk_id='KG-test', section_id='KG-test', document_id='approved-faq',
            supplement=True, search_aliases=['customer derived question'])
        release = {'id':'r1', 'manifest': {'collection':'policy_supplement'}}
        try:
            await upsert_bm25(HybridPolicyIndex(client), release, [row],
                [HybridVector(dense=[1,0], sparse_indices=[1], sparse_values=[1])], config=config)
            payload = (await client.retrieve('policy_supplement', [point_id('r1', row.chunk_id)]))[0].payload
            assert payload['content'] is None
            assert payload['source'] is None
            assert 'search_aliases' not in payload
            assert 'source_references' not in payload
            assert 'effective_until' in payload
        finally:
            await client.close()
    asyncio.run(run())


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
        await upsert_bm25(index, release, [row], [vector], config=config)
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


def test_new_collection_uses_idf_and_skips_empty_lexical_prefetch():
    from qdrant_client import models
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
    async def run():
        client=AsyncQdrantClient(':memory:');index=HybridPolicyIndex(client);config=runtime_config()
        row=chunk()
        release={'id':'idf','manifest':{'collection':'idf'}}
        vector=HybridVector(dense=[1,0],sparse_indices=[1],sparse_values=[1])
        try:
            await upsert_bm25(index, release,[row],[vector],config=config)
            info=await client.get_collection('idf')
            assert info.config.params.sparse_vectors['sparse'].modifier == models.Modifier.IDF
            query=HybridVector(dense=[1,0],sparse_indices=[],sparse_values=[])
            assert [h.chunk_id for h in await index.query(query,release=release,access_filter='public',config=config)]==[row.chunk_id]
        finally: await client.close()
    asyncio.run(run())


async def upsert_bm25(index, release, rows, vectors, *, config):
    from app.mcp_servers.mcp_knowledge.services.bm25 import build_bm25_artifact, BM25Encoder, document_text
    release['manifest']['bm25']=build_bm25_artifact([document_text(r) for r in rows],config)
    encoder=BM25Encoder(release['manifest']['bm25'])
    vectors=[v.model_copy(update=dict(zip(('sparse_indices','sparse_values'),encoder.encode_document(document_text(r))))) for r,v in zip(rows,vectors,strict=True)]
    await index.upsert(release,rows,vectors,config=config)


def test_qdrant_bm25_idf_is_applied_once():
    import math
    from qdrant_client import models
    from app.mcp_servers.mcp_knowledge.services.bm25 import build_bm25_artifact, BM25Encoder
    async def run():
        client=AsyncQdrantClient(':memory:')
        try:
            config=runtime_config()
            artifact=build_bm25_artifact(['a a b','b'],config)
            lexical=BM25Encoder(artifact)
            await client.create_collection('score',vectors_config={},
                sparse_vectors_config={'sparse':models.SparseVectorParams(modifier=models.Modifier.IDF)})
            points=[]
            for i,text in enumerate(['a a b','b']):
                ids,weights=lexical.encode_document(text)
                points.append(models.PointStruct(id=i,vector={'sparse':models.SparseVector(indices=ids,values=weights)}))
            await client.upsert('score',points)
            ids,weights=lexical.encode_query('a')
            response=await client.query_points('score',using='sparse',query=models.SparseVector(indices=ids,values=weights))
            expected=2*2.2/(2+1.2*(.25+.75*3/2))*math.log(2)
            assert response.points[0].id==0 and response.points[0].score==pytest.approx(expected,rel=1e-6)
        finally:await client.close()
    asyncio.run(run())
