import asyncio
import threading
import time
import pytest
from app.knowledge.schemas import HybridVector
from app.mcp_servers.mcp_knowledge.schemas import PolicyRuntimeConfig


def runtime_config(**changes):
    return PolicyRuntimeConfig.model_validate(dict(model_revision='test-revision', tokenizer_revision='test-revision',
        max_tokens=32, dimension=2, dense_candidates=30, sparse_candidates=30, hard_limit=10,
        dense_threshold=.4, sparse_threshold=.1, relevance_verified=True, queue_capacity=1,
        deadline_seconds=1, dependency_timeout_seconds=.5, breaker_failures=2, breaker_cooldown_seconds=.05) | changes)


class Backend:
    def __init__(self):
        self.calls = []
    def token_count(self, text):
        return len(text.split()) + 2
    def encode(self, text):
        self.calls.append(text)
        return HybridVector(dense=[1., 0.], sparse_indices=[4], sparse_values=[1.])


def test_warmup_is_exactly_three_and_token_limit_does_not_truncate():
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    async def run():
        backend = Backend()
        encoder = PolicyEncoder(runtime_config(), backend)
        await encoder.start()
        assert len(backend.calls) == 3 and encoder.ready
        with pytest.raises(ValueError, match='token'):
            await encoder.encode('word ' * 40, deadline=time.monotonic()+1)
        assert len(backend.calls) == 3
        await encoder.close()
    asyncio.run(run())


def test_warmup_failure_never_becomes_ready():
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    class Broken(Backend):
        def encode(self, text):
            raise RuntimeError('broken')
    async def run():
        encoder = PolicyEncoder(runtime_config(), Broken())
        with pytest.raises(RuntimeError):
            await encoder.start()
        assert not encoder.ready
        await encoder.close()
    asyncio.run(run())


def test_timeout_keeps_gpu_worker_until_encode_finishes():
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder, PolicyOverloaded
    class Blocking(Backend):
        started = threading.Event()
        release = threading.Event()
        def encode(self, text):
            if text == 'slow':
                self.started.set()
                self.release.wait(1)
            return super().encode(text)
    async def run():
        backend = Blocking()
        encoder = PolicyEncoder(runtime_config(), backend)
        await encoder.start()
        slow = asyncio.create_task(encoder.encode('slow', deadline=time.monotonic()+.03))
        while not backend.started.is_set():
            await asyncio.sleep(.001)
        expired = asyncio.create_task(encoder.encode('expired', deadline=time.monotonic()+.01))
        await asyncio.sleep(.002)
        with pytest.raises(PolicyOverloaded):
            await encoder.encode('overflow', deadline=time.monotonic()+1)
        with pytest.raises(TimeoutError):
            await expired
        with pytest.raises(TimeoutError):
            await slow
        assert 'expired' not in backend.calls
        backend.release.set()
        await encoder.close()
        assert 'expired' not in backend.calls
    asyncio.run(run())


def test_invalid_vectors_fail_closed():
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    class Invalid(Backend):
        def encode(self, text):
            return HybridVector(dense=[float('nan'),0], sparse_indices=[1], sparse_values=[1])
    async def run():
        encoder = PolicyEncoder(runtime_config(), Invalid())
        with pytest.raises(ValueError):
            await encoder.start()
        assert not encoder.ready
        await encoder.close()
    asyncio.run(run())
