import asyncio
from unittest.mock import AsyncMock
from unittest.mock import patch
import pytest

from langchain_core.messages import AIMessage

from app.agent.harness.runtime import DeepHarnessRuntime
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn
from test_policy_rules import chunk
from test_policy_search import search_fixture


def test_greeting_does_not_require_a_knowledge_release():
    async def run():
        gateway = FakeGateway()
        gateway.transports = {'knowledge': object()}
        gateway.knowledge_release = AsyncMock(side_effect=RuntimeError('offline'))
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[AIMessage(content='Dạ, em chào mình ạ.')]),
                                     gateway, FakeMemory())
        try:
            assert (await runtime.run(turn('Xin chào'))).agent_text
            gateway.knowledge_release.assert_not_awaited()
        finally:
            await runtime.close()
    asyncio.run(run())


def test_cached_snapshot_uses_batch_reads_and_still_rejects_revocation():
    from app.mcp_servers.mcp_knowledge.repos.postgres import PolicyRepository
    from app.knowledge.schemas import SourceChunk, digest
    from app.knowledge.policy.source import content_hash
    from test_knowledge_repo import MemoryRepo

    class Repo(MemoryRepo, PolicyRepository):
        pass

    async def run():
        repo = Repo()
        row = chunk(content_hash=content_hash('7 ngày'))
        manifest = {'index_kind': 'hybrid', 'source_hashes': {row.chunk_id: row.source_hash},
                    'content_hashes': {row.chunk_id: row.content_hash},
                    'snapshot_hash': digest([row.model_dump(mode='json')])}
        release = {'id': 'r', 'status': 'ready', 'manifest': manifest, 'manifest_hash': digest(manifest)}
        await repo.put('releases', 'r', release)
        await repo.put('policy_sources', 'r:'+row.chunk_id, {'chunk': row.model_dump(mode='json')})
        await repo.snapshot(release)
        with patch.object(SourceChunk, 'model_validate', side_effect=AssertionError('unnecessary revalidation')):
            assert len(await repo.snapshot(release)) == 1
        await repo.put('policy_revocations', row.chunk_id, {'id': row.chunk_id})
        with pytest.raises(ValueError, match='revoked'):
            await repo.snapshot(release)
        assert len(repo._validated_snapshots) == 1
    asyncio.run(run())


def test_release_reference_does_not_reload_or_scan_vectors():
    async def run():
        service, repo, index = await search_fixture([chunk()])
        repo.snapshot = AsyncMock(side_effect=AssertionError('full snapshot'))
        index.verify = AsyncMock(side_effect=AssertionError('full index scan'))
        try:
            assert (await service.release_ref())['release_id'] == 'r1'
            repo.snapshot.assert_not_awaited()
            index.verify.assert_not_awaited()
        finally:
            await service.close()
    asyncio.run(run())
