"""Durable selection needs owner-bound committed customer evidence."""
from app.schemas.consultation import ConsultationSnapshot


def test_legacy_snapshot_has_no_customer_permission():
    snap=ConsultationSnapshot()
    assert snap.selected_sku is None and snap.delegation.status=='unknown'
    assert ConsultationSnapshot.model_validate({'schema_version':1}).model_dump()['schema_version']==2


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


def test_admitted_selection_roundtrips_and_clear_does_not_resurrect():
    from app.mcp_servers.mcp_shared.consultation import admit_consultation
    from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta
    t,turns,calls,proposal=evidence()
    admitted=admit_consultation(proposal,customer_id='C',session_id='session',committed_turns=turns,tool_calls=calls)
    assert admitted and admitted['selected_sku']=='SKU-ASTER'
    delta={'topic_updates':[{'scope_type':'global','scope_id':'','consultation':admitted}]}
    stored=apply_episode_delta({},delta,source_turn_id=t,customer_text=turns[0]['customer_text'],agent_text=turns[0]['agent_text'])
    assert stored['topics'][0]['consultation']['selected_sku']=='SKU-ASTER'
    from uuid import uuid4
    t2=str(uuid4());turn={'turn_id':t2,'customer_id':'C','session_id':'session','on':'2026-11-05','customer_text':'Không lấy Aster nữa.','agent_text':'Dạ vâng.'}
    revoked={'selected_sku':None,'source_refs':{'selected_sku':{'customer_id':'C','session_id':'session','source_turn_id':t2,'source_kind':'customer','evidence_quote':turn['customer_text']}}}
    patch=admit_consultation(revoked,customer_id='C',session_id='session',committed_turns=[*turns,turn],tool_calls=calls)
    updated=apply_episode_delta(stored,{'topic_updates':[{'scope_type':'global','consultation':patch}]},source_turn_id=t2,customer_text=turn['customer_text'],agent_text=turn['agent_text'])
    assert updated['topics'][0]['consultation']['selected_sku'] is None
    assert stored['topics'][0]['consultation']['selected_sku']=='SKU-ASTER'


def test_agent_cannot_supply_customer_consent_or_wrong_owner():
    from app.mcp_servers.mcp_shared.consultation import admit_consultation
    t,turns,calls,proposal=evidence()
    proposal['source_refs']['selected_sku']['source_kind']='agent'
    assert admit_consultation(proposal,customer_id='C',session_id='session',committed_turns=turns,tool_calls=calls) is None
    assert admit_consultation(proposal,customer_id='OTHER',session_id='session',committed_turns=turns,tool_calls=calls) is None


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
    topic=projection.put_episode.await_args.args[2]['topics'][0]
    assert topic['consultation']['selected_sku']=='SKU-ASTER'
    assert topic['consultation']['source_refs']['selected_sku']['source_turn_id']==current


def test_projection_keeps_business_identifiers_in_consultation_json():
    from app.mcp_servers.mcp_memory.repos.langmem_projection import _safe
    sku='SKU-0912345678'
    payload={'topics':[{'scope_type':'global','consultation':{'selected_sku':sku,'candidates':[sku]}}]}
    assert _safe(payload)['topics'][0]['consultation']['selected_sku']==sku


def test_provisional_handoff_proposal_cannot_grant_customer_permission():
    from app.agent.memory.episode_candidates import accepted_episode_delta
    _,_,_,proposal=evidence()
    result=accepted_episode_delta('Chào em','Em tìm thấy Aster.',
        {'topic_updates':[{'scope_type':'global','scope_id':'','consultation':proposal}]},{},[])
    assert result=={}


def test_masked_pii_evidence_is_stable_and_roundtrips_without_raw_data():
    import pytest
    from app.schemas.consultation import SourceRef, mask_evidence, mask_consultation
    from app.mcp_servers.mcp_shared.consultation import committed_consultation
    from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta
    t, turns, calls, _ = evidence()
    raw = 'Tôi chọn Aster để xem giá. Địa chỉ: 12 đường Hoa. 0912345678'
    safe = mask_evidence(raw)
    assert '12 đường Hoa' not in safe and '0912345678' not in safe
    assert mask_evidence(safe) == safe
    turns[0]['customer_text'] = safe
    snapshot = committed_consultation('C', 'session', turns, calls)
    patch = {'selected_sku': snapshot.selected_sku,
             'source_refs': {'selected_sku': snapshot.source_refs['selected_sku'].model_dump()}}
    assert mask_consultation(patch) == patch
    stored = apply_episode_delta({}, {'topic_updates': [
        {'scope_type': 'global', 'consultation': patch}]}, source_turn_id=t,
        customer_text=safe, agent_text=turns[0]['agent_text'])
    assert stored['topics'][0]['consultation']['selected_sku'] == 'SKU-ASTER'
    with pytest.raises(ValueError, match='contains PII'):
        SourceRef(customer_id='C', session_id='session', source_turn_id=t,
                  source_kind='customer', evidence_quote=raw)


def test_offer_schema_upgrade_is_compatible_and_does_not_grant_permission():
    from app.schemas.consultation import ConsultationSnapshot
    legacy=ConsultationSnapshot.model_validate({'schema_version':1,'selected_sku':'SKU-ASTER'})
    assert legacy.schema_version==2
    assert legacy.presented_offer is None and legacy.accepted_offer is None
    assert ConsultationSnapshot.model_validate_json(legacy.model_dump_json())==legacy


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


def test_committed_acceptance_can_link_admitted_prior_offer_and_reject_wrong_owner():
    from copy import deepcopy
    from uuid import uuid4
    from app.mcp_servers.mcp_shared.consultation import committed_consultation
    from test_presented_offers import evidence
    sid,turns,calls=evidence()
    first=committed_consultation('C',sid,turns,calls)
    ep={'customer_id':'C','session_id':sid,'on_date':'2026-11-05',
        'topics':[{'scope_type':'global','consultation':first.model_dump(mode='json')}]}
    new_sid,tid=str(uuid4()),str(uuid4())
    new_turn={**turns[0],'session_id':new_sid,'turn_id':tid,'customer_text':'Lấy mẫu đó, lên đơn.',
              'agent_text':'Em đang xử lý yêu cầu.'}
    new_calls=[{**c,'session_id':new_sid,'source_turn_id':tid} for c in calls]
    accepted=committed_consultation('C',new_sid,[new_turn],new_calls,prior_episodes=[ep])
    assert accepted.accepted_offer.price_vnd==900000
    assert accepted.source_refs['accepted_offer'].session_id==new_sid
    assert accepted.accepted_offer.presented_source.session_id==sid
    wrong=deepcopy(ep);wrong['customer_id']='OTHER'
    assert committed_consultation('C',new_sid,[new_turn],new_calls,prior_episodes=[wrong]).accepted_offer is None


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


def test_order_only_acceptance_matches_committed_admission_and_json_readback():
    import json
    from uuid import uuid4
    from app.mcp_servers.mcp_shared.consultation import committed_consultation,admit_consultation
    from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta
    from test_presented_offers import evidence
    sid,turns,calls=evidence();turns[0]['customer_text']='Cho tôi xem giá Aster.'
    first=committed_consultation('C',sid,turns,calls)
    assert first.selected_sku is None and first.accepted_offer is None
    tid=str(uuid4())
    turns.append({**turns[0],'turn_id':tid,'customer_text':'Ok em lên đơn cho anh, thanh toán COD nhé.',
                  'agent_text':'Dạ, em xử lý yêu cầu.'})
    snap=committed_consultation('C',sid,turns,calls)
    assert snap.accepted_offer.price_vnd==900000
    assert snap.source_refs['selected_sku'].source_turn_id==tid
    assert snap.source_refs['accepted_offer'].source_turn_id==tid
    payload=snap.model_dump(mode='json')
    fresh={k:v for k,v in snap.source_refs.items() if v.source_turn_id==tid}
    patch={k:payload[k] for k in fresh}
    patch['source_refs']={k:v.model_dump(mode='json') for k,v in fresh.items()}
    admitted=admit_consultation(patch,customer_id='C',session_id=sid,committed_turns=turns,tool_calls=calls)
    assert admitted is not None
    stored=apply_episode_delta({}, {'topic_updates':[{'scope_type':'global','consultation':admitted}]},
        source_turn_id=tid,customer_text=turns[-1]['customer_text'],agent_text=turns[-1]['agent_text'])
    readback=json.loads(json.dumps(stored))['topics'][0]['consultation']
    assert readback['accepted_offer']==payload['accepted_offer']
    assert 'purchase_intent' not in readback
