import asyncio
from datetime import date
from app.mcp_servers.mcp_knowledge.schemas import PolicySearchInput, TrustedPolicyContext
from app.knowledge.schemas import digest
from app.mcp_servers.mcp_knowledge.repos.qdrant import PolicyHit
from test_policy_rules import chunk
from test_policy_embedding import runtime_config, Backend


class SearchRepo:
    def __init__(self, rows):
        self.rows=rows
        self.revoked=False
        config=runtime_config()
        from app.mcp_servers.mcp_knowledge.services.bm25 import build_bm25_artifact,document_text
        manifest={'schema_version':3,'pipeline':'cloudflare_dense_bm25',
            'bm25':build_bm25_artifact([document_text(r) for r in rows],config),'index_kind':'hybrid','collection':'test','model_fingerprint':config.fingerprint(),
            'config_hash':digest(config.model_dump(mode='json')),'checks':{'index_complete':True,'relevance_verified':True},
            'source_hashes':{r.chunk_id:r.source_hash for r in rows},'content_hashes':{r.chunk_id:r.content_hash for r in rows}}
        self.release={'id':'r1','manifest':manifest,'manifest_hash':digest(manifest),'status':'ready'}
    async def resolve_release(self, release_id=None):
        if release_id and release_id!='r1':
            raise ValueError('invalid pin')
        return self.release
    async def snapshot(self, release):
        if self.revoked:
            raise ValueError('source revoked')
        return self.rows


class Index:
    def __init__(self, rows):
        self.rows=rows
        self.calls=0
    async def verify(self,*args,**kwargs):
        pass
    async def query(self,*args,**kwargs):
        self.calls+=1
        return [PolicyHit(r.chunk_id,r.source_hash,r.content_hash,1.) for r in self.rows]


async def search_fixture(rows, hits=None, **config_changes):
    from app.mcp_servers.mcp_knowledge.services.knowledge import PolicySearchService
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    config=runtime_config(**config_changes)
    repo=SearchRepo(rows)
    repo.release['manifest']['model_fingerprint']=config.fingerprint()
    repo.release['manifest']['config_hash']=digest(config.model_dump(mode='json'))
    repo.release['manifest_hash']=digest(repo.release['manifest'])
    encoder=PolicyEncoder(config,Backend())
    index=Index(rows if hits is None else hits)
    service=PolicySearchService(repo,encoder,index,config)
    await service.start()
    return service,repo,index


def request_context(top_k=5):
    request=PolicySearchInput(query='đổi trả',on='2026-11-03',top_k=top_k)
    context=TrustedPolicyContext(request_id='req',principal='harness',on=request.on,
        verified_order_date=date(2026,10,10),date_source='order.status:OD-1')
    return request,context


def test_top_k_one_keeps_policy_and_exception_until_hard_limit():
    async def run():
        primary=chunk(required_links=['CL-01'])
        exception=chunk(chunk_id='CL-01',section_id='CL-01')
        service,repo,index=await search_fixture([primary,exception],hits=[primary])
        result=await service.search(*request_context(1))
        assert [r.chunk_id for r in result.evidence]==['DT-01','CL-01']
        assert result.evidence[1].retrieved_via=='linked'
        assert result.evidence_set.required_dependencies_complete
        assert index.calls==1
        await service.close()
    asyncio.run(run())


def test_missing_exception_prevents_conclusion_and_revocation_fails_closed():
    async def run():
        primary=chunk(required_links=['MISSING'])
        service,repo,index=await search_fixture([primary])
        result=await service.search(*request_context())
        assert result.evidence[0].applicability.status=='conditional'
        assert result.evidence[0].applicability.missing_required_section_ids==['MISSING']
        assert not result.evidence_set.required_dependencies_complete
        repo.revoked=True
        result=await service.search(*request_context())
        assert result.retrieval_status=='unavailable' and result.evidence==[]
        await service.close()
    asyncio.run(run())


def test_knowledge_limit_is_evidence_not_no_evidence():
    async def run():
        primary=chunk(evidence_type='knowledge_limit')
        service,_,_=await search_fixture([primary])
        assert (await service.search(*request_context())).retrieval_status=='ok'
        await service.close()
        service,_,_=await search_fixture([primary],hits=[])
        assert (await service.search(*request_context())).retrieval_status=='no_evidence'
        await service.close()
    asyncio.run(run())


def test_bad_hash_or_invalid_pin_never_yields_partial_evidence():
    async def run():
        primary=chunk()
        service,repo,index=await search_fixture([primary],hits=[primary.model_copy(update={'source_hash':'stale'})])
        result=await service.search(*request_context())
        assert result.retrieval_status=='unavailable' and not result.evidence
        request,context=request_context()
        result=await service.search(request,context.model_copy(update={'release_id':'forged'}))
        assert result.retrieval_status=='unavailable'
        await service.close()
    asyncio.run(run())


def test_hard_limit_reports_all_missing_exceptions_and_preserves_conflict():
    async def run():
        links=[f'CL-{i:02}' for i in range(1,12)]
        primary=chunk(required_links=links,conflict=True)
        rows=[primary]+[chunk(chunk_id=key,section_id=key) for key in links]
        service,_,_=await search_fixture(rows,hits=[primary])
        result=await service.search(*request_context(1))
        assert len(result.evidence)==10
        assert result.evidence[0].applicability.status=='conflict'
        assert result.evidence_set.missing_required_section_ids==links[9:]
        await service.close()
    asyncio.run(run())


def test_quota_logs_reason_but_returns_generic_unavailable(caplog):
    import logging
    from app.mcp_servers.mcp_knowledge.services.cloudflare import PolicyProviderError
    async def run():
        service,repo,index=await search_fixture([chunk()],relevance_verified=False)
        async def exhausted(*args,**kwargs):
            raise PolicyProviderError('quota_exhausted',status=429,provider_code='1234')
        service.encoder.backend.encode=exhausted
        try:
            result=await service.search(*request_context())
            assert result.retrieval_status=='unavailable' and result.evidence==[]
            assert result.error=='knowledge_unavailable'
            assert index.calls==0
            assert 'quota_exhausted' not in result.model_dump_json()
        finally:await service.close()
    with caplog.at_level(logging.WARNING): asyncio.run(run())
    assert 'reason=quota_exhausted' in caplog.text and 'request_id=req' in caplog.text
    assert 'release_id=r1' in caplog.text and 'provider_code=1234' in caplog.text


def test_each_search_uses_its_pinned_release_vocabulary():
    from app.mcp_servers.mcp_knowledge.services.bm25 import build_bm25_artifact,document_text
    async def run():
        first=chunk(content='đổi trả')
        service,repo,index=await search_fixture([first])
        seen=[]
        query=index.query
        async def capture(vector,**kwargs):
            seen.append((kwargs['release']['id'],vector.sparse_indices))
            return await query(vector,**kwargs)
        index.query=capture
        try:
            await service.search(*request_context())
            second=chunk(content='bảo hành')
            repo.rows=[second];index.rows=[second]
            manifest=repo.release['manifest']|{'bm25':build_bm25_artifact([document_text(second)],service.config)}
            repo.release=repo.release|{'id':'r2','manifest':manifest,'manifest_hash':digest(manifest)}
            await service.search(*request_context())
            assert seen[0][0]=='r1' and seen[0][1]
            assert seen[1]==('r2',[])
        finally: await service.close()
    asyncio.run(run())
