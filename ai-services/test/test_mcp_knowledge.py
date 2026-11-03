import asyncio
from fastmcp import Client
from test_policy_search import search_fixture, request_context
from test_policy_rules import chunk


def test_mcp_policy_search_requires_signed_request_bound_context():
    from app.mcp_servers.mcp_knowledge.tools.handlers import create_server
    from app.mcp_servers.mcp_knowledge.tools.auth import sign_policy_context
    async def run():
        service,_,_=await search_fixture([chunk()])
        server=create_server(service,context_secret='test-only-secret')
        request,context=request_context()
        args=request.model_dump(mode='json',exclude_none=True)
        args['trusted_context']=sign_policy_context(request,context,'test-only-secret')
        async with Client(server) as client:
            result=await client.call_tool('policy.search',args)
            data=result.data if isinstance(result.data,dict) else result.structured_content
            assert data['retrieval_status']=='ok'
            assert data['evidence'][0]['chunk_id']=='DT-01'
            forged={**args,'query':'different question'}
            result=await client.call_tool('policy.search',forged)
            data=result.data if isinstance(result.data,dict) else result.structured_content
            assert data['error']=='forbidden'
            result=await client.call_tool('policy.search',{'query':'đổi trả','on':'2026-11-03'})
            data=result.data if isinstance(result.data,dict) else result.structured_content
            assert data['error']=='forbidden'
    asyncio.run(run())


def test_gateway_routes_policy_to_knowledge_and_strips_forged_context():
    from app.mcp_servers.mcp_knowledge.tools.handlers import create_server
    from app.agent.mcp.gateway import MCPGateway
    async def run():
        service,_,_=await search_fixture([chunk()])
        server=create_server(service,context_secret='test-only-secret')
        gateway=MCPGateway(None,None,None,knowledge=server,context_secret='test-only-secret')
        result=await gateway.invoke('policy.search',{'query':'đổi trả','on':'2026-11-03',
            'order_date':'2020-01-01','knowledge_release_id':'forged','trusted_context':'forged'})
        assert result['retrieval_status']=='ok'
        assert result['context']['order_date'] is None
        assert result['evidence'][0]['applicability']['status']=='conditional'
    asyncio.run(run())


def test_http_endpoint_rejects_missing_auth_before_tool_execution():
    import httpx
    from app.mcp_servers.mcp_knowledge.tools.handlers import create_server
    async def run():
        service,_,index=await search_fixture([chunk()])
        server=create_server(service,token='test-http-secret')
        app=server.http_app(path='/mcp')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            result=await client.post('/mcp',headers={'Accept':'application/json, text/event-stream'},json={
                'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26',
                'capabilities':{},'clientInfo':{'name':'functional-test','version':'1'}}})
            assert result.status_code==401
        assert index.calls==0
        await service.close()
    asyncio.run(run())


def test_release_endpoint_delegates_to_service_without_private_validation_access():
    class Service:
        ready = True
        async def release_ref(self, release_id=None):
            return {'release_id': release_id or 'active-release', 'manifest_hash': 'safe-hash'}
        async def close(self):
            pass
    from app.mcp_servers.mcp_knowledge.tools.handlers import create_server
    async def run():
        server = create_server(Service(), context_secret='test-secret')
        async with Client(server) as client:
            result = await client.call_tool('eval.knowledge_release', {'release_id': 'pinned-release'})
            data = result.data if isinstance(result.data, dict) else result.structured_content
            assert data == {'release_id': 'pinned-release', 'manifest_hash': 'safe-hash'}
    asyncio.run(run())
