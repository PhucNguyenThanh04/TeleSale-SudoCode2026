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


    def state_for(self,request):return self.states[str(request.client_msg_id)]


class CommittedRepo:
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
    assert rows[1]['tool_calls']==[]
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
