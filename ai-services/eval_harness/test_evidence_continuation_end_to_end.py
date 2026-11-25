import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from eval_harness.benchmark_runner import run_configuration
from eval_harness.turn_diagnostics import verify_turn_diagnostics


class CommittedRepo:
    def __init__(self,runtime):self.runtime=runtime;self.observed={}
    @asynccontextmanager
    async def transaction(self):yield None
    async def owner(self,conn,sid):return 'C-INTEGRATION'
    async def lock_key(self,*args):pass
    async def next_turn(self,conn,sid):return len(self.runtime.sessions[sid]['turns'])+1
    async def turn_count(self,conn,sid):return len(self.runtime.sessions[sid]['turns'])
    async def insert_turn(self,conn,sid,number,cid,channel,on,customer,agent,tid,
                          observations=(),outcome='khac',**kwargs):
        self.runtime.sessions[sid]['turns'].append({'turn_id':tid,'customer_id':cid,
            'session_id':sid,'on':str(on),'customer_text':customer,'agent_text':agent,
            'tool_observations': observations, 'request_hash': kwargs.get('request_hash')})
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


class ProductionRepo(CommittedRepo):
    def __init__(self):
        super().__init__(SimpleNamespace(sessions={},episodes={}))
        self.jobs=[];self.operations={};self.facts=[];self.links=[];self.products=[]

    async def owner(self,conn,sid):
        turns=self.runtime.sessions.setdefault(sid,{'turns':[],'calls':[]})['turns']
        return turns[0]['customer_id'] if turns else None

    async def is_erasure_blocked(self,*args):return False

    async def replay_turn(self, conn, sid, tid):
        return next((turn for turn in self.runtime.sessions[sid]['turns']
                     if turn['turn_id'] == tid), None)

    async def recent_customer_sessions(self, conn, cid, maximum):
        turns = [session['turns'][-1] for session in self.runtime.sessions.values()
                 if session['turns'] and session['turns'][-1]['customer_id'] == cid]
        return [{'session_id': turn['session_id'], 'on_date': turn['on'], 'channel': turn['channel']}
                for turn in reversed(turns[-maximum:])]

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

    async def insert_turn(self,conn,sid,number,cid,channel,on,customer,agent,tid,*args,**kwargs):
        await super().insert_turn(conn,sid,number,cid,channel,on,customer,agent,tid,*args,**kwargs)
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
        if name=='memory.replay':
            from app.mcp_servers.mcp_memory.services.replay import replay_turn
            return await replay_turn(self.repo, **args)
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

    async def invoke_trusted(self,name,args,*identity,**context):return await self.invoke(name,args)

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
    def with_structured_output(self, schema, **kwargs):
        async def review(messages):
            if schema.__name__ == 'GroundingReview':
                return schema(supported=True, reason='supported', unsupported_claim='')
            text = json.loads(messages[-1].content)['customer_text']
            return schema(allowed=True, basis='customer_request',
                          customer_quote=text, reason='authorized')
        return SimpleNamespace(ainvoke=review)
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
        scripted_tool('pricing.get_quote', {'sku': sku}),
        AIMessage(content=f'{name} giá {price:,}đ.'.replace(',','.')),
        scripted_tool('catalog.search', {'query': name}),
        scripted_tool('pricing.get_quote', {'sku': sku}),
        scripted_tool('inventory.check', {'sku': sku}),
        scripted_tool('order.create', {'sku': sku, 'price_vnd': price}),
        AIMessage(content='Em đã tạo đơn OD-PRODUCTION.')])
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
    last_turn = next(reversed(runtime._states.values()))
    assert last_turn['call_brief']['is_returning'] is True
    assert any(f'{price:,}'.replace(',', '.') in turn['agent']
               for episode in last_turn['episodes'] for turn in episode.get('committed_turns', []))
    assert verify_turn_diagnostics(out)['rows'] == 2
