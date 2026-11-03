import asyncio
from datetime import date
from uuid import uuid4
import pytest
from app.schemas.agent import TextTurnRequest
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.implementations.business_agent import BusinessTools
from app.agent.mcp.gateway import MCPGateway
from app.knowledge.events.runtime import turn_event
from test_policy_search import search_fixture
from test_policy_rules import chunk


@pytest.mark.parametrize('reported,order_date,answer,accepted',[
    (None,'2026-10-10','Chính sách đổi trả trong 7 ngày.',True),
    ('2026-10-10',None,'Theo ngày anh khai, chính sách đổi trả trong 7 ngày; em chưa xác minh quyền lợi của đơn.',True),
    ('2026-10-10',None,'Đơn của anh đủ điều kiện đổi trả trong 7 ngày.',False),
])
def test_functional_policy_path_through_mcp_business_tools_and_guardrail(reported,order_date,answer,accepted):
    from app.mcp_servers.mcp_knowledge.tools.handlers import create_server
    async def run():
        service,_,_=await search_fixture([chunk()])
        server=create_server(service,context_secret='integration-secret')
        gateway=MCPGateway(None,None,None,knowledge=server,context_secret='integration-secret')
        request=TextTurnRequest(client_msg_id=uuid4(),session_id=uuid4(),channel='hotline',
            channel_identity='0900000000',on=date(2026,11,3),text='Chính sách đổi trả?',input_mode='clean')
        calls=[]
        if order_date:
            calls.append({'name':'order.status','result':{'orders':[{'order_id':'OD-TEST','created_on':order_date}]}})
        state={'request':request,'safe_text':request.text,'tool_calls':calls,'tool_count':0,
            'identity_status':'known','customer_id':'synthetic'}
        business=BusinessTools(gateway,state,5,lambda:None)
        args={'query':'đổi trả'}
        if reported:
            args['customer_reported_order_date']=reported
        if order_date:
            args['order_id']='OD-TEST'
        result=await business.invoke('policy.search',args)
        assert result['retrieval_status']=='ok'
        assert result['evidence'][0]['chunk_id']=='DT-01'
        assert result['context'].get('order_date')==order_date
        state['agent_draft']=answer
        verified=await AgentNodes(None,None,None,5,3).verify_agent(state)
        assert (verified['agent_text']==answer)==accepted
        event=turn_event({'tool_observations':state['tool_calls'],'knowledge_signal':'operator_review',
            'customer_text':request.text,'agent_text':verified['agent_text'],'on':'2026-11-03',
            'client_msg_id':str(request.client_msg_id)},str(request.session_id),'synthetic')
        assert event['retrieved_ids']==['DT-01']
        assert not any(c['name'] in {'schedule.callback','handoff.transfer'} for c in state['tool_calls'])
    asyncio.run(run())


def test_operational_failure_is_technical_not_missing_content():
    event=turn_event({'tool_observations':[{'name':'policy.search','result':{
        'retrieval_status':'unavailable','error':'knowledge_unavailable','evidence':[]}}],
        'knowledge_evidence':{'signal':'fallback'},'customer_text':'đổi trả','agent_text':'Chưa xác nhận được',
        'on':'2026-11-03','client_msg_id':'synthetic'},'synthetic','synthetic')
    assert event['signal']=='mcp_unavailable'


def test_repeated_policy_read_revalidates_revocation_instead_of_cached_evidence():
    from app.mcp_servers.mcp_knowledge.tools.handlers import create_server
    async def run():
        service,repo,_=await search_fixture([chunk()])
        gateway=MCPGateway(None,None,None,knowledge=create_server(service,context_secret='test-secret'),context_secret='test-secret')
        request=TextTurnRequest(client_msg_id=uuid4(),session_id=uuid4(),channel='hotline',
            channel_identity='0900000000',on=date(2026,11,3),text='đổi trả?',input_mode='clean')
        state={'request':request,'safe_text':request.text,'tool_calls':[],'tool_count':0}
        business=BusinessTools(gateway,state,5,lambda:None)
        first=await business.invoke('policy.search',{'query':'đổi trả'})
        assert first['retrieval_status']=='ok'
        repo.revoked=True
        second=await business.invoke('policy.search',{'query':'đổi trả'})
        assert second['retrieval_status']=='unavailable'
        assert second['evidence']==[]
    asyncio.run(run())
