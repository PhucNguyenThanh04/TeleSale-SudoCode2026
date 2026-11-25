import asyncio
import json
from types import SimpleNamespace

import httpx2 as httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.configs import Settings
from rag_eval.adapters import Generator, MCPRetriever


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


@pytest.mark.parametrize('content,tool_calls', [
    ('{"answer":"Đổi trong 7 ngày","action":"answer"}', []),
    ('```json\n{"answer":"Đổi trong 7 ngày","action":"answer"}\n```', []),
    (None, [{'id': 'rag-answer', 'type': 'function', 'function': {
        'name': 'RAGAnswer',
        'arguments': '{"answer":"Đổi trong 7 ngày","action":"answer"}'}}]),
])
def test_generator_accepts_structured_and_markdown_answers(monkeypatch, content, tool_calls):
    requests = []

    async def send(client, request, **kwargs):
        requests.append(json.loads(request.content))
        return httpx.Response(200, request=request, json={
            'id': 'rag-test', 'object': 'chat.completion', 'created': 0,
            'model': 'gemma4:31b', 'choices': [{'index': 0,
                'message': {'role': 'assistant', 'content': content, 'tool_calls': tool_calls},
                'finish_reason': 'tool_calls' if tool_calls else 'stop'}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}})

    monkeypatch.setattr(httpx.AsyncClient, 'send', send)
    generator = Generator(Settings(_env_file=None, llm_api_key='offline-key',
        llm_model='gemma4:31b', llm_base_url='https://ollama.com/v1'))
    result = asyncio.run(generator.generate({'question': 'Đổi hàng trong bao lâu?'}))
    assert result['answer'] == 'Đổi trong 7 ngày'
    assert result['action'] == 'answer'
    assert result['usage']['total_tokens'] == 30
    assert len(requests) == 1
    assert requests[0]['tools'][0]['function']['parameters']['required'] == ['answer', 'action']
    assert requests[0]['tool_choice']['function']['name'] == 'RAGAnswer'


@pytest.mark.parametrize('content,finish_reason,error', [
    ('', 'stop', json.JSONDecodeError),
    ('Không phải JSON', 'stop', json.JSONDecodeError),
    ('```json\n{"answer":"7 ngày","action":"answer"', 'stop', json.JSONDecodeError),
    ('{"answer":"7 ngày","action":"unknown"}', 'stop', ValidationError),
    ('{"answer":7,"action":"answer"}', 'stop', ValidationError),
    ('{"answer":"7 ngày","action":"answer"}', 'length', ValueError),
])
def test_generator_rejects_invalid_or_truncated_answers(monkeypatch, content, finish_reason, error):
    async def send(client, request, **kwargs):
        return httpx.Response(200, request=request, json={
            'id': 'rag-test', 'object': 'chat.completion', 'created': 0,
            'model': 'gemma4:31b', 'choices': [{'index': 0,
                'message': {'role': 'assistant', 'content': content},
                'finish_reason': finish_reason}]})

    monkeypatch.setattr(httpx.AsyncClient, 'send', send)
    generator = Generator(Settings(_env_file=None, llm_api_key='offline-key',
        llm_model='gemma4:31b', llm_base_url='https://ollama.com/v1'))
    with pytest.raises(error):
        asyncio.run(generator.generate({'question': 'Đổi hàng trong bao lâu?'}))
