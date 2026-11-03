"""Thin policy tools: validate, authenticate request context, call evidence service."""
from contextlib import asynccontextmanager
from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from pydantic import ValidationError
from app.mcp_servers.mcp_knowledge.tools.auth import verify_policy_context
from app.mcp_servers.mcp_knowledge.services.embedding import PolicyInputError
from app.mcp_servers.mcp_knowledge.schemas import PolicySearchInput
from app.mcp_servers.mcp_shared.observability import trace_mcp_call


def create_server(service, token=None, *, context_secret=None):
    secret=context_secret or token
    if not secret:
        raise ValueError('Knowledge context authentication required')

    @asynccontextmanager
    async def lifespan(server):
        if not service.ready:
            await service.start()
        try:
            yield {}
        finally:
            await service.close()

    auth=StaticTokenVerifier({token:{'client_id':'harness','scopes':['tools']}}) if token else None
    server=FastMCP('telesale-knowledge',auth=auth,lifespan=lifespan)

    @server.tool(name='policy.search')
    async def policy_search(query:str,on:str,order_date:str|None=None,
                            customer_reported_order_date:str|None=None,top_k:int=5,
                            trusted_context:str|None=None)->dict:
        async def run():
            try:
                request=PolicySearchInput(query=query,on=on,order_date=order_date,
                    customer_reported_order_date=customer_reported_order_date,top_k=top_k)
            except ValidationError:
                return {'error':'invalid_args','evidence':[]}
            try:
                context=verify_policy_context(request,trusted_context,secret)
            except PermissionError:
                return {'error':'forbidden','evidence':[]}
            try:
                result=await service.search(request,context)
            except PolicyInputError:
                return {'error':'invalid_args','evidence':[]}
            return result.model_dump(mode='json',exclude_none=True)
        # Signed context/query are deliberately excluded from free-form logs.
        return await trace_mcp_call('knowledge','policy.search',{'on':on,'top_k':top_k},run)

    @server.tool(name='eval.knowledge_release')
    async def knowledge_release(release_id:str|None=None)->dict:
        try:
            return await service.release_ref(release_id)
        except Exception:
            return {'error':'knowledge_unavailable'}

    @server.tool(name='eval.database_identity')
    async def database_identity()->dict:
        return await service.repo.database_identity()

    return server
