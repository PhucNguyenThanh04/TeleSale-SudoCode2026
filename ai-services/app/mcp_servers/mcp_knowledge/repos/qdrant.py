from dataclasses import dataclass
import uuid
import math
from qdrant_client import models
from app.knowledge.schemas import digest
from app.mcp_servers.mcp_knowledge.services.bm25 import BM25Encoder, document_text, build_bm25_artifact


@dataclass(frozen=True)
class PolicyHit:
    chunk_id: str
    source_hash: str
    content_hash: str
    score: float


def point_id(release_id, chunk_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'mcp-knowledge:{release_id}:{chunk_id}'))


def _payload(release, chunk, config):
    metadata = chunk.model_dump(mode='json', include={
        'chunk_id', 'section_id', 'document_id', 'access_level', 'source_hash', 'content_hash',
        'supplement', 'evidence_type', 'date_basis', 'effective_from', 'effective_until',
        'required_context', 'required_links', 'rules', 'conflict', 'transformation'})
    return metadata | {
        'release_id': release['id'], 'model_fingerprint': config.fingerprint(),
        'lexical_fingerprint': release['manifest'].get('bm25', {}).get('hash'),
        'content': None if chunk.supplement else chunk.content,
        'source': None if chunk.supplement else chunk.source,
    }


class HybridPolicyIndex:
    def __init__(self, client):
        self.client = client

    async def upsert(self, release, chunks, vectors, *, config):
        name = release['manifest']['collection']
        if not await self.client.collection_exists(name):
            await self.client.create_collection(name,
                shard_number=1, vectors_config={'dense':models.VectorParams(size=config.dimension, distance=models.Distance.COSINE)},
                sparse_vectors_config={'sparse':models.SparseVectorParams(modifier=models.Modifier.IDF)})
        if len(chunks) != len(vectors):
            raise ValueError('Missing vectors')
        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            points.append(models.PointStruct(id=point_id(release['id'], chunk.chunk_id),
                vector={'dense':vector.dense, 'sparse':models.SparseVector(
                    indices=vector.sparse_indices, values=vector.sparse_values)},
                payload=_payload(release, chunk, config)))
        if points:
            await self.client.upsert(name, points=points, wait=True)

    async def refresh_payloads(self, release, chunks, *, config):
        chunks = list(chunks)
        snapshot = sorted([c.model_dump(mode='json') for c in chunks], key=lambda row:row['chunk_id'])
        if digest(snapshot) != release['manifest'].get('snapshot_hash'):
            raise ValueError('Policy snapshot mismatch')
        await self.verify(release, config)
        for chunk in chunks:
            await self.client.overwrite_payload(release['manifest']['collection'],
                payload=_payload(release, chunk, config),
                points=[point_id(release['id'], chunk.chunk_id)], wait=True)
        await self.verify(release, config, chunks=chunks)

    async def verify(self, release, config, *, chunks=None):
        manifest = release['manifest']
        lexical = BM25Encoder(manifest['bm25'])
        expected = None
        if chunks is not None:
            chunks = list(chunks)
            if build_bm25_artifact([document_text(c) for c in chunks], config) != manifest['bm25']:
                raise ValueError('BM25 corpus artifact mismatch')
            snapshot = sorted([c.model_dump(mode='json') for c in chunks], key=lambda row:row['chunk_id'])
            if digest(snapshot) != manifest.get('snapshot_hash'):
                raise ValueError('Policy snapshot mismatch')
            expected = {c.chunk_id:_payload(release,c,config) for c in chunks}
            if len(expected)!=len(chunks) or set(expected)!=set(manifest['source_hashes']):
                raise ValueError('Policy snapshot IDs mismatch')
        if manifest['model_fingerprint'] != config.fingerprint():
            raise ValueError('Model fingerprint mismatch')
        name = manifest['collection']
        info = await self.client.get_collection(name)
        vectors = info.config.params.vectors
        if not isinstance(vectors, dict) or 'dense' not in vectors or vectors['dense'].size != config.dimension:
            raise ValueError('Dense index schema mismatch')
        if vectors['dense'].distance != models.Distance.COSINE or 'sparse' not in (info.config.params.sparse_vectors or {}):
            raise ValueError('Hybrid index schema mismatch')
        if info.config.params.sparse_vectors['sparse'].modifier != models.Modifier.IDF or info.config.params.shard_number not in (None, 1):
            raise ValueError('BM25 IDF/shard configuration mismatch')
        ids = manifest['source_hashes']
        if (await self.client.count(name, exact=True)).count != len(ids):
            raise ValueError('Incomplete collection')
        points = await self.client.retrieve(name, ids=[point_id(release['id'], key) for key in ids],
                                             with_payload=True, with_vectors=expected is not None)
        seen = set()
        for point in points:
            payload = point.payload or {}
            key = payload.get('chunk_id')
            if (key not in ids or payload.get('source_hash') != ids[key]
                    or payload.get('content_hash') != manifest['content_hashes'][key]
                    or payload.get('model_fingerprint') != config.fingerprint()
                    or payload.get('lexical_fingerprint') != manifest['bm25']['hash']
                    or payload.get('release_id') != release['id'] or payload.get('access_level') != 'public'):
                raise ValueError('Index manifest/hash mismatch')
            if expected is not None:
                vectors = point.vector or {}
                dense = vectors.get('dense') if isinstance(vectors,dict) else None
                sparse = vectors.get('sparse') if isinstance(vectors,dict) else None
                if (not isinstance(dense,list) or len(dense)!=config.dimension
                        or not all(math.isfinite(v) for v in dense)
                        or abs(sum(v*v for v in dense)-1)>0.001
                        or not isinstance(sparse,models.SparseVector)
                        or len(sparse.indices)!=len(sparse.values)
                        or len(set(sparse.indices))!=len(sparse.indices)
                        or any(i<0 for i in sparse.indices)
                        or any(not math.isfinite(v) or v<=0 for v in sparse.values)):
                    raise ValueError('Hybrid vector mismatch: '+key)
                expected_sparse = lexical.encode_document(document_text(next(c for c in chunks if c.chunk_id == key)))
                if sparse.indices != expected_sparse[0] or any(abs(a-b)>1e-6 for a,b in zip(sparse.values, expected_sparse[1], strict=True)):
                    raise ValueError('BM25 vector mismatch: '+key)
                wanted = expected[key]
                for field in sorted(set(wanted) | set(payload)):
                    if field not in payload or field not in wanted or digest(payload[field])!=digest(wanted[field]):
                        raise ValueError(f'Payload mismatch: {key}.{field}')
            seen.add(key)
        if seen != set(ids):
            raise ValueError('Incomplete manifest')

    async def query(self, vector, *, release, access_filter, config, include_supplements=True):
        must = [models.FieldCondition(key='release_id',match=models.MatchValue(value=release['id'])),
                models.FieldCondition(key='access_level',match=models.MatchValue(value=access_filter)),
                models.FieldCondition(key='model_fingerprint',match=models.MatchValue(value=config.fingerprint()))]
        must.append(models.FieldCondition(key='lexical_fingerprint', match=models.MatchValue(value=release['manifest']['bm25']['hash'])))
        if not include_supplements:
            must.append(models.FieldCondition(key='supplement',match=models.MatchValue(value=False)))
        allowed = models.Filter(must=must)
        prefetch = [models.Prefetch(query=vector.dense, using='dense', filter=allowed,
                          limit=config.dense_candidates, score_threshold=config.dense_threshold)]
        if vector.sparse_indices:
            prefetch.append(models.Prefetch(query=models.SparseVector(
                indices=vector.sparse_indices, values=vector.sparse_values), using='sparse',
                filter=allowed, limit=config.sparse_candidates))
        response = await self.client.query_points(collection_name=release['manifest']['collection'],
            prefetch=prefetch, query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=config.dense_candidates+config.sparse_candidates, query_filter=allowed,
            with_payload=['chunk_id','source_hash','content_hash'], with_vectors=False)
        return [PolicyHit(p.payload['chunk_id'],p.payload['source_hash'],p.payload['content_hash'],float(p.score))
                for p in response.points if p.payload and {'chunk_id','source_hash','content_hash'} <= p.payload.keys()]
