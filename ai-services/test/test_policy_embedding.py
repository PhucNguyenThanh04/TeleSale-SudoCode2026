import asyncio
import time
import pytest
from app.knowledge.schemas import HybridVector
from app.mcp_servers.mcp_knowledge.schemas import PolicyRuntimeConfig


def runtime_config(**changes):
    return PolicyRuntimeConfig.model_validate(dict(tokenizer_revision='test-revision', tokenizer_sha256='a'*64,
        max_tokens=32, dimension=2, dense_candidates=30, sparse_candidates=30, hard_limit=10,
        dense_threshold=.4, relevance_verified=True, queue_capacity=1,
        deadline_seconds=1, dependency_timeout_seconds=.5, breaker_failures=2, breaker_cooldown_seconds=.05) | changes)


class Backend:
    def __init__(self):
        self.calls = []
    def token_count(self, text):
        return len(text.split()) + 2
    async def encode(self, text, *, deadline):
        self.calls.append(text)
        return [1., 0.]
    async def close(self):
        pass


def test_encoder_start_has_no_network_calls_and_never_truncates():
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    async def run():
        backend = Backend()
        encoder = PolicyEncoder(runtime_config(), backend)
        await encoder.start()
        assert not backend.calls and encoder.ready
        with pytest.raises(ValueError, match='token'):
            await encoder.encode('word '*40,deadline=time.monotonic()+1)
        assert not backend.calls
        assert await encoder.encode('valid',deadline=time.monotonic()+1) == [1,0]
        await encoder.close()
    asyncio.run(run())


def test_timeout_cancels_http_and_does_not_leak_worker():
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder, PolicyOverloaded
    class Blocking(Backend):
        def __init__(self):
            super().__init__();self.started=asyncio.Event();self.cancelled=False
        async def encode(self,text,*,deadline):
            if text == 'slow':
                self.started.set()
                try: await asyncio.Event().wait()
                finally: self.cancelled=True
            return await super().encode(text,deadline=deadline)
    async def run():
        backend=Blocking();encoder=PolicyEncoder(runtime_config(),backend)
        await encoder.start()
        slow=asyncio.create_task(encoder.encode('slow',deadline=time.monotonic()+.04))
        await backend.started.wait()
        queued=asyncio.create_task(encoder.encode('expired',deadline=time.monotonic()+.01))
        await asyncio.sleep(.002)
        with pytest.raises(PolicyOverloaded):
            await encoder.encode('overflow',deadline=time.monotonic()+1)
        with pytest.raises(TimeoutError): await queued
        with pytest.raises(TimeoutError): await slow
        assert await encoder.encode('next',deadline=time.monotonic()+1)==[1,0]
        assert backend.cancelled and 'expired' not in backend.calls
        await encoder.close()
    asyncio.run(run())


def test_invalid_vectors_fail_closed():
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    class Invalid(Backend):
        async def encode(self,text,*,deadline): return [float('nan'),0]
    async def run():
        encoder=PolicyEncoder(runtime_config(),Invalid());await encoder.start()
        with pytest.raises(ValueError): await encoder.encode('text',deadline=time.monotonic()+1)
        await encoder.close()
    asyncio.run(run())


def test_encoder_masks_pii_preserves_sku_and_normalizes():
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    class Dense(Backend):
        async def encode(self,text,*,deadline):
            self.calls.append(text);return [3,4]
    async def run():
        backend=Dense();encoder=PolicyEncoder(runtime_config(),backend);await encoder.start()
        assert await encoder.encode('SKU-123 2026-09-20 test@example.com 0912345678',deadline=time.monotonic()+1)==[.6,.8]
        assert 'test@example.com' not in backend.calls[0] and '0912345678' not in backend.calls[0]
        assert 'SKU-123' in backend.calls[0] and '2026-09-20' in backend.calls[0]
        await encoder.close()
    asyncio.run(run())


def test_bundled_tokenizer_matches_runtime_hash_without_download():
    from pathlib import Path
    from app.mcp_servers.mcp_knowledge.services.embedding import load_tokenizer
    config=PolicyRuntimeConfig.model_validate_json((Path(__file__).resolve().parents[2]/'config/policy-runtime.json').read_text())
    tokenizer=load_tokenizer(config)
    assert len(tokenizer.encode('đổi trả bảo hành').ids)>2
    alternate=config.model_copy(update={'tokenizer_path':Path('/different/container/path')})
    assert config.fingerprint()==alternate.fingerprint()
    assert config.model_dump(mode='json')==alternate.model_dump(mode='json')
