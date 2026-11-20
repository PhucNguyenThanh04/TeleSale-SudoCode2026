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
