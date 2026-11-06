"""Real rules, admission, JSON persistence and runner; scripted tools, no model/DB."""
import asyncio
from copy import deepcopy
from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.agent.implementations.business_agent import BusinessTools
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.harness.session_nodes import safe_catalog_reply, safe_quote_reply, safe_transaction_reply
from app.mcp_servers.mcp_shared.consultation import committed_consultation, derive_consultation
from app.mcp_servers.mcp_memory.services.langmem_admission import admit_episode_candidate
from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta
from app.schemas.langmem import CustomerCallEpisodeCandidate
from eval_harness.benchmark_runner import run_configuration
from eval_harness.turn_diagnostics import verify_turn_diagnostics


class Runtime:
    def __init__(self, sku, name, price, *, new_price=None):
        self.sku,self.name,self.price=sku,name,price
        self.new_price=new_price
        self.memory=SimpleNamespace(include_prior=True,namespace='')
        self.states={};self.sessions={};self.episodes={};self.trades=[]
        self.nodes=AgentNodes(None,None,None,8,6)

    async def run(self, request):
        sid=str(request.session_id);tid=str(request.client_msg_id)
        session=self.sessions.setdefault(sid,{'turns':[],'calls':[]})
        state={'request':request,'safe_text':request.text,'customer_id':'C-SYNTHETIC','customer_phone':'0900000000',
               'identity_status':'known','profile':{},'scoped_facts':{},'tool_calls':[],
               'session_tool_calls':deepcopy(session['calls']),
               'history':[{'customer':t['customer_text'],'agent':t['agent_text'],'source_turn_id':t['turn_id']} for t in session['turns']],
               'episodes':[deepcopy(ep) for key,ep in self.episodes.items() if key!=sid],
               'current_episode':deepcopy(self.episodes.get(sid)), 'tool_count':0}
        price=self.new_price if len(self.sessions)>1 and self.new_price else self.price
        async def invoke(name,args,*a,**kw):
            if name=='catalog.search':
                return {'items':[{'sku':self.sku,'name':self.name,'variants':[], 'list_price_vnd':self.price,
                                  'attributes':{'room_area_m2':35,'child_safe_lock':True}}]}
            if name=='pricing.get_quote':return {'sku':self.sku,'final_price_vnd':price,'applied_promos':[]}
            if name=='inventory.check':return {'sku':self.sku,'in_stock':True,'qty':10}
            if name=='order.create':
                self.trades.append(deepcopy(args));return {'status':'created','order_id':'OD-SYNTHETIC'}
            raise AssertionError('unexpected tool')
        gateway=SimpleNamespace(invoke_trusted=invoke)
        business=BusinessTools(gateway,state,8,lambda:None)
        if not session['turns'] and not self.episodes:
            await business.invoke('catalog.search',{'min_room_area_m2':25})
        await business.prepare_consultation()
        d=derive_consultation(state)
        if d.purchase_intent and d.snapshot.selected_sku:
            args={'sku':self.sku,'price_vnd':price,'qty':1}
            result=await business.invoke('order.create',args)
            if result.get('status')=='created':
                # An agent retry in this turn must return the receipt, not write twice.
                assert await business.invoke('order.create',args)==result
            answer=safe_transaction_reply(state) or safe_quote_reply(state) or 'Mình cần xác nhận lại lựa chọn.'
        else:
            answer=safe_catalog_reply(state) or safe_quote_reply(state) or 'Dạ, em ghi nhận yêu cầu.'
        state['agent_draft']=answer
        verified=await self.nodes.verify_agent(state)
        state.update(verified)
        self.states[tid]=state
        committed={'turn_id':tid,'customer_id':'C-SYNTHETIC','session_id':sid,'on':request.on.isoformat(),
                   'customer_text':request.text,'agent_text':state['agent_text']}
        session['turns'].append(committed)
        session['calls'].extend({**deepcopy(c),'source_turn_id':tid} for c in state['tool_calls'])
        snap=committed_consultation('C-SYNTHETIC',sid,session['turns'],session['calls'])
        fresh={k:v for k,v in snap.source_refs.items() if v.source_turn_id==tid}
        payload=snap.model_dump(mode='json')
        patch={k:payload[k] for k in fresh};patch['source_refs']={k:v.model_dump(mode='json') for k,v in fresh.items()}
        old=self.episodes.get(sid,{'customer_id':'C-SYNTHETIC','session_id':sid,'on_date':request.on.isoformat(),'topics':[]})
        if fresh:
            candidate=CustomerCallEpisodeCandidate(customer_id='C-SYNTHETIC',session_id=sid,channel='hotline',on=request.on,
                source_turn_ids=[t['turn_id'] for t in session['turns']],topics=[{'scope_type':'global','consultation':patch}])
            delta=admit_episode_candidate('C-SYNTHETIC',sid,candidate,session['turns'],session['calls'])
            if delta:
                old={**old,**apply_episode_delta(old,delta,source_turn_id=tid,customer_text=request.text,agent_text=state['agent_text'])}
        self.episodes[sid]=json.loads(json.dumps(old))  # serialized readback, not in-process object sharing
        return SimpleNamespace(agent_text=state['agent_text'],call_brief=None)

    def state_for(self,request):return self.states[str(request.client_msg_id)]


@pytest.mark.parametrize('sku,name,price,budget',[('SKU-ASTER','Aster',900000,1000000),('SKU-CEDAR','Cedar',640000,800000)])
def test_consultation_selection_quote_purchase_survive_same_day_session_change(tmp_path,sku,name,price,budget):
    runtime=Runtime(sku,name,price)
    scenarios={'UNRELATED-ID':{'calls':{'call_1':{'customer_turns':[
        f'Tư vấn giúp tôi cho phòng 25m2, ngân sách tối đa {budget}đ.',
        f'Tôi chọn {name} để xem giá.']},
        'call_2':{'days_later':0,'customer_turns':[f'Mua {name} giá {price}đ, lên đơn giúp tôi.']}}}}
    out=tmp_path/'trace.jsonl'
    result=asyncio.run(run_configuration(scenarios=scenarios,config='full',runtime=runtime,run_id='scripted-only',out=out,
        wait_for_jobs=AsyncMock(),capture_writes=AsyncMock(return_value={})))
    assert len(runtime.trades)==1 and runtime.trades[0]['sku']==sku
    rows=[json.loads(line) for line in out.read_text().splitlines()]
    assert not any(c['name']=='order.create' for row in rows[:2] for c in row['tool_calls'])
    assert [c['name'] for c in rows[-1]['tool_calls']]==['catalog.search','pricing.get_quote','inventory.check','order.create']
    state=runtime.states[next(reversed(runtime.states))]
    assert derive_consultation(state).snapshot.selected_sku==sku
    assert verify_turn_diagnostics(out,result['turn_diagnostics'])['rows']==3
    assert state['episodes'][0]['topics'][0]['consultation']['selected_sku']==sku


def test_changed_quote_requires_customer_confirmation_before_write(tmp_path):
    runtime=Runtime('SKU-ASTER','Aster',900000,new_price=950000)
    scenarios={'DIFFERENT-ID':{'calls':{'call_1':{'customer_turns':['Tư vấn máy, ngân sách 1 triệu.','Tôi chọn Aster để xem giá.']},
        'call_2':{'customer_turns':['Lên đơn Aster giá 900.000đ.']}}}}
    asyncio.run(run_configuration(scenarios=scenarios,config='full',runtime=runtime,run_id='scripted',out=tmp_path/'trace.jsonl',
        wait_for_jobs=AsyncMock(),capture_writes=AsyncMock(return_value={})))
    assert runtime.trades==[]
