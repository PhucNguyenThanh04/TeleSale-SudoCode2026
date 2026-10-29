"""Policy retrieval over PostgreSQL-authorized chunks and an optional dense index."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from functools import lru_cache
from typing import Any


LOGGER = logging.getLogger("app.mcp.catalog.retrieval")
COLLECTION = "btc_policy_v1"
MODEL = "intfloat/multilingual-e5-small"


def lexical_rank(query: str, chunks: list[dict]) -> list[tuple[str, int]]:
    """Keep the existing lexical baseline while making its scores inspectable."""
    words = set(re.findall(r"\w+", query.casefold()))
    ranked = []
    for chunk in chunks:
        haystack = f"{chunk['title']} {chunk['body']}".casefold()
        score = sum(word in haystack for word in words if len(word) > 1)
        if score:
            ranked.append((chunk["chunk_id"], score))
    return sorted(ranked, key=lambda item: (-item[1], item[0]))


@lru_cache(maxsize=2)
def _encoder(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def warmup() -> bool:
    """Load the local encoder before the MCP starts serving policy queries."""
    if os.getenv("POLICY_RAG_ENABLED", "false").lower() != "true":
        return False
    try:
        _encoder(os.getenv("EMBEDDING_MODEL", MODEL))
    except Exception as exc:
        LOGGER.warning("policy encoder warmup unavailable | error_type=%s", type(exc).__name__)
        return False
    LOGGER.info("policy encoder ready")
    return True


def _dense_search(query: str, allowed: dict[str, dict], *, url: str,
                  model_name: str) -> list[tuple[str, float, str]]:
    """Fetch IDs/scores only; source content always comes from PostgreSQL."""
    from qdrant_client import QdrantClient, models

    vector = _encoder(model_name).encode(
        f"query: {query}", normalize_embeddings=True, convert_to_numpy=True,
    )
    client = QdrantClient(url=url, timeout=2)
    try:
        response = client.query_points(
            collection_name=COLLECTION, query=vector.tolist(), limit=20,
            query_filter=models.Filter(must=[
                models.FieldCondition(key="chunk_id", match=models.MatchAny(any=list(allowed))),
                models.FieldCondition(key="access_level", match=models.MatchValue(value="public")),
                models.FieldCondition(key="embedding_model", match=models.MatchValue(value=model_name)),
            ]),
            with_payload=["chunk_id", "source_hash"], with_vectors=False,
        )
    finally:
        client.close()
    hits = []
    for point in response.points:
        payload = point.payload or {}
        chunk_id = payload.get("chunk_id")
        source = allowed.get(chunk_id)
        if source:
            hits.append((chunk_id, float(point.score), payload.get("source_hash")))
    return hits


def fuse(lexical: list[tuple[str, int]], dense: list[tuple[str, float]]) -> list[str]:
    """Reciprocal-rank fusion: scores from different retrievers are incomparable."""
    scores: dict[str, float] = {}
    for ranking in (lexical, dense):
        for rank, (chunk_id, _) in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (60 + rank)
    return sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))


async def retrieve(query: str, chunks: list[dict], *, dense_enabled: bool | None = None,
                   dense_search=None) -> dict[str, Any]:
    """Return authorized source rows and safe, bounded retrieval diagnostics."""
    authorized = {chunk["chunk_id"]: chunk for chunk in chunks}
    lexical = lexical_rank(query, chunks)
    if dense_enabled is None:
        dense_enabled = os.getenv("POLICY_RAG_ENABLED", "false").lower() == "true"
    dense: list[tuple[str, float]] = []
    status = "lexical_only"
    if dense_enabled and authorized:
        search = dense_search or _dense_search
        try:
            candidates = await asyncio.wait_for(asyncio.to_thread(
                search, query, authorized,
                url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
                model_name=os.getenv("EMBEDDING_MODEL", MODEL),
            ), timeout=5)
            # Revalidate even when a replacement retriever is injected.
            dense = [(chunk_id, score) for chunk_id, score, source_hash in candidates
                     if chunk_id in authorized and source_hash
                     and authorized[chunk_id].get("source_hash") == source_hash]
            status = "hybrid"
        except Exception as exc:
            status = "degraded_lexical"
            LOGGER.warning("dense retrieval unavailable | error_type=%s", type(exc).__name__)
    ordered = fuse(lexical, dense) if status == "hybrid" else [key for key, _ in lexical]
    selected = [authorized[key] for key in ordered[:5]]
    if not selected and status != "degraded_lexical":
        status = "no_evidence"
    diagnostics = {
        "status": status,
        "lexical": [{"chunk_id": key, "score": score} for key, score in lexical[:20]],
        "dense": [{"chunk_id": key, "score": round(score, 4)} for key, score in dense[:20]],
        "selected_ids": [chunk["chunk_id"] for chunk in selected],
        "authorized_count": len(authorized),
    }
    LOGGER.info("policy retrieval | %s", diagnostics)
    return {"chunks": selected, "retrieval_status": status}
