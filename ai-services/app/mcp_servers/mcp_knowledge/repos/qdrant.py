"""Qdrant stores vectors and identifiers only; PostgreSQL owns serving content."""
from dataclasses import dataclass
import uuid
from qdrant_client import models


@dataclass(frozen=True)
class PolicyHit:
    chunk_id: str
    source_hash: str
    content_hash: str
    score: float


def point_id(release_id, chunk_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'mcp-knowledge:{release_id}:{chunk_id}'))


class HybridPolicyIndex:
    def __init__(self, client):
        self.client = client

    async def upsert(self, release, chunks, vectors, *, config):
        name = release['manifest']['collection']
        if not await self.client.collection_exists(name):
            await self.client.create_collection(name,
                vectors_config={'dense':models.VectorParams(size=config.dimension, distance=models.Distance.COSINE)},
                sparse_vectors_config={'sparse':models.SparseVectorParams()})
        if len(chunks) != len(vectors):
            raise ValueError('Missing vectors')
        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            points.append(models.PointStruct(id=point_id(release['id'], chunk.chunk_id),
                vector={'dense':vector.dense, 'sparse':models.SparseVector(
                    indices=vector.sparse_indices, values=vector.sparse_values)},
                payload={'chunk_id':chunk.chunk_id, 'release_id':release['id'],
                    'access_level':'public', 'source_hash':chunk.source_hash,
                    'content_hash':chunk.content_hash, 'supplement':chunk.supplement,
                    'model_fingerprint':config.fingerprint()}))
        if points:
            await self.client.upsert(name, points=points, wait=True)

    async def verify(self, release, config):
        manifest = release['manifest']
        if manifest['model_fingerprint'] != config.fingerprint():
            raise ValueError('Model fingerprint mismatch')
        name = manifest['collection']
        info = await self.client.get_collection(name)
        vectors = info.config.params.vectors
        if not isinstance(vectors, dict) or 'dense' not in vectors or vectors['dense'].size != config.dimension:
            raise ValueError('Dense index schema mismatch')
        if vectors['dense'].distance != models.Distance.COSINE or 'sparse' not in (info.config.params.sparse_vectors or {}):
            raise ValueError('Hybrid index schema mismatch')
        ids = manifest['source_hashes']
        if (await self.client.count(name, exact=True)).count != len(ids):
            raise ValueError('Incomplete collection')
        points = await self.client.retrieve(name, ids=[point_id(release['id'], key) for key in ids],
                                             with_payload=True, with_vectors=False)
        seen = set()
        for point in points:
            payload = point.payload or {}
            key = payload.get('chunk_id')
            if (key not in ids or payload.get('source_hash') != ids[key]
                    or payload.get('content_hash') != manifest['content_hashes'][key]
                    or payload.get('model_fingerprint') != config.fingerprint()
                    or payload.get('release_id') != release['id'] or payload.get('access_level') != 'public'):
                raise ValueError('Index manifest/hash mismatch')
            seen.add(key)
        if seen != set(ids):
            raise ValueError('Incomplete manifest')

    async def query(self, vector, *, release, access_filter, config, include_supplements=True):
        must = [models.FieldCondition(key='release_id',match=models.MatchValue(value=release['id'])),
                models.FieldCondition(key='access_level',match=models.MatchValue(value=access_filter)),
                models.FieldCondition(key='model_fingerprint',match=models.MatchValue(value=config.fingerprint()))]
        if not include_supplements:
            must.append(models.FieldCondition(key='supplement',match=models.MatchValue(value=False)))
        allowed = models.Filter(must=must)
        response = await self.client.query_points(collection_name=release['manifest']['collection'],
            prefetch=[models.Prefetch(query=vector.dense, using='dense', filter=allowed,
                          limit=config.dense_candidates, score_threshold=config.dense_threshold),
                      models.Prefetch(query=models.SparseVector(indices=vector.sparse_indices,values=vector.sparse_values),
                          using='sparse', filter=allowed, limit=config.sparse_candidates,
                          score_threshold=config.sparse_threshold)],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=config.dense_candidates+config.sparse_candidates, query_filter=allowed,
            with_payload=['chunk_id','source_hash','content_hash'], with_vectors=False)
        return [PolicyHit(p.payload['chunk_id'],p.payload['source_hash'],p.payload['content_hash'],float(p.score))
                for p in response.points if p.payload and {'chunk_id','source_hash','content_hash'} <= p.payload.keys()]
