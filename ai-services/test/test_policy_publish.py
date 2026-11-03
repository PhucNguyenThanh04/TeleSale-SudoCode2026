import asyncio
import pytest
from qdrant_client import AsyncQdrantClient
from btc_data import btc_data_dir
from test_knowledge_repo import MemoryRepo
from test_policy_embedding import runtime_config, Backend


def test_release_build_is_idempotent_and_requires_index_ready_before_activation():
    from app.knowledge.services.publish import build_policy_release
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
    from app.mcp_servers.mcp_knowledge.repos.postgres import PolicyRepository
    from app.knowledge.policy.source import default_metadata
    from app.knowledge.services.releases import activate_release
    class Repo(MemoryRepo, PolicyRepository):
        pass
    async def run():
        repo=Repo()
        await repo.put('permissions','reviewer',{'permissions':['knowledge_review']})
        config=runtime_config(max_tokens=8000)
        encoder=PolicyEncoder(config,Backend())
        await encoder.start()
        client=AsyncQdrantClient(':memory:')
        index=HybridPolicyIndex(client)
        args=dict(source_dir=btc_data_dir()/'policy',metadata=default_metadata(),revision_ids=[],expected_active_id=None,actor_id='reviewer')
        first=await build_policy_release(repo,encoder,index,**args)
        second=await build_policy_release(repo,encoder,index,**args)
        assert first['id']==second['id']
        assert (await repo.get('active','current')) is None
        await activate_release(repo,first['id'],None,'reviewer')
        assert (await repo.resolve_release())['id']==first['id']
        assert len(await repo.snapshot(first))==93
        await repo.put('policy_revocations','DT-01',{'id':'DT-01'})
        with pytest.raises(ValueError,match='revoked'):
            await repo.snapshot(first)
        await encoder.close()
        await client.close()
    asyncio.run(run())


def test_failed_index_never_marks_release_ready():
    from app.knowledge.services.publish import build_policy_release
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    from app.knowledge.policy.source import default_metadata
    class BrokenIndex:
        async def upsert(self,*args,**kwargs):
            raise ConnectionError('offline')
    async def run():
        repo=MemoryRepo()
        await repo.put('permissions','reviewer',{'permissions':['knowledge_review']})
        encoder=PolicyEncoder(runtime_config(max_tokens=8000),Backend())
        await encoder.start()
        with pytest.raises(ConnectionError):
            await build_policy_release(repo,encoder,BrokenIndex(),source_dir=btc_data_dir()/'policy',
                metadata=default_metadata(),revision_ids=[],expected_active_id=None,actor_id='reviewer')
        assert all(row['status']!='ready' for row in await repo.rows('releases'))
        assert await repo.get('active','current') is None
        await encoder.close()
    asyncio.run(run())


def test_revoked_approval_during_encode_blocks_ready_state():
    from app.knowledge.services.publish import build_policy_release
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    from app.knowledge.policy.source import default_metadata
    from test_knowledge_revisions import fixture
    from test_knowledge_releases import approved
    async def run():
        repo=await fixture()
        from app.knowledge.policy.source import parse_policy_sources
        current = {c.chunk_id:c for c in parse_policy_sources(btc_data_dir()/'policy', default_metadata())}
        repo.source_rows['DT-01']['source_hash'] = current['DT-01'].source_hash
        revision=await approved(repo)
        class RevokeIndex:
            async def upsert(self,*args,**kwargs):
                current=await repo.get('revisions',revision['id'])
                current['status']='erased'
                await repo.put('revisions',revision['id'],current)
            async def verify(self,*args):
                pass
        encoder=PolicyEncoder(runtime_config(max_tokens=8000),Backend())
        await encoder.start()
        with pytest.raises(Exception,match='Approved revision'):
            await build_policy_release(repo,encoder,RevokeIndex(),source_dir=btc_data_dir()/'policy',
                metadata=default_metadata(),revision_ids=[revision['id']],expected_active_id=None,actor_id='reviewer')
        assert all(row['status']!='ready' for row in await repo.rows('releases'))
        await encoder.close()
    asyncio.run(run())


def test_snapshot_metadata_tampering_is_detected_even_when_body_hash_matches():
    from app.mcp_servers.mcp_knowledge.repos.postgres import PolicyRepository
    from app.knowledge.policy.source import content_hash
    from app.knowledge.schemas import digest
    from test_policy_rules import chunk
    class Repo(MemoryRepo,PolicyRepository):
        pass
    async def run():
        repo=Repo()
        row=chunk(content_hash=content_hash('7 ngày'))
        snapshot=[row.model_dump(mode='json')]
        manifest={'index_kind':'hybrid','source_hashes':{row.chunk_id:row.source_hash},
            'content_hashes':{row.chunk_id:row.content_hash},'snapshot_hash':digest(snapshot)}
        release={'id':'r','status':'ready','manifest':manifest,'manifest_hash':digest(manifest)}
        await repo.put('releases','r',release)
        stored={'id':'r:DT-01','release_id':'r','chunk':snapshot[0]}
        await repo.put('policy_sources','r:DT-01',stored)
        assert len(await repo.snapshot(release))==1
        stored['chunk']['effective_from']='2000-01-01'
        await repo.put('policy_sources','r:DT-01',stored)
        with pytest.raises(ValueError,match='snapshot'):
            await repo.snapshot(release)
    asyncio.run(run())
