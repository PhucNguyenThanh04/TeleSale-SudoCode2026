import asyncio
from types import SimpleNamespace

from pydantic import SecretStr

from rag_eval.adapters import MCPRetriever


def test_real_mcp_handler_accepts_signed_eval_context(monkeypatch):
    from fastmcp import Client
    from app.mcp_servers.mcp_knowledge.schemas import PolicySearchResult
    from app.mcp_servers.mcp_knowledge.tools.handlers import create_server

    class Service:
        ready = True
        seen = []

        async def close(self):
            pass

        async def release_ref(self, release_id=None):
            return {'release_id': release_id or 'pinned', 'manifest_hash': 'hash'}

        async def search(self, request, context):
            self.seen.append(context)
            return PolicySearchResult(retrieval_status='no_evidence', context={
                'knowledge_release_id': context.release_id})

    service = Service()
    server = create_server(service, context_secret='offline-secret')
    monkeypatch.setattr('fastmcp.Client', lambda transport, **kwargs: Client(transport))
    settings = SimpleNamespace(mcp_knowledge_url=server,
        mcp_internal_token=SecretStr('offline-secret'), knowledge_policy_config_file=None,
        knowledge_release_id=None)
    async def run():
        adapter = MCPRetriever(settings)
        release = await adapter.pin()
        result = await adapter.search({'query': 'Đổi hàng?', 'on': '2026-10-15',
            'verified_order_date': '2026-09-28', 'date_source': 'eval_fixture'}, release, 5)
        assert result['retrieval_status'] == 'no_evidence'
        assert service.seen[0].release_id == 'pinned'
        assert service.seen[0].date_source == 'eval_fixture'
        assert service.seen[0].include_supplements is False
    asyncio.run(run())
