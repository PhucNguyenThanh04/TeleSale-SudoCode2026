"""Exercise the real model tool boundary with offline HTTP and MCP."""
import asyncio
import json
import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx2 as httpx
import pytest
from app.configs import Settings
from app.infarstructure.llm import build_llm
from app.agent.implementations import build_agent
from app.agent.implementations.business_agent import BusinessTools
from test_business_completion import state


@pytest.mark.parametrize('kind', ['deep', 'react'])
@pytest.mark.parametrize('model_name,base_url', [
    ('gpt-6-luna', 'https://offline.invalid/v1'),
    ('gemma4:12b', 'https://ollama.com/v1'),
    ('gemma4:31b', 'https://ollama.com/v1'),
])
def test_real_model_tool_roundtrip(kind, model_name, base_url):
    async def run():
        current = state()
        current['safe_text'] = 'Tìm máy lọc không khí'
        gateway = AsyncMock()
        gateway.invoke_trusted.return_value = {'items': []}
        business = BusinessTools(gateway, current, 8, lambda: datetime.now(timezone.utc))
        model = build_llm(Settings(_env_file=None, llm_api_key='offline-key',
            llm_model=model_name, llm_base_url=base_url))
        requests = []
        async def send(client, request, **kwargs):
            payload = json.loads(request.content)
            requests.append(payload)
            assert str(request.url) == base_url + '/chat/completions'
            assert payload['model'] == model_name
            assert payload['reasoning_effort'] == 'none'
            names = [t['function']['name'] for t in payload['tools']]
            assert len(names) == 10 and all(re.fullmatch(r'[A-Za-z0-9_-]{1,64}', n) for n in names)
            assert 'pricing_quote_order' in names
            assert 'catalog_search' in names and 'write_file' not in names
            if len(requests) == 1:
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'call-test', 'type': 'function', 'function': {
                        'name': 'catalog_search', 'arguments': '{"query":"máy lọc không khí"}'}}]}
            else:
                tool = next(m for m in payload['messages'] if m['role'] == 'tool')
                assert tool['tool_call_id'] == 'call-test'
                assert json.loads(tool['content']) == {'items': []}
                message = {'role': 'assistant', 'content': 'Chưa có kết quả.'}
            return httpx.Response(200, request=request, json={'id': 'offline',
                'object': 'chat.completion', 'created': 0, 'model': model_name,
                'choices': [{'index': 0, 'message': message,
                    'finish_reason': 'tool_calls' if len(requests) == 1 else 'stop'}]})
        with patch.object(httpx.AsyncClient, 'send', send):
            result = await build_agent(kind, model, business, 'Dùng catalog.search để tìm.').ainvoke(
                {'messages': [{'role': 'user', 'content': current['safe_text']}]})
        assert len(requests) == 2
        assert result['messages'][-1].content == 'Chưa có kết quả.'
        assert gateway.invoke_trusted.call_args.args[0] == 'catalog.search'
        assert current['tool_calls'][0]['name'] == 'catalog.search'
        assert 'catalog_search' in requests[0]['messages'][0]['content']
    asyncio.run(run())


def test_mapping_rejects_unknown_and_missing_names():
    from app.agent.implementations.tool_names import to_canonical_tool_name, validate_model_tool_names
    with pytest.raises(ValueError):
        to_canonical_tool_name('unknown_tool')
    with pytest.raises(ValueError):
        validate_model_tool_names(['catalog.search'])


def test_alias_does_not_bypass_purchase_gate():
    async def run():
        current = state()
        current['identity_status'] = 'unknown'
        gateway = AsyncMock()
        business = BusinessTools(gateway, current, 3, lambda: datetime.now(timezone.utc))
        tool = next(t for t in business.langchain_tools() if t.name == 'order_create')
        result = await tool.ainvoke({'sku': 'SKU-TEST', 'price_vnd': 100000})
        assert 'error' in result
        gateway.invoke_trusted.assert_not_called()
    asyncio.run(run())


def test_alias_collision_and_prompt_scope():
    from app.agent.implementations.tool_names import MODEL_TOOL_NAMES, validate_model_tool_names, model_tool_instructions
    with patch.dict(MODEL_TOOL_NAMES, {'order.create': 'catalog_search'}):
        with pytest.raises(ValueError):
            validate_model_tool_names(MODEL_TOOL_NAMES)
    assert model_tool_instructions('Use catalog.search; not xcatalog.search or catalog.search.extra') == (
        'Use catalog_search; not xcatalog.search or catalog.search.extra')


def test_middleware_blocks_unknown_and_exhausted_budget():
    from types import SimpleNamespace
    from app.agent.implementations.business_agent import BusinessOnlyMiddleware
    async def run():
        business = BusinessTools(AsyncMock(), {'tool_count': 3}, 3, lambda: None)
        middleware = BusinessOnlyMiddleware(business)
        handler = AsyncMock()
        request = SimpleNamespace(tools=business.langchain_tools(), override=lambda **kw: kw)
        await middleware.awrap_model_call(request, handler)
        assert handler.call_args.args[0]['tools'] == []
        blocked = await middleware.awrap_tool_call(SimpleNamespace(tool_call={'name':'write_file','id':'blocked'}), handler)
        assert blocked.tool_call_id == 'blocked' and handler.await_count == 1
    asyncio.run(run())


def test_runtime_graph_emits_health_and_preserves_canonical_observations():
    from test_deep_memory import FakeGateway, FakeMemory, turn
    from app.agent.harness.runtime import DeepHarnessRuntime
    from app.agent.harness.observability import capture_diagnostic_events
    from app.agent.harness.execution_diagnostics import execution_health
    async def run():
        llm = build_llm(Settings(_env_file=None, llm_api_key='offline-key', llm_model='gpt-6-luna',
                                 llm_base_url='https://offline.invalid/v1'))
        runtime = DeepHarnessRuntime(llm, FakeGateway(), FakeMemory())
        n = 0
        async def send(client, request, **kwargs):
            nonlocal n
            n += 1
            if n == 1:
                message = {'role':'assistant','content':None,'tool_calls':[{'id':'call-runtime','type':'function',
                    'function':{'name':'catalog_search','arguments':'{"query":"máy lọc"}'}}]}
            else:
                message = {'role':'assistant','content':'Dạ, em đã kiểm tra danh mục.'}
            return httpx.Response(200, request=request, json={'id':'offline','object':'chat.completion',
                'created':0,'model':'gpt-6-luna','choices':[{'index':0,'message':message,
                'finish_reason':'tool_calls' if n == 1 else 'stop'}]})
        request = turn('Xin chào')
        with patch.object(httpx.AsyncClient, 'send', send), capture_diagnostic_events() as events:
            await runtime.run(request)
        assert n == 2
        assert any(c['name']=='catalog.search' for c in runtime.state_for(request)['tool_calls'])
        assert execution_health([{'runtime_events':events}]) == 'healthy'
    asyncio.run(run())
