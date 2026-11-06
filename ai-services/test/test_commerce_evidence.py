"""Commercial evidence across turns; no BTC expected-answer inputs."""
from copy import deepcopy
from datetime import date
from uuid import uuid4
from app.schemas.agent import TextTurnRequest


def state(text='Lấy Aster, lên đơn giúp tôi.'):
    request=TextTurnRequest(client_msg_id=uuid4(),session_id=uuid4(),on=date(2026,11,5),
        text=text,channel='hotline',channel_identity='0900000000',input_mode='clean')
    return {'request':request,'safe_text':text,'identity_status':'known','customer_id':'C-OFFLINE',
        'customer_phone':'0900000000','session_tool_calls':[], 'tool_calls':[], 'tool_count':0,
        'profile':{},'scoped_facts':{},'history':[]}


def catalog(sku='SKU-ASTER',name='Aster',variants=None):
    return {'name':'catalog.search','args':{'sku':sku},'result':{'items':[
        {'sku':sku,'name':name,'variants':variants or [],'list_price_vnd':900000,'attributes':{}}]}}


def quote(sku='SKU-ASTER',price=900000,**args):
    return {'name':'pricing.get_quote','args':{'sku':sku,'qty':1,'on':'2026-11-05',**args},
        'result':{'sku':sku,'list_price_vnd':price,'final_price_vnd':price,'applied_promos':[],'freeship':False}}


def stock(sku='SKU-ASTER'):
    return {'name':'inventory.check','args':{'sku':sku,'on':'2026-11-05'},
        'result':{'sku':sku,'in_stock':True,'qty':10}}


def test_prior_turn_quote_reused_by_real_verifier():
    import asyncio
    from app.agent.harness.agent_nodes import AgentNodes
    s=state('Giá vẫn vậy đúng không?');s['session_tool_calls']=[catalog(),quote()]
    s['agent_draft']='Aster giá 900.000đ.'
    result=asyncio.run(AgentNodes(None,None,None,6,6).verify_agent(s))
    assert result['agent_text']==s['agent_draft']


def test_evidence_view_filters_stale_and_failed_refresh_without_mutation():
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    s=state();s['session_tool_calls']=[catalog(),quote(),stock()]
    s['tool_calls']=[{'name':'pricing.get_quote','args':quote()['args'],'result':{'error':'unavailable'}},
                     {'name':'policy.search','args':{},'result':{'evidence':[]}}]
    before=deepcopy(s['session_tool_calls']+s['tool_calls'])
    view=build_commerce_evidence(s,args={'sku':'SKU-ASTER','qty':1})
    assert not any(c['name']=='pricing.get_quote' and 'error' not in c['result'] for c in view)
    assert any(c['name']=='policy.search' for c in view)
    assert s['session_tool_calls']+s['tool_calls']==before


def test_changed_quote_inputs_and_wrong_owner_session_rejected():
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    for patch in [{'qty':2},{'address':'Region B'},{'basket_skus':['SKU-OTHER']},{'on':'2026-11-06'}]:
        s=state();s['session_tool_calls']=[quote(address='Region A',basket_skus=['SKU-ASTER'])]
        view=build_commerce_evidence(s,args={'sku':'SKU-ASTER','qty':1,'address':'Region A','basket_skus':['SKU-ASTER'],**patch})
        assert not any(c['name']=='pricing.get_quote' for c in view)
    for field,value in [('customer_id','C-OTHER'),('session_id','other-session')]:
        s=state();q=quote();q[field]=value;s['session_tool_calls']=[q]
        assert not build_commerce_evidence(s,args={'sku':'SKU-ASTER'})


def test_unknown_order_conflict_is_not_resolved_by_success_filter():
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    s=state();a=quote();b=quote(price=950000)
    a['observation_order']=b['observation_order']=1
    s['session_tool_calls']=[a,b]
    assert not any(c['name']=='pricing.get_quote' for c in build_commerce_evidence(s))


def test_latest_catalog_failure_removes_previous_metadata():
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    s=state();s['session_tool_calls']=[catalog()]
    s['tool_calls']=[{'name':'catalog.search','args':catalog()['args'],'result':{'error':'unavailable'}}]
    assert not any(c['name']=='catalog.search' for c in build_commerce_evidence(s))


def test_quote_is_bound_to_sku_not_just_amount():
    import asyncio
    from app.agent.harness.agent_nodes import AgentNodes
    s=state('Giá bao nhiêu?');s['session_tool_calls']=[catalog(),catalog('SKU-BRIO','Brio'),quote(),quote('SKU-BRIO',800000)]
    s['agent_draft']='Aster giá 800.000đ.'
    result=asyncio.run(AgentNodes(None,None,None,6,6).verify_agent(s))
    assert result['agent_text']!=s['agent_draft']


def test_memory_history_retains_server_owned_source_turn_id():
    import asyncio
    from contextlib import asynccontextmanager
    from app.mcp_servers.mcp_memory.services.memory import read
    turn_id=str(uuid4())
    class Repo:
        @asynccontextmanager
        async def transaction(self):yield None
        async def owner(self,*a):return None
        async def recent_turns(self,*a):return [{'customer_text':'Hỏi Aster.','agent_text':'Aster giá 900.000đ.','client_msg_id':turn_id}]
        async def turn_count(self,*a):return 1
    result=asyncio.run(read(Repo(),None,str(uuid4())))
    assert result['history'][0]['source_turn_id']==turn_id


def test_current_customer_address_invalidates_old_quote_for_verifier_too():
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    s=state('Địa chỉ: Region B')
    s['session_tool_calls']=[quote(address='Region A')]
    assert not any(c['name']=='pricing.get_quote' for c in build_commerce_evidence(s))


def test_duplicate_observation_does_not_resolve_equal_order_conflict():
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    s=state();a=quote();b=quote(price=950000)
    a['observation_order']=b['observation_order']=1
    s['session_tool_calls']=[a,b,deepcopy(b)]
    assert not any(c['name']=='pricing.get_quote' for c in build_commerce_evidence(s))


def test_parent_variant_claim_binding_and_unrelated_quotes():
    from app.agent.guardrails.checks import check_answer
    calls=[catalog(name='Giày Aster',variants=[{'variant_sku':'SKU-ASTER-40-DEN','size':40,'color':'den'},
        {'variant_sku':'SKU-ASTER-41-DEN','size':41,'color':'den'}]),quote('SKU-ASTER-40-DEN'),
        catalog('SKU-BRIO','Brio'),quote('SKU-BRIO',800000)]
    assert check_answer('Giày Aster size 40 màu đen giá 900.000đ.',calls)[1] is None
    assert check_answer('Giày Aster giá 900.000đ.',calls)[1] is not None
    assert check_answer('Giày Aster size 41 màu đen giá 900.000đ.',calls)[1] is not None
    assert check_answer('Giày Aster giá 900.000đ.',calls,focus_sku='SKU-ASTER-40-DEN')[1] is None
    assert check_answer('Brio giá 900.000đ.',calls)[1] is not None
    assert check_answer('Giày Aster size 40 màu đen giá 900.000đ; Brio giá 800.000đ.',list(reversed(calls)))[1] is None


def bind_history_observations(s):
    """Bind existing prior tool results to the committed test turn; never add consent."""
    tid=str(uuid4())
    s['history'][0]['source_turn_id']=tid
    for call in s['session_tool_calls']:
        call['source_turn_id']=tid
        call['customer_id']=s['customer_id']
        call['session_id']=str(s['request'].session_id)


def test_prompt_context_exposes_reused_session_evidence_without_new_tool_call():
    from app.agent.harness.context import prompt_context
    s=state('Giá bao nhiêu?');s['session_tool_calls']=[catalog(),quote()]
    context=prompt_context(s,6)
    q=next(c for c in context['tool_observations'] if c['name']=='pricing.get_quote')
    assert q['result']['final_price_vnd']==900000
    assert q['evidence_scope']=='current_session'
    assert s['tool_calls']==[]


def test_context_refresh_prefers_sourced_selection_over_advised_list():
    import asyncio
    from datetime import datetime,timezone
    from types import SimpleNamespace
    from app.agent.harness.context import load_context
    s=state('Giá mẫu đó bao nhiêu?')
    ref={'customer_id':s['customer_id'],'session_id':'old','source_turn_id':'old-turn',
         'source_kind':'customer','evidence_quote':'Tôi chọn Aster.'}
    ep={'customer_id':s['customer_id'],'session_id':'old','on':'2026-11-04',
        'channel':'hotline','summary':'Đã hỏi giá.','outcome':'khac',
        'topics':[{'scope_type':'global','consultation':{'selected_sku':'SKU-ASTER','source_refs':{'selected_sku':ref}}}]}
    async def read(*a):return {'history':[{'customer':'Chào em.','agent':'Dạ.'}],
        'turn_count':1,'profile':{},'episodes':[ep],
        'scoped_facts':{'product':{sku:{} for sku in ['SKU-BRIO','SKU-CEDAR','SKU-ASTER']},'room':{}}}
    calls=[]
    async def invoke(name,args,*a):
        calls.append((name,args))
        return quote(args['sku'])['result'] if name=='pricing.get_quote' else stock(args['sku'])['result']
    result=asyncio.run(load_context(s,SimpleNamespace(read_context=read,include_prior=True,max_episodes=5),
        SimpleNamespace(invoke_trusted=invoke),lambda:datetime.now(timezone.utc)))
    assert {args['sku'] for _,args in calls}=={'SKU-ASTER'}
    assert len(result['tool_calls'])==2


def test_promotion_expiry_requires_exact_code_and_exact_status():
    from app.agent.guardrails.checks import check_answer
    q=quote();q['result'].update(expired_promos=['OLD-OTHER'],
        ineligible_promos=[{'promo_code':'LIMIT-SALE','reason':'min_qty'}],
        applied_promos=[{'promo_code':'CURRENT-SALE','type':'fixed','discount_vnd':10000}])
    calls=[catalog(),q]
    assert check_answer('Ưu đãi cũ hết hạn.',calls)[1] is not None
    assert check_answer('Mã LIMIT-SALE đã hết hạn.',calls)[1] is not None
    assert check_answer('Mã OLD-OTHER đã hết hạn.',calls)[1] is None
    assert check_answer('Mã LIMIT-SALE không đủ điều kiện.',calls)[1] is None


def test_stock_claims_bind_each_product_without_cross_product_leakage():
    from app.agent.guardrails.checks import check_answer
    calls=[catalog(),catalog('SKU-BRIO','Brio'),stock()]
    assert check_answer('Brio còn hàng.',calls)[1] is not None
    calls.append(stock('SKU-BRIO'))
    assert check_answer('Aster còn hàng; Brio còn hàng.',calls)[1] is None


def test_retained_quote_region_needs_literal_customer_source_and_matching_owner():
    from app.mcp_servers.mcp_shared.commerce_evidence import current_customer_address
    s=state('Lên đơn nhé.')
    s['history']=[{'customer':'Anh ở Q7 HCM.','agent':'Dạ.'}]
    s['session_tool_calls']=[quote(address='Q7 HCM')]
    bind_history_observations(s)
    assert current_customer_address(s)=='Q7 HCM'
    s['history'][0]['customer']='Tôi chỉ hỏi giá.'
    assert current_customer_address(s) is None
    s['history'][0]['customer']='Anh ở Q7 HCM.'
    s['session_tool_calls'][0]['customer_id']='OTHER'
    assert current_customer_address(s) is None
    s['session_tool_calls'][0]['customer_id']=s['customer_id']
    s['history'].append({'customer':'Tôi không còn ở Q7 HCM.','agent':'Dạ.'})
    assert current_customer_address(s) is None


def test_context_masking_preserves_valid_turn_uuid_that_contains_phone_like_digits():
    from app.agent.harness.context import _mask_context
    tid='12345678-1234-4123-8123-091234567890'
    masked=_mask_context({'history':[{'source_turn_id':tid,'customer':'SĐT 0912345678'}],
                          'profile':{'source_turn_id':tid}})
    assert masked['history'][0]['source_turn_id']==tid
    assert '0912345678' not in masked['history'][0]['customer']
    assert masked['profile']['source_turn_id']!=tid  # The exemption is by trusted field path.


def test_new_unresolved_customer_region_does_not_revive_prior_quote_region():
    from app.mcp_servers.mcp_shared.commerce_evidence import current_customer_address
    s=state('Anh ở Q1 HCM, lên đơn nhé.')
    s['history']=[{'customer':'Anh ở Q7 HCM.','agent':'Dạ.'}]
    s['session_tool_calls']=[quote(address='Q7 HCM')]
    bind_history_observations(s)
    assert current_customer_address(s) is None
