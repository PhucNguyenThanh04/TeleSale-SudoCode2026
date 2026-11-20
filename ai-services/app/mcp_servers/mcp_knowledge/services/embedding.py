import asyncio
import hashlib
import math
import time

from app.mcp_servers.mcp_shared.pii import mask_pii
from app.mcp_servers.mcp_knowledge.services.cloudflare import CloudflareEmbeddingClient
from app.mcp_servers.mcp_knowledge.services.dependencies import PolicyDependencies


class PolicyInputError(ValueError):
    pass


class PolicyOverloaded(RuntimeError):
    pass


def load_tokenizer(config):
    from tokenizers import Tokenizer
    data = config.tokenizer_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != config.tokenizer_sha256:
        raise ValueError('Tokenizer asset hash mismatch')
    tokenizer = Tokenizer.from_str(data.decode('utf-8'))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


class CloudflareBackend:
    def __init__(self, config):
        from app.configs import get_settings
        settings = get_settings()
        self.tokenizer = load_tokenizer(config)
        self.client = CloudflareEmbeddingClient(config, account_id=settings.cloudflare_account_id,
            token=settings.cloudflare_api_token.get_secret_value() if settings.cloudflare_api_token else None)

    def token_count(self, text):
        return len(self.tokenizer.encode(text).ids)

    async def encode(self, text, *, deadline):
        return (await self.client.embed([text], deadline=deadline))[0]

    async def close(self):
        await self.client.close()


class PolicyEncoder:
    def __init__(self, config, backend=None, *, clock=time.monotonic):
        self.config, self.backend, self.clock = config, backend, clock
        self.ready = False
        self.dependencies = PolicyDependencies(config, clock=clock)
        self._queue = asyncio.Queue(maxsize=config.queue_capacity)
        self._workers = []
        self._starting = asyncio.Lock()

    def _validate(self, value):
        if (not isinstance(value, list) or len(value) != self.config.dimension
                or any(type(v) not in (float, int) or not math.isfinite(v) for v in value)):
            raise ValueError('Invalid dense vector')
        norm = math.sqrt(sum(v*v for v in value))
        if not math.isfinite(norm) or norm == 0:
            raise ValueError('Invalid dense norm')
        return [v/norm for v in value]

    async def start(self):
        async with self._starting:
            if self.ready:
                return
            if self.backend is None:
                self.backend = CloudflareBackend(self.config)
            self._workers = [asyncio.create_task(self._run()) for _ in range(self.config.http_concurrency)]
            self.ready = True

    async def encode(self, text, *, deadline):
        if not self.ready:
            raise RuntimeError('Encoder not ready')
        if self.clock() >= deadline:
            raise TimeoutError('Encode deadline')
        text = self.config.prefix + mask_pii(text)
        if self.backend.token_count(text) > self.config.max_tokens:
            raise PolicyInputError('Input exceeds token limit')
        future = asyncio.get_running_loop().create_future()
        try:
            self._queue.put_nowait((text, deadline, future))
        except asyncio.QueueFull:
            raise PolicyOverloaded('Encode queue full') from None
        try:
            return await asyncio.wait_for(future, max(0, deadline-self.clock()))
        finally:
            if not future.done():
                future.cancel()

    async def _execute(self, text, deadline):
        dense = await self.dependencies.call_dependency('cloudflare',
            lambda: self.backend.encode(text, deadline=deadline), deadline=deadline)
        return self._validate(dense)

    async def _run(self):
        while True:
            text, deadline, future = await self._queue.get()
            job = None
            try:
                if future.cancelled():
                    continue
                if self.clock() >= deadline:
                    raise TimeoutError('Queued encode expired')
                job = asyncio.create_task(self._execute(text, deadline))
                def cancel_job(done, task=job):
                    if done.cancelled():
                        task.cancel()
                future.add_done_callback(cancel_job)
                try:
                    result = await job
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                    continue
                if not future.done():
                    future.set_result(result)
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)
            finally:
                if job and not job.done():
                    job.cancel()
                if not future.done():
                    future.cancel()
                self._queue.task_done()

    async def close(self):
        self.ready = False
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []
        while not self._queue.empty():
            _, _, future = self._queue.get_nowait()
            future.cancel()
            self._queue.task_done()
        if self.backend:
            await self.backend.close()
