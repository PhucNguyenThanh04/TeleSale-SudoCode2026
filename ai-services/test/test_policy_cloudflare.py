import asyncio
import json
import time
import httpx
import pytest
from test_policy_embedding import runtime_config


def client_for(handler, **kwargs):
    from app.mcp_servers.mcp_knowledge.services.cloudflare import CloudflareEmbeddingClient
    return CloudflareEmbeddingClient(runtime_config(batch_size=2), account_id='a'*32, token='fake-secret',
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kwargs)


def test_dense_response_is_ordered_and_validated():
    async def run():
        def handler(request):
            assert request.url.path.endswith('/ai/run/@cf/baai/bge-m3')
            assert json.loads(request.content)['text'] == ['đổi trả', 'bảo hành']
            return httpx.Response(200, json={'success':True, 'result':{'shape':[2,2],'data':[[3,4],[1,0]]}})
        client = client_for(handler)
        assert await client.embed(['đổi trả','bảo hành'],deadline=time.monotonic()+1) == [[3,4],[1,0]]
        await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('body', [
    {'success':True,'result':{'data':[[1]]}},
    {'success':True,'result':{'data':[[0,0]]}},
    {'success':True,'result':{'data':[[1,0],[1,0]]}},
    {'success':False,'result':{'data':[[1,0]]}},
])
def test_invalid_response_fails_closed(body):
    async def run():
        from app.mcp_servers.mcp_knowledge.services.cloudflare import PolicyProviderError
        client=client_for(lambda r:httpx.Response(200,json=body))
        with pytest.raises(PolicyProviderError):
            await client.embed(['query'],deadline=time.monotonic()+1)
        await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('status,message,reason,retry',[
    (429,'Daily free allocation exceeded','quota_exhausted',False),
    (429,'Rate limit exceeded','rate_limited',True),
    (429,'unknown','provider_error',False),
    (401,'Unauthorized','auth',False),
    (500,'server error','provider_error',True),
])
def test_provider_error_classification_and_no_adapter_retry(status,message,reason,retry):
    async def run():
        from app.mcp_servers.mcp_knowledge.services.cloudflare import PolicyProviderError
        calls=[]
        def handler(r):
            calls.append(r)
            return httpx.Response(status,json={'success':False,'errors':[{'code':1234,'message':message}]},headers={'Retry-After':'0'})
        client=client_for(handler)
        with pytest.raises(PolicyProviderError) as caught:
            await client.embed(['query'],deadline=time.monotonic()+1)
        assert caught.value.reason == reason
        assert caught.value.retryable == retry
        assert len(calls)==1
        assert 'fake-secret' not in str(caught.value)
        await client.close()
    asyncio.run(run())


def test_deadline_expired_sends_no_http():
    async def run():
        client=client_for(lambda r:pytest.fail('Unexpected HTTP call'))
        with pytest.raises(TimeoutError):
            await client.embed(['query'],deadline=time.monotonic()-1)
        await client.close()
    asyncio.run(run())


def test_documented_quota_code_is_recognized_without_message():
    async def run():
        from app.mcp_servers.mcp_knowledge.services.cloudflare import PolicyProviderError
        client=client_for(lambda r:httpx.Response(429,json={'errors':[{'code':3036}]}))
        with pytest.raises(PolicyProviderError) as caught:
            await client.embed(['query'],deadline=time.monotonic()+1)
        assert caught.value.reason=='quota_exhausted' and not caught.value.retryable
        await client.close()
    asyncio.run(run())


def test_provider_retry_is_bounded_and_quota_breaker_keeps_reason():
    from app.mcp_servers.mcp_knowledge.services.dependencies import PolicyDependencies
    from app.mcp_servers.mcp_knowledge.services.cloudflare import PolicyProviderError
    async def run():
        dependency=PolicyDependencies(runtime_config())
        calls=0
        async def transient():
            nonlocal calls
            calls+=1
            raise PolicyProviderError('provider_error',status=503,retryable=True)
        with pytest.raises(PolicyProviderError):
            await dependency.call_dependency('cloudflare',transient,deadline=time.monotonic()+2)
        assert calls==2
        dependency=PolicyDependencies(runtime_config())
        calls=0
        async def quota():
            nonlocal calls
            calls+=1
            raise PolicyProviderError('quota_exhausted',status=429,provider_code='3036')
        for _ in range(2):
            with pytest.raises(PolicyProviderError) as caught:
                await dependency.call_dependency('cloudflare',quota,deadline=time.monotonic()+2)
            assert caught.value.reason=='quota_exhausted'
        assert calls==1
    asyncio.run(run())
