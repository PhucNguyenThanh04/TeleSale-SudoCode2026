"""Real AgentNodes/BusinessTools/admission/JSON/runner; model deliberately never orders."""
from eval_harness.test_support import VoiceLifecycleStub
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from app.agent.harness.agent_nodes import AgentNodes
from app.mcp_servers.mcp_shared.consultation import committed_consultation
from app.mcp_servers.mcp_memory.services.langmem_admission import admit_episode_candidate
from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta
from app.schemas.langmem import CustomerCallEpisodeCandidate
from eval_harness.benchmark_runner import run_configuration
from eval_harness.turn_diagnostics import verify_turn_diagnostics


class Runtime(VoiceLifecycleStub):
    def __init__(self,sku,name,price,new_price=None,*,service_memory=False,delayed_worker=False,known_session=True,promos=None,new_promos=None):
        self.sku,self.name,self.price,self.new_price=sku,name,price,new_price
        self.memory=SimpleNamespace(include_prior=True,namespace='')
        self.sessions={};self.episodes={};self.states={};self.writes=[];self.model_calls=0
        self.service_memory=service_memory;self.delayed_worker=delayed_worker;self.known_session=known_session
        self.repo=CommittedRepo(self)
        self.promos=promos or [];self.new_promos=new_promos

    async def run(self,request):
        sid,tid=str(request.session_id),str(request.client_msg_id)
        session=self.sessions.setdefault(sid,{'turns':[],'calls':[]})
        state={'request':request,'safe_text':request.text,'identity_status':'known',
            'customer_id':'C-INTEGRATION','customer_phone':'0900000000','tool_calls':[],
            'session_tool_calls':deepcopy(session['calls']),'tool_count':0,'profile':{},'scoped_facts':{},
            'history':[{'customer':t['customer_text'],'agent':t['agent_text'],'source_turn_id':t['turn_id']}
                       for t in session['turns']],
            'episodes':[deepcopy(ep) for key,ep in self.episodes.items() if key!=sid],
            'current_episode':deepcopy(self.episodes.get(sid))}
        if self.service_memory:
            from app.mcp_servers.mcp_memory.services.memory import read
            context=await read(self.repo,'C-INTEGRATION',sid,projector=self.repo)
            assert 'error' not in context,context
            state.update({key:context[key] for key in ('history','profile','scoped_facts','episodes','current_episode')})
        price=self.new_price if len(self.sessions)>1 and self.new_price else self.price
        async def invoke(name,args,*a,**kw):
            if name=='catalog.search':
                return {'items':[{'sku':self.sku,'name':self.name,'variants':[],
                                  'list_price_vnd':self.price,'attributes':{}}]}
            if name=='pricing.get_quote':
                return {'sku':self.sku,'list_price_vnd':price,'final_price_vnd':price,
                        'applied_promos':(self.new_promos if len(self.sessions)>1 and self.new_promos is not None else self.promos),'freeship':False}
            if name=='inventory.check':return {'sku':self.sku,'in_stock':True,'qty':10}
            if name=='order.create':
                self.writes.append(deepcopy(args));return {'status':'created','order_id':'OD-INTEGRATION'}
            raise AssertionError(name)
        runtime=self
        def build(kind,llm,business,prompt):
            class Agent:
                async def ainvoke(self,*a,**kw):
                    runtime.model_calls+=1
                    if not session['turns'] and not runtime.episodes:
                        await business.invoke('catalog.search',{'query':runtime.name})
                        await business.invoke('pricing.get_quote',{'sku':runtime.sku})
                    return {'messages':[AIMessage(content=f'{runtime.name} giá {price:,}đ.'.replace(',','.'))]}
            return Agent()
        nodes=AgentNodes(None,SimpleNamespace(invoke_trusted=invoke),None,6,6)
        with patch('app.agent.harness.agent_nodes.build_agent',side_effect=build),patch('app.agent.harness.agent_nodes.text_prompt',return_value='offline'):
            state.update(await nodes.run_agent(state))
            state.update(await nodes.verify_agent(state))
        turn={'turn_id':tid,'customer_id':'C-INTEGRATION','session_id':sid,'on':request.on.isoformat(),
              'customer_text':request.text,'agent_text':state['agent_text']}
        if self.service_memory:
            from app.mcp_servers.mcp_memory.services.memory import write
            result=await write(self.repo,'commit_turn','C-INTEGRATION',sid,{
                'client_msg_id':tid,'on':request.on.isoformat(),'channel':'hotline',
                'customer_text':request.text,'agent_text':state['agent_text'],'tool_observations':state['tool_calls']})
            assert 'error' not in result,result
        else:
            session['turns'].append(turn)
        session['calls'].extend({**deepcopy(c),'source_turn_id':tid,'customer_id':'C-INTEGRATION','session_id':sid}
                                for c in state['tool_calls'])
        snapshot=committed_consultation('C-INTEGRATION',sid,session['turns'],session['calls'])
        fresh={k:r for k,r in snapshot.source_refs.items() if r.source_turn_id==tid}
        payload=snapshot.model_dump(mode='json')
        patch_data={k:payload[k] for k in fresh}
        patch_data['source_refs']={k:r.model_dump(mode='json') for k,r in fresh.items()}
        old=self.episodes.get(sid,{'customer_id':'C-INTEGRATION','session_id':sid,
                                 'on_date':request.on.isoformat(),'topics':[]})
        if fresh and not self.delayed_worker:
            candidate=CustomerCallEpisodeCandidate(customer_id='C-INTEGRATION',session_id=sid,
                channel='hotline',on=request.on,source_turn_ids=[t['turn_id'] for t in session['turns']],
                topics=[{'scope_type':'global','consultation':patch_data}])
            delta=admit_episode_candidate('C-INTEGRATION',sid,candidate,session['turns'],session['calls'])
            assert delta
            old={**old,**apply_episode_delta(old,delta,source_turn_id=tid,
                customer_text=request.text,agent_text=state['agent_text'])}
        if not self.delayed_worker or self.known_session:
            self.episodes[sid]=json.loads(json.dumps({**old,'schema_version':1}))
        self.states[tid]=state
        return SimpleNamespace(agent_text=state['agent_text'],call_brief=None)

    def state_for(self,request):return self.states[str(request.client_msg_id)]


class CommittedRepo:
    """Only persistence I/O is fake; commit/read/admission/reducer are production code."""
    def __init__(self,runtime):self.runtime=runtime;self.observed={}
    @asynccontextmanager
    async def transaction(self):yield None
    async def owner(self,conn,sid):return 'C-INTEGRATION'
    async def lock_key(self,*args):pass
    async def next_turn(self,conn,sid):return len(self.runtime.sessions[sid]['turns'])+1
    async def turn_count(self,conn,sid):return len(self.runtime.sessions[sid]['turns'])
    async def insert_turn(self,conn,sid,number,cid,channel,on,customer,agent,tid):
        self.runtime.sessions[sid]['turns'].append({'turn_id':tid,'customer_id':cid,
            'session_id':sid,'on':str(on),'customer_text':customer,'agent_text':agent})
    async def enqueue_distillation(self,conn,sid,cid,tid,observations,*args,**kwargs):
        from app.mcp_servers.mcp_shared.memory_observations import memory_observations
        self.observed[tid]=json.loads(json.dumps(memory_observations(observations)))
    async def recent_turns(self,conn,sid,limit):
        return [{**t,'client_msg_id':t['turn_id']} for t in self.runtime.sessions[sid]['turns'][-limit:]]
    async def recent_session_turns(self,conn,sid,cid,through_turn_no,limit=12):
        assert cid=='C-INTEGRATION'
        return [{**t,'client_msg_id':t['turn_id'],'on_date':t['on'],
                 'tool_observations':self.observed.get(t['turn_id'],[])}
                for t in self.runtime.sessions[sid]['turns'][:through_turn_no][-limit if limit else 0:]]
    async def order_links(self,*args):return []
    async def list_fact_versions(self,*args):return []
    async def list_episode_versions(self,*args):return deepcopy(list(self.runtime.episodes.values()))


@pytest.mark.parametrize('sku,name,price',[('SKU-CEDAR','Cedar',640000),('SKU-LINDEN','Linden',720000)])
def test_real_nodes_readback_hydration_and_prior_turn_evidence_then_order_once(tmp_path,sku,name,price):
    runtime=Runtime(sku,name,price)
    scenarios={'UNRELATED-PATH':{'calls':{'call_1':{'call_date':'2026-11-05','customer_turns':[
        f'Tôi chọn {name} để xem giá.', 'Giá hiện tại là bao nhiêu?']},
        'call_2':{'call_date':'2026-11-05','customer_turns':[f'Lấy mẫu hôm trước giá {price}đ, lên đơn.']}}}}
    out=tmp_path/'trace.jsonl'
    result=asyncio.run(run_configuration(scenarios=scenarios,config='full',runtime=runtime,
        run_id='offline-only',out=out,wait_for_jobs=AsyncMock(),capture_writes=AsyncMock(return_value={})))
    rows=[json.loads(line) for line in out.read_text().splitlines()]
    assert rows[1]['tool_calls']==[]  # Verified from the previous turn, not copied into the trace.
    assert f'{price:,}'.replace(',','.') in rows[1]['agent_text']
    assert [c['name'] for c in rows[2]['tool_calls']]==['catalog.search','pricing.get_quote','inventory.check','order.create']
    assert len(runtime.writes)==1 and runtime.writes[0]['sku']==sku
    assert runtime.model_calls==3
    assert verify_turn_diagnostics(out,result['turn_diagnostics'])['rows']==3
    final=runtime.states[next(reversed(runtime.states))]
    assert final['episodes'][0]['topics'][0]['consultation']['selected_sku']==sku


def test_real_nodes_changed_price_requires_confirmation_then_advances(tmp_path):
    runtime=Runtime('SKU-CEDAR','Cedar',640000,new_price=690000)
    scenarios={'DIFFERENT-ID':{'calls':{'call_1':{'call_date':'2026-11-05',
        'customer_turns':['Tôi chọn Cedar để xem giá.']},'call_2':{'call_date':'2026-11-05',
        'customer_turns':['Mua Cedar giá 640000đ, lên đơn.', 'Đồng ý Cedar giá 690000đ, lên đơn.']}}}}
    out=tmp_path/'trace.jsonl'
    asyncio.run(run_configuration(scenarios=scenarios,config='full',runtime=runtime,
        run_id='offline-only',out=out,wait_for_jobs=AsyncMock(),capture_writes=AsyncMock(return_value={})))
    rows=[json.loads(line) for line in out.read_text().splitlines()]
    assert not any(c['name']=='order.create' for c in rows[1]['tool_calls'])
    assert 'đồng ý' in rows[1]['agent_text'].lower()
    assert len(runtime.writes)==1 and runtime.writes[0]['price_vnd']==690000


@pytest.mark.parametrize('delayed_worker',[False,True])
def test_presented_offer_survives_json_then_deictic_acceptance_without_repeating_price(tmp_path,delayed_worker):
    runtime=Runtime('SKU-CEDAR','Cedar',640000,service_memory=True,delayed_worker=delayed_worker)
    scenarios={'OFFER-CONTINUITY':{'calls':{
        'call_1':{'call_date':'2026-11-05','customer_turns':['Cho tôi xem giá Cedar.']},
        'call_2':{'call_date':'2026-11-05','customer_turns':['Lấy mẫu đó, lên đơn.']}}}}
    out=tmp_path/'offer.jsonl'
    asyncio.run(run_configuration(scenarios=scenarios,config='full',runtime=runtime,
        run_id='offline-offer',out=out,wait_for_jobs=AsyncMock(),capture_writes=AsyncMock(return_value={})))
    last_state=runtime.states[next(reversed(runtime.states))]
    first=last_state['episodes'][0]['topics'][0]['consultation']
    assert first['presented_offer']['price_vnd']==640000
    assert first['accepted_offer'] is None
    assert len(runtime.writes)==1
    assert runtime.writes[0]['sku']=='SKU-CEDAR'
    rows=[json.loads(line) for line in out.read_text().splitlines()]
    assert '640.000' in rows[0]['agent_text']
    assert [c['name'] for c in rows[1]['tool_calls']].count('order.create')==1


@pytest.mark.parametrize('mode',['higher_price','lost_gift','delivery','revoked','unknown_session'])
def test_offer_continuity_negative_conditions_never_write(tmp_path,mode):
    gift={'type':'gift','promo_code':'GIFT-CEDAR','gift_sku':'SKU-CEDAR-GIFT'}
    runtime=Runtime('SKU-CEDAR','Cedar',640000,service_memory=True,
        new_price=690000 if mode=='higher_price' else None,
        delayed_worker=mode=='unknown_session',known_session=mode!='unknown_session',
        promos=[gift] if mode=='lost_gift' else [],new_promos=[] if mode=='lost_gift' else None)
    accept={'delivery':'Lấy mẫu đó, giao trong tuần này nhé.',
            'revoked':'Không lấy mẫu đó nữa.'}.get(mode,'Lấy mẫu đó, lên đơn.')
    first=['Cho tôi xem giá Cedar.']
    if mode=='lost_gift':first.append('Có tặng quà không?')
    scenarios={'NEGATIVE-OFFER':{'calls':{
        'call_1':{'call_date':'2026-11-05','customer_turns':first},
        'call_2':{'call_date':'2026-11-05','customer_turns':[accept]}}}}
    out=tmp_path/f'{mode}.jsonl'
    asyncio.run(run_configuration(scenarios=scenarios,config='full',runtime=runtime,
        run_id='offline-negative',out=out,wait_for_jobs=AsyncMock(),capture_writes=AsyncMock(return_value={})))
    rows=[json.loads(line) for line in out.read_text().splitlines()]
    assert runtime.writes==[]
    assert not any(c['name']=='order.create' for row in rows for c in row['tool_calls'])
    assert 'đã tạo đơn' not in rows[-1]['agent_text']
    if mode=='lost_gift':
        assert 'tặng' in rows[1]['agent_text']
        prior=runtime.states[next(reversed(runtime.states))]['episodes'][0]['topics'][0]['consultation']
        assert prior['presented_offer']['price_vnd']==640000
        assert prior['presented_offer']['promo_terms'][0]['gift_sku']=='SKU-CEDAR-GIFT'


class ProductionRepo(CommittedRepo):
    """JSON persistence fake for the production graph and real distillation worker."""
    def __init__(self):
        super().__init__(SimpleNamespace(sessions={},episodes={}))
        self.jobs=[];self.operations={};self.facts=[];self.links=[];self.products=[]

    async def owner(self,conn,sid):
        turns=self.runtime.sessions.setdefault(sid,{'turns':[],'calls':[]})['turns']
        return turns[0]['customer_id'] if turns else None

    async def is_erasure_blocked(self,*args):return False

    async def claim_operation(self,conn,key,digest):
        previous=self.operations.get(key)
        if previous:
            assert previous[0]==digest
            return deepcopy(previous[1])
        self.operations[key]=(digest,None)
        return None

    async def finish_operation(self,conn,key,result):
        self.operations[key]=(self.operations[key][0],deepcopy(result))

    async def enqueue_distillation(self,conn,sid,cid,tid,observations,outcome='khac',**kwargs):
        await super().enqueue_distillation(conn,sid,cid,tid,observations)
        self.jobs.append({'job_id':len(self.jobs)+1,'customer_id':cid,'session_id':sid,
            'source_turn_id':tid,'turn_no':len(self.runtime.sessions[sid]['turns']),
            'attempts':0,'status':'pending','verified_outcome':outcome,
            'tool_observations':deepcopy(self.observed[tid])})

    async def insert_turn(self,conn,sid,number,cid,channel,on,customer,agent,tid):
        await super().insert_turn(conn,sid,number,cid,channel,on,customer,agent,tid)
        self.runtime.sessions[sid]['turns'][-1]['channel']=channel

    async def claim_distillation(self,*args):
        job=next((j for j in self.jobs if j['status']=='pending'),None)
        if job:job['status']='leased';job['attempts']+=1
        return deepcopy(job)

    async def distillation_turn(self,conn,job):
        return next({**t,'on_date':t['on']} for t in self.runtime.sessions[job['session_id']]['turns']
                    if t['turn_id']==job['source_turn_id'])

    async def save_distillation_proposals(self,conn,job_id,value):
        self.jobs[job_id-1]['accepted_proposals']=json.loads(json.dumps(value))

    async def finish_distillation(self,conn,job_id,status,error_code=None,accepted_writes=None):
        self.jobs[job_id-1].update(status=status,error_code=error_code)

    async def completed_job_revisions(self,conn,cid,revisions):
        return {j['job_id'] for j in self.jobs if j['customer_id']==cid and j['status']=='completed'
                and j['job_id'] in revisions}

    async def variant_details(self,conn,sku):
        return next(({**v,'parent_sku':p['sku']} for p in self.products for v in p['variants']
                     if v['variant_sku']==sku),None)

    async def link_order(self,conn,cid,order):self.links.append(order)
    async def order_links(self,*args):return list(self.links)
    async def list_fact_versions(self,*args):return deepcopy(self.facts)

    async def put_facts(self,cid,sid,tid,on,facts,*,revision,completed_revisions):
        from app.mcp_servers.mcp_memory.repos.langmem_projection import _safe
        for fact in facts:
            self.facts.append(_safe({**fact,'schema_version':1,'customer_id':cid,
                'session_id':sid,'source_turn_id':tid,'on':on,'revision':revision,
                'source':f'langmem:{sid}:{tid}'}))
        return deepcopy(facts)

    async def put_episode(self,cid,sid,canonical,*,revision):
        from app.mcp_servers.mcp_memory.repos.langmem_projection import _safe
        self.runtime.episodes[sid]=json.loads(json.dumps(_safe({**canonical,'schema_version':1,
            'customer_id':cid,'session_id':sid,'on':canonical['on_date'],'revision':revision})))


class ProductionGateway:
    """Only tool/persistence I/O is fake; no production decision is patched."""
    def __init__(self,products,price=730000):
        self.repo=ProductionRepo();self.repo.products=products
        self.products=products;self.price=price;self.promos=[];self.calls=[];self.writes=[]
        self.fail_stock=False;self.fail_quote=False;self.order_error=False
        self.customer='C-INTEGRATION'

    async def invoke(self,name,args):
        from app.mcp_servers.mcp_memory.services import memory
        self.calls.append((name,deepcopy(args)))
        if name=='crm.get_customer':
            return {'found':True,'customer_id':self.customer,'phone':'0900000000','orders':[], 'sessions':[]}
        if name=='memory.read':return await memory.read(self.repo,projector=self.repo,**args)
        if name=='memory.write':return await memory.write(self.repo,**args)
        if name=='catalog.search':
            items=[p for p in self.products if not args.get('sku') or p['sku']==args['sku']
                   or any(v['variant_sku']==args['sku'] for v in p['variants'])]
            return {'items':deepcopy(items),'total':len(items)}
        if name=='pricing.get_quote':
            if self.fail_quote:return {'error':'unavailable'}
            return {'sku':args['sku'],'list_price_vnd':self.price,'final_price_vnd':self.price,
                'applied_promos':deepcopy(self.promos),'expired_promos':[],
                'ineligible_promos':[],'not_applied_exclusive':[],'freeship':False}
        if name=='inventory.check':
            return {'error':'unavailable'} if self.fail_stock else {'sku':args['sku'],'in_stock':True,'qty':8}
        if name=='order.create':
            self.writes.append(deepcopy(args))
            return {'error':'unavailable'} if self.order_error else {'status':'created','order_id':'OD-PRODUCTION'}
        raise AssertionError(name)

    async def invoke_trusted(self,name,args,*identity):return await self.invoke(name,args)

    async def project(self):
        from app.mcp_servers.mcp_memory.distiller_worker import process_one
        async def extractor(*args):return [],None
        while any(j['status']=='pending' for j in self.repo.jobs):
            assert await process_one(self.repo,extractor,self.repo)
            assert all(j.get('error_code') is None for j in self.repo.jobs),self.repo.jobs


class ProductionModel(BaseChatModel):
    replies: list[AIMessage]

    @property
    def _llm_type(self):return 'offline-script'
    def bind_tools(self,tools,**kwargs):return self
    def _generate(self,messages,stop=None,run_manager=None,**kwargs):
        assert self.replies, 'script exhausted'
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])


def production_case(*,variants=False,price=730000,sku='SKU-WILLOW',name='Willow Classic'):
    from datetime import datetime,timezone
    from app.agent.harness.runtime import AgentHarnessRuntime
    from app.agent.memory.store import MCPMemoryStore
    products=[{'sku':sku,'name':name,'variants':[
        {'variant_sku':sku+'-39-DEN','size':39,'color':'den'},
        {'variant_sku':sku+'-41-DEN','size':41,'color':'den'}] if variants else [],
        'attributes':{},'list_price_vnd':price}]
    gateway=ProductionGateway(products,price)
    model=ProductionModel(replies=[])
    runtime=AgentHarnessRuntime(model,gateway,MCPMemoryStore(gateway),max_tool_calls=6,
        clock=lambda:datetime(2026,11,5,tzinfo=timezone.utc))
    return runtime,gateway,model


def production_request(text,*,sid=None,on='2026-11-05'):
    from uuid import uuid4
    from app.schemas.agent import TextTurnRequest
    return TextTurnRequest(client_msg_id=uuid4(),session_id=sid or uuid4(),on=on,
        text=text,channel='hotline',channel_identity='0900000000',input_mode='clean')


def scripted_tool(name,args):
    from uuid import uuid4
    from app.agent.implementations.tool_names import to_model_tool_name
    return AIMessage(content='',tool_calls=[{'name':to_model_tool_name(name),'args':args,'id':str(uuid4())}])


@pytest.mark.parametrize('project_worker',[False,True])
def test_production_runtime_order_only_after_variant_quote(project_worker):
    async def run():
        runtime,gateway,model=production_case(variants=True)
        first=production_request('Willow Classic còn size 39 màu đen không?')
        model.replies.extend([scripted_tool('catalog.search',{'query':'Willow Classic'}),
            scripted_tool('inventory.check',{'sku':'SKU-WILLOW','size':39,'color':'den'}),
            scripted_tool('pricing.get_quote',{'sku':'SKU-WILLOW','size':39,'color':'den'}),
            AIMessage(content='Willow Classic size 39 màu đen giá 730.000đ.')])
        await runtime.run(first)
        if project_worker:await gateway.project()
        accept=production_request('Ok em lên đơn cho anh, thanh toán COD nhé.',sid=first.session_id)
        model.replies.append(AIMessage(content='Dạ, em xử lý yêu cầu.'))
        response=await runtime.run(accept)
        state=runtime.state_for(accept)
        from app.mcp_servers.mcp_shared.consultation import derive_consultation,consultation_missing_fields
        assert len(gateway.writes)==1,(response.agent_text,consultation_missing_fields(state),derive_consultation(state))
        assert gateway.writes[0]['sku']=='SKU-WILLOW-39-DEN'
        assert 'OD-PRODUCTION' in response.agent_text
        await gateway.project()
        memory=await runtime.memory.read_context(str(accept.session_id),'C-INTEGRATION')
        snapshot=memory['current_episode']['topics'][0]['consultation']
        assert snapshot['accepted_offer']['price_vnd']==730000
        assert snapshot['source_refs']['accepted_offer']['source_turn_id']==str(accept.client_msg_id)
    asyncio.run(run())


def test_production_runtime_first_variant_selection_after_parent_offer():
    async def run():
        runtime,gateway,model=production_case(variants=True)
        inquiry=production_request('Tôi muốn hỏi Willow Classic.')
        model.replies.extend([scripted_tool('catalog.search',{'query':'Willow Classic'}),
            AIMessage(content='Em tư vấn Willow Classic, có nhiều size để mình chọn.')])
        await runtime.run(inquiry)
        await gateway.project()
        price=production_request('Willow Classic giá bao nhiêu?')
        model.replies.extend([scripted_tool('catalog.search',{'sku':'SKU-WILLOW'}),
            AIMessage(content='Willow Classic giá 730.000đ.')])
        response=await runtime.run(price)
        state=runtime.state_for(price)
        assert '730.000' in response.agent_text,(response.agent_text,state['tool_calls'])
        assert any(c['name']=='pricing.get_quote' and c['args']['sku']=='SKU-WILLOW'
                   for c in state['tool_calls'])
        accept=production_request('Ok lấy size 41 màu đen, lên đơn nhé.',sid=price.session_id)
        model.replies.append(AIMessage(content='Dạ, em kiểm tra đúng size.'))
        response=await runtime.run(accept)
        from app.mcp_servers.mcp_shared.consultation import consultation_missing_fields
        assert len(gateway.writes)==1,(response.agent_text,consultation_missing_fields(runtime.state_for(accept)))
        assert gateway.writes[0]['sku']=='SKU-WILLOW-41-DEN'
    asyncio.run(run())


@pytest.mark.parametrize('extra_price_turn',[False,True])
def test_production_runtime_cross_session_accepts_current_offer(extra_price_turn):
    async def run():
        runtime,gateway,model=production_case()
        gateway.promos=[{'type':'gift','promo_code':'WILLOW-GIFT','gift_sku':'SKU-WILLOW-FILTER'},
                        {'type':'freecod','promo_code':'COD-ZERO','discount_vnd':0}]
        first=production_request('Cho tôi xem giá Willow Classic.')
        model.replies.extend([scripted_tool('catalog.search',{'query':'Willow Classic'}),
            AIMessage(content='Willow Classic giá 730.000đ.')])
        await runtime.run(first)
        await gateway.project()
        second=production_request('Willow Classic có tặng quà và COD không?')
        model.replies.append(AIMessage(content='Willow Classic được tặng quà theo chương trình WILLOW-GIFT, miễn phí thu hộ COD.'))
        response=await runtime.run(second)
        assert 'tặng' in response.agent_text
        if extra_price_turn:
            price=production_request('Giá hiện tại bao nhiêu?',sid=second.session_id)
            model.replies.append(AIMessage(content='Willow Classic giá 730.000đ.'))
            await runtime.run(price)
        accept=production_request('ok len don cho a nhe',sid=second.session_id)
        model.replies.append(AIMessage(content='Dạ, em xử lý yêu cầu.'))
        response=await runtime.run(accept)
        from app.mcp_servers.mcp_shared.consultation import consultation_missing_fields,derive_consultation
        s=runtime.state_for(accept)
        assert len(gateway.writes)==1,(response.agent_text,consultation_missing_fields(s),derive_consultation(s))
        assert gateway.writes[0]['price_vnd']==730000
        await gateway.project()
    asyncio.run(run())


def test_production_runtime_region_quote_context_survives_order_only_followup():
    async def run():
        runtime,gateway,model=production_case()
        gateway.promos=[{'type':'gift','promo_code':'WILLOW-GIFT','gift_sku':'SKU-WILLOW-FILTER'},
                        {'type':'freecod','promo_code':'COD-ZERO','discount_vnd':0}]
        first=production_request('Cho tôi xem giá Willow Classic.')
        model.replies.extend([scripted_tool('catalog.search',{'query':'Willow Classic'}),
            AIMessage(content='Willow Classic giá 730.000đ.')])
        await runtime.run(first);await gateway.project()
        region=production_request('Willow Classic có ship COD không, anh ở Q7 HCM.')
        from uuid import UUID
        region=region.model_copy(update={'client_msg_id':UUID('12345678-1234-4123-8123-091234567890')})
        model.replies.extend([scripted_tool('pricing.get_quote',{'sku':'SKU-WILLOW','address':'Q7 HCM'}),
            AIMessage(content='Willow Classic được tặng quà theo chương trình WILLOW-GIFT, miễn phí thu hộ COD.')])
        await runtime.run(region)
        accept=production_request('ok len don cho a nhe',sid=region.session_id)
        model.replies.append(AIMessage(content='Dạ, em xử lý yêu cầu.'))
        response=await runtime.run(accept)
        assert len(gateway.writes)==1,response.agent_text
        assert gateway.writes[0].get('address')=='Q7 HCM'
        quotes=[args for name,args in gateway.calls if name=='pricing.get_quote']
        region_index=next(i for i,args in enumerate(quotes) if args.get('address')=='Q7 HCM')
        assert all(args.get('address')=='Q7 HCM' for args in quotes[region_index:])
    asyncio.run(run())


def test_production_runtime_price_increase_then_order_only_accepts_new_presented_price():
    async def run():
        runtime,gateway,model=production_case()
        first=production_request('Cho tôi xem giá Willow Classic.')
        model.replies.extend([scripted_tool('catalog.search',{'query':'Willow Classic'}),
            AIMessage(content='Willow Classic giá 730.000đ.')])
        await runtime.run(first);await gateway.project()
        gateway.price=780000
        request=production_request('Lấy Willow Classic giá hôm trước, lên đơn nhé.',on='2026-11-06')
        model.replies.append(AIMessage(content='Dạ, em kiểm tra.'))
        response=await runtime.run(request)
        assert gateway.writes==[]
        assert '780.000' in response.agent_text and 'đồng ý' in response.agent_text
        accept=production_request('Thôi cũng được, lên đơn.',sid=request.session_id,on='2026-11-06')
        model.replies.append(AIMessage(content='Dạ, em xử lý yêu cầu.'))
        response=await runtime.run(accept)
        assert len(gateway.writes)==1,response.agent_text
        assert gateway.writes[0]['price_vnd']==780000
    asyncio.run(run())


@pytest.mark.parametrize('mode',['higher_price','lost_gift','quantity','revoked','conditional',
    'refused_payment','delivery','required_code','failed_refresh','wrong_owner'])
def test_production_runtime_consent_scope_and_transaction_retry(mode):
    async def run():
        runtime,gateway,model=production_case()
        gift={'type':'gift','promo_code':'WILLOW-GIFT','gift_sku':'SKU-WILLOW-FILTER'}
        gateway.promos=[gift]
        first=production_request('Cho tôi xem giá Willow Classic.')
        model.replies.extend([scripted_tool('catalog.search',{'query':'Willow Classic'}),
            AIMessage(content='Willow Classic giá 730.000đ, tặng quà theo chương trình WILLOW-GIFT.')])
        first_response=await runtime.run(first)
        assert 'tặng' in first_response.agent_text,first_response.agent_text
        await gateway.project()
        on='2026-11-05'
        if mode=='higher_price':gateway.price=780000;on='2026-11-06'
        if mode=='lost_gift':gateway.promos=[];on='2026-11-06'
        if mode=='failed_refresh':gateway.fail_quote=True;on='2026-11-06'
        if mode=='wrong_owner':
            async def other_owner(*args):return 'OTHER'
            gateway.repo.owner=other_owner
        if mode=='revoked':
            revoke=production_request('Không mua Willow Classic nữa.',sid=first.session_id)
            model.replies.append(AIMessage(content='Dạ, em ghi nhận.'))
            await runtime.run(revoke)
        text={'quantity':'Lên đơn 2 chiếc nhé.', 'conditional':'Nếu lên đơn thì sao?',
            'refused_payment':'Lên đơn, nhưng không COD nhé.', 'delivery':'Lên đơn, giao trong tuần này nhé.',
            'required_code':'Lên đơn, phải dùng mã EXACT-SALE.'}.get(mode,'Lên đơn mẫu đó nhé.')
        accept=production_request(text,sid=first.session_id,on=on)
        model.replies.append(AIMessage(content='Dạ, em kiểm tra điều kiện.'))
        if mode=='wrong_owner':
            with pytest.raises(RuntimeError,match='memory_turn_write_failed'):
                await runtime.run(accept)
        else:
            await runtime.run(accept)
        assert gateway.writes==[],(mode,runtime.state_for(accept))
    asyncio.run(run())


@pytest.mark.parametrize('failed',[False,True])
def test_production_runtime_receipt_or_failed_write_does_not_automatically_repeat(failed):
    async def run():
        runtime,gateway,model=production_case()
        first=production_request('Cho tôi xem giá Willow Classic.')
        model.replies.extend([scripted_tool('catalog.search',{'query':'Willow Classic'}),
            AIMessage(content='Willow Classic giá 730.000đ.')])
        await runtime.run(first)
        gateway.order_error=failed
        accept=production_request('Lên đơn nhé.',sid=first.session_id)
        model.replies.append(AIMessage(content='Dạ, em xử lý.'))
        response=await runtime.run(accept)
        assert len(gateway.writes)==1
        count=len(gateway.repo.runtime.sessions[str(accept.session_id)]['turns'])
        assert await runtime.run(accept)==response
        assert len(gateway.writes)==1
        assert len(gateway.repo.runtime.sessions[str(accept.session_id)]['turns'])==count
        follow=production_request('Cảm ơn em nhé.',sid=first.session_id)
        model.replies.append(AIMessage(content='Dạ.'))
        final=await runtime.run(follow)
        assert len(gateway.writes)==1
        if failed:assert 'đã tạo đơn' not in response.agent_text and 'đã tạo đơn' not in final.agent_text
    asyncio.run(run())


def test_production_runtime_bound_variant_change_still_needs_consent():
    async def run():
        runtime,gateway,model=production_case(variants=True)
        first=production_request('Willow Classic size 39 màu đen giá bao nhiêu?')
        model.replies.extend([scripted_tool('catalog.search',{'query':'Willow Classic'}),
            AIMessage(content='Willow Classic size 39 màu đen giá 730.000đ.')])
        await runtime.run(first)
        accept=production_request('Lên đơn size 41 màu đen nhé.',sid=first.session_id)
        model.replies.append(AIMessage(content='Dạ, em kiểm tra đúng size.'))
        await runtime.run(accept)
        assert gateway.writes==[]
        assert any(c['name']=='pricing.get_quote' and c['args']['sku']=='SKU-WILLOW-41-DEN'
                   for c in runtime.state_for(accept)['tool_calls'])
    asyncio.run(run())


@pytest.mark.parametrize('sku,name,price',[('SKU-ALDER','Alder Plus',610000),('SKU-LARCH','Larch Prime',820000)])
def test_production_benchmark_runner_uses_real_runtime_and_committed_readback(tmp_path,sku,name,price):
    runtime,gateway,model=production_case(sku=sku,name=name,price=price)
    model.replies.extend([scripted_tool('catalog.search',{'query':name}),
        AIMessage(content=f'{name} giá {price:,}đ.'.replace(',','.')),
        AIMessage(content='Dạ, em xử lý yêu cầu.')])
    scenarios={'UNRELATED-LIFECYCLE':{'calls':{
        'call_1':{'call_date':'2026-11-05','customer_turns':[f'Cho tôi xem giá {name}.']},
        'call_2':{'call_date':'2026-11-06','customer_turns':['Lên đơn mẫu hôm trước nhé.']}}}}
    async def wait(*args):await gateway.project()
    out=tmp_path/'production-trace.jsonl'
    asyncio.run(run_configuration(scenarios=scenarios,config='full',runtime=runtime,
        run_id='offline-production',out=out,wait_for_jobs=wait,capture_writes=AsyncMock(return_value={})))
    rows=[json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows)==2
    assert f'{price:,}'.replace(',','.') in rows[0]['agent_text']
    assert len(gateway.writes)==1 and gateway.writes[0]['sku']==sku
    assert [c['name'] for c in rows[1]['tool_calls']].count('order.create')==1
    assert all(j['status']=='completed' for j in gateway.repo.jobs)


def test_decision_capture_preserves_production_purchase_and_worker_readback(monkeypatch, tmp_path):
    """Instrumentation observes the real graph and worker; no gate/reducer is patched."""
    from app.mcp_servers.mcp_shared import decision_diagnostics as d
    from eval_harness.turn_diagnostics import TurnDiagnostics, verify_decisions
    first = production_request('Cho tôi xem giá Willow Classic.')
    accept = production_request('Ok em lên đơn cho anh, thanh toán COD nhé.', sid=first.session_id)

    async def run(observe):
        runtime, gateway, model = production_case()
        model.replies.extend([scripted_tool('catalog.search', {'query': 'Willow Classic'}),
            AIMessage(content='Willow Classic giá 730.000đ.'),
            AIMessage(content='Dạ, em xử lý yêu cầu.')])
        collector = TurnDiagnostics()
        outputs, rows = [], []
        for index, request in enumerate((first, accept), 1):
            from contextlib import nullcontext
            with d.capture_decisions() if observe else nullcontext(None) as capture:
                response = await runtime.run(request)
            await gateway.project()
            state = runtime.state_for(request)
            row = dict(run_id='offline', config='full', scenario_id='capture', call='call_1',
                turn=index, agent_text=response.agent_text)
            rows.append(row)
            outputs.append((response.agent_text, deepcopy(state['tool_calls'])))
            if observe:
                job = gateway.repo.jobs[-1]
                d.observe_job(capture, {'revision': job['job_id'], 'status': job['status'],
                    'envelope': job['accepted_proposals'].get('_decision_diagnostics')}, state)
                assert capture.errors == 0, capture.events
                collector.observe_decisions(row, capture)
        return outputs, gateway.writes, collector, rows

    monkeypatch.delenv('EVAL_DECISION_DIAGNOSTICS', raising=False)
    plain, writes, _, _ = asyncio.run(run(False))
    monkeypatch.setenv('EVAL_DECISION_DIAGNOSTICS', '1')
    observed, observed_writes, collector, rows = asyncio.run(run(True))
    assert observed == plain
    assert observed_writes == writes and len(writes) == 1
    assert all(not t['missing_components'] for t in collector.decision_turns)
    events = collector.decisions
    assert any(e['event'] == 'worker_admission' and 'snapshot' in e for e in events)
    assert any(e['event'] == 'worker_projection' for e in events)
    assert any(e['event'] == 'gate_result' and e['status'] == 'allowed' for e in events)
    trace = tmp_path / 'parity.jsonl'
    trace.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    ref = collector.write_decisions(trace)
    verify_decisions(trace, ref)
    raw = (tmp_path / ref['path']).read_text()
    assert '0900000000' not in raw and 'C-INTEGRATION' not in raw


@pytest.mark.parametrize('reverse', [False, True])
def test_production_budget_followup_keeps_scope_and_commits_one_offer(reverse):
    async def run():
        runtime, gateway, model = production_case(price=730000)
        first_item = gateway.products[0]
        first_item.update(category='air', attributes={'room_area_m2': 30, 'child_safe_lock': True})
        alternative = {'sku': 'SKU-ZEPHYR', 'name': 'Zephyr Air', 'category': 'air',
            'list_price_vnd': 900000, 'variants': [], 'attributes': {'room_area_m2': 30}}
        gateway.products.append(alternative)
        if reverse: gateway.products.reverse()
        first = production_request('Tôi cần máy lọc không khí cho phòng 25m2.')
        model.replies.extend([scripted_tool('catalog.search', {'query': 'máy lọc', 'min_room_area_m2': 25}),
            AIMessage(content='Em tìm thấy Willow Classic và Zephyr Air.')])
        await runtime.run(first)
        await gateway.project()
        unrelated = {'sku': 'SKU-BUGGY', 'name': 'Travel Buggy', 'category': 'stroller',
            'list_price_vnd': 100000, 'variants': [], 'attributes': {}}
        gateway.products.insert(0, unrelated)
        follow = production_request('Ngân sách khoảng 800.000đ thôi.', sid=first.session_id)
        model.replies.append(AIMessage(content='Dạ, em sẽ kiểm tra phương án phù hợp.'))
        response = await runtime.run(follow)
        assert 'Willow Classic' in response.agent_text and '730.000' in response.agent_text, response.agent_text
        assert 'Travel Buggy' not in response.agent_text
        assert gateway.writes == []
        state = runtime.state_for(follow)
        assert not any(c['name'] == 'catalog.search' for c in state['tool_calls'])
        from app.mcp_servers.mcp_shared.consultation import derive_consultation
        assert derive_consultation(state).snapshot.accepted_offer is None
        await gateway.project()
        accept = production_request('Lấy mẫu em đề xuất, lên đơn giúp tôi.', sid=first.session_id)
        model.replies.append(AIMessage(content='Dạ, em xử lý yêu cầu.'))
        result = await runtime.run(accept)
        assert len(gateway.writes) == 1, result.agent_text
        assert gateway.writes[0]['sku'] == 'SKU-WILLOW'
        assert 'OD-PRODUCTION' in result.agent_text
        again = await runtime.run(accept)
        assert again == result and len(gateway.writes) == 1
    asyncio.run(run())


@pytest.mark.parametrize('include_prior', [False, True])
def test_production_shortlist_cross_session_respects_memory_configuration(include_prior):
    async def run():
        runtime, gateway, model = production_case(price=730000)
        gateway.products[0].update(category='air', attributes={'room_area_m2': 30})
        gateway.products.append({'sku': 'SKU-ZEPHYR', 'name': 'Zephyr Air', 'category': 'air',
            'list_price_vnd': 900000, 'variants': [], 'attributes': {'room_area_m2': 30}})
        first = production_request('Tôi cần máy lọc không khí cho phòng 25m2.')
        model.replies.extend([scripted_tool('catalog.search', {'query': 'máy lọc', 'min_room_area_m2': 25}),
            AIMessage(content='Em tìm thấy Willow Classic và Zephyr Air.')])
        await runtime.run(first)
        await gateway.project()
        runtime.memory.include_prior = include_prior
        follow = production_request('Ngân sách khoảng 800.000đ, tư vấn giúp tôi.')
        model.replies.append(AIMessage(content='Dạ, em kiểm tra phương án phù hợp.'))
        response = await runtime.run(follow)
        state = runtime.state_for(follow)
        quotes = [c for c in state['tool_calls'] if c['name'] == 'pricing.get_quote']
        if include_prior:
            assert quotes and '730.000' in response.agent_text, response.agent_text
            assert 'Willow Classic' in response.agent_text
        else:
            assert not quotes and not state.get('episodes')
            assert 'loại sản phẩm' in response.agent_text, response.agent_text
        assert gateway.writes == []
    asyncio.run(run())


class FollowupProductionGateway(ProductionGateway):
    def __init__(self, products, price=730000):
        super().__init__(products, price)
        self.policy_status = 'ok'
        self.policy_contexts = []
        self.expired_promos = []
    async def invoke(self, name, args):
        if name == 'pricing.get_quote':
            result = await super().invoke(name, args)
            return {**result, 'expired_promos': list(self.expired_promos)}
        if name != 'policy.search': return await super().invoke(name, args)
        self.calls.append((name, deepcopy(args)))
        return {'retrieval_status': self.policy_status, 'context': {},
            'evidence_set': {'required_dependencies_complete': True},
            'evidence': [] if self.policy_status != 'ok' else [{
                'chunk_id': 'PUBLIC-WARRANTY', 'section_id': 'warranty', 'document_id': 'public',
                'content': 'Bảo hành 24 tháng cho lỗi kỹ thuật do nhà sản xuất. Không bảo hành hư hỏng do sử dụng sai hướng dẫn.',
                'source': {}, 'evidence_type': 'business_rule', 'applicability': {'status': 'applicable'}}]}
    async def invoke_trusted(self, name, args, *identity, **context):
        if name == 'policy.search': self.policy_contexts.append(context.get('policy_context'))
        return await self.invoke(name, args)


    async def project(self):
        from app.mcp_servers.mcp_memory.distiller_worker import process_one
        from app.schemas.langmem import ProfileFactCandidate
        from datetime import date
        async def extractor(messages, *args):
            payload = json.loads(messages[-1]['content'])
            speech = payload['customer_text']
            if 'đắt quá' not in speech:
                return [], None
            return [ProfileFactCandidate(key='objection', value='dat_qua', source_kind='customer',
                source_turn_id=payload['turn_id'], evidence_quote=speech,
                observed_on=date.fromisoformat(payload['on']), scope_type='product', scope_id='SKU-WILLOW')], None
        while any(j['status'] == 'pending' for j in self.repo.jobs):
            assert await process_one(self.repo, extractor, self.repo)
            assert all(j.get('error_code') is None for j in self.repo.jobs), self.repo.jobs


def production_followup_case():
    from datetime import datetime, timezone
    from app.agent.harness.runtime import AgentHarnessRuntime
    from app.agent.memory.store import MCPMemoryStore
    products = [{'sku': 'SKU-WILLOW', 'name': 'Willow Classic', 'variants': [],
                 'category': 'air', 'attributes': {}, 'list_price_vnd': 730000}]
    gateway = FollowupProductionGateway(products)
    model = ProductionModel(replies=[])
    runtime = AgentHarnessRuntime(model, gateway, MCPMemoryStore(gateway), max_tool_calls=6,
        clock=lambda: datetime(2026, 11, 5, tzinfo=timezone.utc))
    return runtime, gateway, model


def test_production_warranty_question_is_answered_even_when_customer_pauses_purchase():
    async def run():
        runtime, gateway, model = production_followup_case()
        request = production_request('Willow Classic bảo hành thế nào? Tôi cân nhắc thêm rồi báo lại.')
        model.replies.append(AIMessage(content='Dạ, mình cứ cân nhắc thêm nhé.'))
        response = await runtime.run(request)
        searches = [args for name, args in gateway.calls if name == 'policy.search']
        assert len(searches) == 1, (response.agent_text, gateway.calls)
        assert '24 tháng' in response.agent_text and 'sai hướng dẫn' in response.agent_text
        assert searches[0]['on'] == '2026-11-05' and 'order_date' not in searches[0]
        assert gateway.policy_contexts[0].verified_order_date is None
        assert gateway.writes == []
    asyncio.run(run())


@pytest.mark.parametrize('include_prior', [False, True])
@pytest.mark.parametrize('promotion_status', ['expired', 'absent', 'equivalent'])
def test_production_returning_objection_uses_current_offer_and_keeps_consent_boundary(include_prior, promotion_status):
    async def run():
        runtime, gateway, model = production_followup_case()
        gateway.promos = [{'type': 'gift', 'promo_code': 'GIFT-OLD', 'gift_sku': 'SKU-WILLOW-FILTER'},
                          {'type': 'freecod', 'promo_code': 'COD-ZERO', 'discount_vnd': 0}]
        first = production_request('Cho tôi xem giá Willow Classic.')
        model.replies.extend([scripted_tool('catalog.search', {'query': 'Willow Classic'}),
            AIMessage(content='Willow Classic giá 730.000đ, tặng quà theo mã GIFT-OLD, miễn phí thu hộ COD.')])
        await runtime.run(first); await gateway.project()
        objection = production_request('Willow Classic đắt quá, bên kia tôi thấy bán 650k.', sid=first.session_id)
        model.replies.append(AIMessage(content='Willow Classic giá 730.000đ.'))
        response = await runtime.run(objection)
        assert 'COD' in response.agent_text and '650' not in response.agent_text, response.agent_text
        await gateway.project()
        assert gateway.writes == []
        runtime.memory.include_prior = include_prior
        gateway.price = 730000 if promotion_status == 'equivalent' else 790000
        gateway.promos = ([{'type': 'gift', 'promo_code': 'GIFT-NEW', 'gift_sku': 'SKU-WILLOW-FILTER'},
                           {'type': 'freecod', 'promo_code': 'COD-ZERO', 'discount_vnd': 0}]
                          if promotion_status == 'equivalent' else [])
        gateway.expired_promos = ['GIFT-OLD'] if promotion_status == 'expired' else []
        follow = production_request('Tôi gọi lại về Willow Classic hôm trước.', on='2026-11-06')
        model.replies.append(AIMessage(content='Dạ em chào mình. Mình đã quyết định chưa ạ?'))
        response = await runtime.run(follow)
        if include_prior:
            observed = runtime.state_for(follow)
            assert 'mức giá' in response.agent_text and '650' not in response.agent_text, json.dumps({
                'text': response.agent_text, 'draft': observed.get('agent_draft'),
                'reasons': [e.get('reason') for e in observed.get('verifier_events', [])]}, ensure_ascii=False)
            assert ('730.000' if promotion_status == 'equivalent' else '790.000') in response.agent_text
            if promotion_status == 'expired': assert 'hết hạn' in response.agent_text
            else: assert 'hết hạn' not in response.agent_text
            if promotion_status == 'equivalent': assert 'xác nhận lại' not in response.agent_text
        else:
            assert 'mức giá' not in response.agent_text and 'hết hạn' not in response.agent_text
        assert gateway.writes == []
        if include_prior:
            accept = production_request('Lấy mẫu đó, lên đơn giúp tôi.', sid=follow.session_id, on='2026-11-06')
            model.replies.append(AIMessage(content='Dạ em xử lý yêu cầu.'))
            receipt = await runtime.run(accept)
            assert len(gateway.writes) == 1, receipt.agent_text
            assert gateway.writes[0]['price_vnd'] == gateway.price
            assert await runtime.run(accept) == receipt and len(gateway.writes) == 1
    asyncio.run(run())


def test_production_policy_and_price_questions_keep_both_supported_answers_during_pause():
    async def run():
        runtime, gateway, model = production_followup_case()
        first = production_request('Cho tôi xem giá Willow Classic.')
        model.replies.extend([scripted_tool('catalog.search', {'query': 'Willow Classic'}),
                              AIMessage(content='Willow Classic giá 730.000đ.')])
        await runtime.run(first)
        follow = production_request('Giá Willow Classic vẫn vậy và bảo hành thế nào? Tôi cân nhắc thêm.', sid=first.session_id)
        model.replies.append(AIMessage(content='Mình cứ cân nhắc thêm nhé.'))
        answer = await runtime.run(follow)
        assert '730.000' in answer.agent_text and '24 tháng' in answer.agent_text, answer.agent_text
        assert len([name for name, _ in gateway.calls if name == 'policy.search']) == 1
        assert gateway.writes == []
    asyncio.run(run())


def test_production_good_policy_draft_is_kept_and_bad_claim_is_recorded():
    async def run(bad):
        runtime, gateway, model = production_followup_case()
        request = production_request('Willow Classic bảo hành thế nào?')
        text = ('Bảo hành 99 tháng.' if bad else
                'Bảo hành 24 tháng cho lỗi kỹ thuật do nhà sản xuất. Không bảo hành hư hỏng do sử dụng sai hướng dẫn.')
        model.replies.append(AIMessage(content=text))
        answer = await runtime.run(request)
        if bad:
            assert '99 tháng' not in answer.agent_text and '24 tháng' in answer.agent_text
            assert runtime.state_for(request).get('verifier_events')
        else:
            assert answer.agent_text == text
            assert not runtime.state_for(request).get('verifier_events')
        assert gateway.writes == []
    asyncio.run(run(False)); asyncio.run(run(True))
