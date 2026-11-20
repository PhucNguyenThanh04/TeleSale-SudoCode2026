



def evidence():
    from uuid import uuid4
    t=str(uuid4());s='session'
    turns=[{'turn_id':t,'customer_id':'C','session_id':s,'on':'2026-11-05',
        'customer_text':'Tôi chọn Aster để xem giá.','agent_text':'Em kiểm tra giúp anh.'}]
    calls=[{'name':'catalog.search','source_turn_id':t,'args':{},'result':{'items':[
        {'sku':'SKU-ASTER','name':'Aster','variants':[]}]}}]
    proposal={'selected_sku':'SKU-ASTER','source_refs':{'selected_sku':{'customer_id':'C','session_id':s,
        'source_turn_id':t,'source_kind':'customer','evidence_quote':turns[0]['customer_text']}}}
    return t,turns,calls,proposal






def test_topic_optional_contract_and_mcp_admission_preserve_snapshot():
    from app.schemas.langmem import CustomerCallEpisodeCandidate
    from app.mcp_servers.mcp_memory.services.langmem_admission import admit_episode_candidate
    t,turns,calls,proposal=evidence()
    candidate=CustomerCallEpisodeCandidate(customer_id='C',session_id='session',channel='hotline',on='2026-11-05',
        source_turn_ids=[t],topics=[{'scope_type':'global','consultation':proposal}])
    delta=admit_episode_candidate('C','session',candidate,turns,calls)
    assert delta['topic_updates'][0]['consultation']['selected_sku']=='SKU-ASTER'


def test_worker_derives_and_persists_selection_without_llm_snapshot():
    import asyncio
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock
    from uuid import uuid4
    from app.mcp_servers.mcp_memory.distiller_worker import process_one
    sid,prior,current=str(uuid4()),str(uuid4()),str(uuid4())
    catalog={'name':'catalog.search','args':{},'result':{'items':[{'sku':'SKU-ASTER','name':'Aster','variants':[]}]}}
    repo=AsyncMock()
    @asynccontextmanager
    async def transaction():yield object()
    repo.transaction=transaction;repo.is_erasure_blocked.return_value=False
    repo.claim_distillation.return_value={'job_id':42,'customer_id':'C','session_id':sid,'source_turn_id':current,
        'turn_no':2,'attempts':1,'tool_observations':[]}
    repo.distillation_turn.return_value={'customer_text':'Tôi chọn Aster để xem giá.','agent_text':'Dạ, em ghi nhận.',
        'on_date':'2026-11-05','channel':'hotline'}
    repo.recent_session_turns.return_value=[{'client_msg_id':prior,'customer_text':'Tư vấn giúp tôi.',
        'agent_text':'Em đề xuất Aster.','on_date':'2026-11-05','channel':'hotline','tool_observations':[catalog]},
        {'client_msg_id':current,**repo.distillation_turn.return_value}]
    projection=AsyncMock();projection.list_fact_versions.return_value=[];projection.list_episode_versions.return_value=[]
    extractor=AsyncMock(return_value=([],None))
    assert asyncio.run(process_one(repo,extractor,projection)) is True
    import json
    messages = extractor.await_args.args[0]
    assert len(messages) == 1
    payload = json.loads(messages[0]['content'])
    assert payload['turn_id'] == current
    assert payload['customer_text'] == 'Tôi chọn Aster để xem giá.'
    assert payload['reference_context']['previous_agent_text'] == 'Em đề xuất Aster.'
    topic=projection.put_episode.await_args.args[2]['topics'][0]
    assert topic['consultation']['selected_sku']=='SKU-ASTER'
    assert topic['consultation']['source_refs']['selected_sku']['source_turn_id']==current


def test_projection_keeps_business_identifiers_in_consultation_json():
    from app.mcp_servers.mcp_memory.repos.langmem_projection import _safe
    sku='SKU-0912345678'
    payload={'topics':[{'scope_type':'global','consultation':{'selected_sku':sku,'candidates':[sku]}}]}
    assert _safe(payload)['topics'][0]['consultation']['selected_sku']==sku








def test_memory_read_committed_offer_before_worker_and_preserves_admitted_on_truncation():
    import asyncio,json
    from contextlib import asynccontextmanager
    from app.mcp_servers.mcp_memory.services.memory import read
    from test_presented_offers import evidence
    sid,turns,calls=evidence()
    class Repo:
        @asynccontextmanager
        async def transaction(self):yield None
        async def owner(self,*a):return 'C'
        async def recent_turns(self,*a):return []
        async def turn_count(self,*a):return 1
        async def lock_key(self,*a):pass
        async def order_links(self,*a):return []
        async def recent_session_turns(self,conn,session,customer,*a,**kw):
            assert session==sid and customer=='C'
            return [{'client_msg_id':turns[0]['turn_id'],'customer_text':turns[0]['customer_text'],
                'agent_text':turns[0]['agent_text'],'on_date':turns[0]['on'],'tool_observations':calls}]
    class Projection:
        async def list_fact_versions(self,*a):return []
        async def list_episode_versions(self,*a):return []
    result=asyncio.run(read(Repo(),'C',sid,projector=Projection()))
    snapshot=json.loads(json.dumps(result['current_episode']))['topics'][0]['consultation']
    assert snapshot['presented_offer']['price_vnd']==900000
    assert snapshot['accepted_offer'] is None
    async def no_window(*args,**kwargs):return []
    async def stored_episodes(*args):return [result['current_episode']]
    repo=Repo();repo.recent_session_turns=no_window
    projection=Projection();projection.list_episode_versions=stored_episodes
    repeated=asyncio.run(read(repo,'C',sid,projector=projection))
    assert repeated['current_episode']['topics'][0]['consultation']==snapshot




def test_worker_offer_projection_retry_is_idempotent_and_does_not_invent_consent():
    import asyncio
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock
    from app.mcp_servers.mcp_memory.distiller_worker import process_one
    from test_presented_offers import evidence
    sid,turns,calls=evidence();turn=turns[0];tid=turn['turn_id']
    repo=AsyncMock()
    @asynccontextmanager
    async def transaction():yield None
    repo.transaction=transaction;repo.is_erasure_blocked.return_value=False
    repo.claim_distillation.return_value={'job_id':42,'customer_id':'C','session_id':sid,
        'source_turn_id':tid,'turn_no':1,'attempts':1,'tool_observations':calls}
    repo.distillation_turn.return_value={'customer_text':turn['customer_text'],'agent_text':turn['agent_text'],
        'on_date':turn['on'],'channel':'hotline'}
    repo.recent_session_turns.return_value=[{'client_msg_id':tid,**repo.distillation_turn.return_value,
                                           'tool_observations':calls}]
    projection=AsyncMock();projection.list_fact_versions.return_value=[];projection.list_episode_versions.return_value=[]
    extractor=AsyncMock(return_value=([],None))
    assert asyncio.run(process_one(repo,extractor,projection))
    first=projection.put_episode.await_args.args[2]['topics'][0]['consultation']
    assert first['presented_offer']['price_vnd']==900000
    assert first['accepted_offer'] is None
    assert asyncio.run(process_one(repo,extractor,projection))
    assert projection.put_episode.await_args.args[2]['topics'][0]['consultation']==first
