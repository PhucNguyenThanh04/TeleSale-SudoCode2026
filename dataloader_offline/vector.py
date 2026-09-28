"""Incremental local embeddings and Qdrant indexes for public BTC knowledge."""

from __future__ import annotations

import json
import uuid
from typing import Any

from .source import PolicyChunk, digest, product_index_text

POLICY_COLLECTION = "btc_policy_v1"
PRODUCT_COLLECTION = "btc_products_v1"
POINT_NAMESPACE = uuid.UUID("18ab7aaa-86e0-5afb-bd12-379c1038c5f8")


def _point_id(collection: str, key: str) -> str:
    return str(uuid.uuid5(POINT_NAMESPACE, f"{collection}:{key}"))


def _specs(release: dict[str, Any]) -> dict[str, list[tuple[str, str, dict[str, Any]]]]:
    policy = []
    for chunk in release["chunks"]:
        assert isinstance(chunk, PolicyChunk)
        payload = {
            "kind": "policy", "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id, "title": chunk.title,
            "text": chunk.index_text, "access_level": chunk.access_level,
            "effective_from": chunk.effective_from,
            "effective_until": chunk.effective_until,
            "date_basis": chunk.date_basis, "source_hash": chunk.content_hash,
        }
        policy.append((chunk.chunk_id, chunk.index_text, payload))
    products = []
    for item in release["products"]["products"]:
        search_text = product_index_text(item)
        payload = {
            "kind": "product", "sku": item["sku"], "name": item["name"],
            "text": search_text, "access_level": "public",
            "source_hash": digest(search_text),
        }
        products.append((item["sku"], search_text, payload))
    return {POLICY_COLLECTION: policy, PRODUCT_COLLECTION: products}


def import_vectors(qdrant_url: str, model_name: str, release: dict[str, Any]) -> dict[str, int]:
    try:
        from qdrant_client import QdrantClient, models
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("Install dataloader_offline/requirements.txt to build Qdrant indexes") from exc

    # Local model only: source text is not sent to an embedding API.
    encoder = SentenceTransformer(model_name)
    dimension = encoder.get_sentence_embedding_dimension()
    if not dimension:
        raise ValueError("Embedding model has no known vector dimension")
    client = QdrantClient(url=qdrant_url, timeout=30)
    counts: dict[str, int] = {}
    for collection, specs in _specs(release).items():
        if not client.collection_exists(collection):
            client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
            )
        else:
            info = client.get_collection(collection)
            vector_config = info.config.params.vectors
            if not isinstance(vector_config, models.VectorParams) or vector_config.size != dimension:
                raise ValueError(f"{collection} has a different vector size; create a new collection version")
        changed = []
        for start in range(0, len(specs), 64):
            batch = specs[start:start + 64]
            ids = [_point_id(collection, key) for key, _, _ in batch]
            old = {str(point.id): point.payload or {} for point in client.retrieve(
                collection_name=collection, ids=ids, with_payload=True, with_vectors=False,
            )}
            for (key, content, payload), point_id in zip(batch, ids, strict=True):
                payload["embedding_model"] = model_name
                payload["index_hash"] = digest(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                if old.get(point_id, {}).get("index_hash") != payload["index_hash"]:
                    changed.append((point_id, content, payload))
        for start in range(0, len(changed), 32):
            batch = changed[start:start + 32]
            # E5 requires distinct prefixes for indexed passages and runtime queries.
            vectors = encoder.encode(
                [f"passage: {content}" for _, content, _ in batch],
                normalize_embeddings=True, convert_to_numpy=True,
            )
            client.upsert(
                collection_name=collection, wait=True,
                points=[models.PointStruct(id=point_id, vector=vector.tolist(), payload=payload)
                        for (point_id, _, payload), vector in zip(batch, vectors, strict=True)],
            )
        counts[collection] = len(changed)
    client.close()
    return counts
