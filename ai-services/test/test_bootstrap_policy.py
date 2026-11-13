"""A fresh knowledge database can reuse BTC vectors but not old gap content."""
import asyncio
import pytest

from btc_data import btc_data_dir
from qdrant_client import AsyncQdrantClient

from test_knowledge_repo import MemoryRepo
from test_policy_embedding import Backend, runtime_config


def test_fresh_knowledge_restores_only_base_without_embedding_again(monkeypatch):
    from app.bootstrap.policy import initialize_base
    from app.knowledge.policy.source import default_metadata
    from app.knowledge.services.publish import build_policy_release
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
    config = runtime_config(max_tokens=8000, deadline_seconds=10, dependency_timeout_seconds=2)
    from app.configs import get_settings
    settings = get_settings().model_copy(update={'knowledge_policy_config_file': None})
    monkeypatch.setattr('app.configs.get_settings', lambda: settings)
    async def run():
        backend = Backend(); encoder = PolicyEncoder(config, backend)
        client = AsyncQdrantClient(':memory:'); index = HybridPolicyIndex(client)
        old = MemoryRepo(); await old.put('permissions', 'bootstrap', {'permissions': ['knowledge_review']})
        args = dict(source_dir=btc_data_dir()/'policy', metadata=default_metadata(), actor_id='bootstrap')
        try:
            base = await build_policy_release(old, encoder, index, revision_ids=[], expected_active_id=None, **args)
            calls = len(backend.calls)
            fresh = MemoryRepo(); await fresh.put('permissions', 'bootstrap', {'permissions': ['knowledge_review']})
            restored = await initialize_base(fresh, encoder, index, cache=base, **args)
            assert restored['manifest']['items'] == []
            assert len(backend.calls) == calls
            assert await fresh.rows('gaps') == []
            assert await fresh.rows('revisions') == []
            assert (await fresh.get('active', 'current'))['release_id'] == base['id']
            assert all(not r['chunk']['supplement'] for r in await fresh.rows('policy_sources'))
            bad = dict(base, manifest=dict(base['manifest'], items=[{'id': 'old-approved-content'}]))
            other = MemoryRepo(); await other.put('permissions', 'bootstrap', {'permissions': ['knowledge_review']})
            rebuilt = await initialize_base(other, encoder, index, cache=bad, **args)
            assert rebuilt['manifest']['items'] == []
            assert len(backend.calls) > calls
        finally:
            await encoder.close(); await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('corruption', ['missing', 'wrong_dimension'])
def test_invalid_vector_cache_is_rebuilt_instead_of_served(monkeypatch, corruption):
    from app.bootstrap.policy import initialize_base
    from app.knowledge.policy.source import default_metadata
    from app.knowledge.services.publish import build_policy_release
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
    from qdrant_client import models
    config = runtime_config(max_tokens=8000, deadline_seconds=10, dependency_timeout_seconds=2)
    from app.configs import get_settings
    settings = get_settings().model_copy(update={'knowledge_policy_config_file': None})
    monkeypatch.setattr('app.configs.get_settings', lambda: settings)
    async def run():
        backend = Backend(); encoder = PolicyEncoder(config, backend)
        client = AsyncQdrantClient(':memory:'); index = HybridPolicyIndex(client)
        old = MemoryRepo(); await old.put('permissions', 'bootstrap', {'permissions': ['knowledge_review']})
        args = dict(source_dir=btc_data_dir()/'policy', metadata=default_metadata(), actor_id='bootstrap')
        try:
            base = await build_policy_release(old, encoder, index, revision_ids=[], expected_active_id=None, **args)
            await client.delete_collection(base['manifest']['collection'])
            if corruption == 'wrong_dimension':
                await client.create_collection(base['manifest']['collection'],
                    vectors_config={'dense': models.VectorParams(size=3, distance=models.Distance.COSINE)})
            fresh = MemoryRepo(); await fresh.put('permissions', 'bootstrap', {'permissions': ['knowledge_review']})
            restored = await initialize_base(fresh, encoder, index, cache=base, **args)
            await index.verify(restored, config)
            assert restored['manifest']['items'] == []
        finally:
            await encoder.close(); await client.close()
    asyncio.run(run())
