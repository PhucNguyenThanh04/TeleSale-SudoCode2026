import asyncio
import pytest
from test_policy_embedding import runtime_config


def test_retry_is_bounded_and_breaker_recovers_with_one_probe():
    from app.mcp_servers.mcp_knowledge.services.dependencies import PolicyDependencies, PolicyUnavailable
    async def run():
        now=[0.]
        dependencies=PolicyDependencies(runtime_config(), clock=lambda: now[0])
        attempts=[]
        async def broken():
            attempts.append(1)
            raise ConnectionError('not logged')
        with pytest.raises(ConnectionError):
            await dependencies.call_dependency('qdrant', broken, deadline=2)
        assert len(attempts)==2
        with pytest.raises(PolicyUnavailable):
            await dependencies.call_dependency('qdrant', broken, deadline=2)
        assert len(attempts)==2
        now[0]=1
        async def recovered():
            return 'ready'
        assert await dependencies.call_dependency('qdrant', recovered, deadline=2)=='ready'
    asyncio.run(run())


def test_data_and_oom_failures_are_not_retried():
    from app.mcp_servers.mcp_knowledge.services.dependencies import PolicyDependencies
    async def run():
        for exception in (ValueError('hash mismatch'), MemoryError('oom')):
            attempts=[]
            async def broken():
                attempts.append(1)
                raise exception
            with pytest.raises(type(exception)):
                await PolicyDependencies(runtime_config()).call_dependency('postgres', broken, deadline=__import__('time').monotonic()+1)
            assert len(attempts)==1
    asyncio.run(run())
