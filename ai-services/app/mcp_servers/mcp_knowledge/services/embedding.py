"""One bounded encoder worker; cancellation never releases a running GPU job."""
import asyncio
import math
import time

from app.knowledge.schemas import HybridVector


class PolicyInputError(ValueError):
    pass


class PolicyOverloaded(RuntimeError):
    pass


class FlagBackend:
    def __init__(self, config):
        # Only an already cached immutable snapshot is loaded. No implicit downloads.
        import re
        if not re.fullmatch(r'[0-9a-f]{40}', config.model_revision):
            raise ValueError('Immutable model commit revision required')
        from huggingface_hub import snapshot_download
        from FlagEmbedding import BGEM3FlagModel
        import torch
        if not config.device.startswith('cuda') or not torch.cuda.is_available():
            raise RuntimeError('Configured CUDA device unavailable')
        if config.model_revision != config.tokenizer_revision:
            raise ValueError('Tokenizer and model revisions must match')
        path = snapshot_download(config.model_name, revision=config.model_revision, local_files_only=True)
        self.config = config
        self.model = BGEM3FlagModel(path, devices=[config.device], use_fp16=True,
            normalize_embeddings=True, batch_size=config.batch_size,
            query_max_length=config.max_tokens, passage_max_length=config.max_tokens,
            return_dense=True, return_sparse=True, return_colbert_vecs=False)

    def token_count(self, text):
        return len(self.model.tokenizer(text, truncation=False)['input_ids'])

    def encode(self, text):
        output = self.model.encode([text], batch_size=self.config.batch_size,
            max_length=self.config.max_tokens, return_dense=True, return_sparse=True,
            return_colbert_vecs=False)
        sparse = output['lexical_weights'][0]
        pairs = sorted((int(key), float(value)) for key, value in sparse.items() if value > 0)
        return HybridVector(dense=output['dense_vecs'][0].tolist(),
            sparse_indices=[key for key, _ in pairs], sparse_values=[value for _, value in pairs])


class PolicyEncoder:
    def __init__(self, config, backend=None, *, clock=time.monotonic):
        self.config = config
        self.backend = backend
        self.clock = clock
        self.ready = False
        self._queue = asyncio.Queue(maxsize=config.queue_capacity)
        self._worker = None
        self._starting = asyncio.Lock()

    def _validate(self, value):
        value = HybridVector.model_validate(value)
        if len(value.dense) != self.config.dimension or not all(math.isfinite(v) for v in value.dense):
            raise ValueError('Invalid dense vector')
        if (len(value.sparse_indices) != len(value.sparse_values)
                or len(set(value.sparse_indices)) != len(value.sparse_indices)
                or any(i < 0 for i in value.sparse_indices)
                or any(not math.isfinite(v) or v <= 0 for v in value.sparse_values)):
            raise ValueError('Invalid sparse vector')
        norm = math.sqrt(sum(v*v for v in value.dense))
        if norm == 0:
            raise ValueError('Zero dense vector')
        return value.model_copy(update={'dense': [v/norm for v in value.dense]})

    async def start(self):
        async with self._starting:
            if self.ready:
                return
            if self.backend is None:
                self.backend = await asyncio.to_thread(FlagBackend, self.config)
            for _ in range(3):
                text = 'Kiểm tra tra cứu chính sách.'
                count = await asyncio.to_thread(self.backend.token_count, self.config.prefix+text)
                if count > self.config.max_tokens:
                    raise ValueError('Warmup exceeds token limit')
                self._validate(await asyncio.to_thread(self.backend.encode, self.config.prefix+text))
            self._worker = asyncio.create_task(self._run())
            self.ready = True

    async def encode(self, text, *, deadline):
        if not self.ready:
            raise RuntimeError('Encoder not ready')
        if self.clock() >= deadline:
            raise TimeoutError('Encode deadline')
        future = asyncio.get_running_loop().create_future()
        # Consume late exceptions even when the waiter has timed out.
        future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        try:
            self._queue.put_nowait((self.config.prefix+text, deadline, future))
        except asyncio.QueueFull:
            raise PolicyOverloaded('Encode queue full') from None
        try:
            return await asyncio.wait_for(asyncio.shield(future), max(0, deadline-self.clock()))
        except (TimeoutError, asyncio.CancelledError):
            future.cancel()
            raise

    async def _run(self):
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return
                text, deadline, future = item
                if future.cancelled():
                    continue
                try:
                    if self.clock() >= deadline:
                        raise TimeoutError('Queued encode expired')
                    count = await asyncio.to_thread(self.backend.token_count, text)
                    if count > self.config.max_tokens:
                        raise PolicyInputError('Input exceeds token limit')
                    if future.cancelled():
                        continue
                    if self.clock() >= deadline:
                        raise TimeoutError('Encode expired before inference')
                    value = self._validate(await asyncio.to_thread(self.backend.encode, text))
                    if not future.done():
                        future.set_result(value)
                except Exception as exc:
                    if not future.done():
                        future.set_exception(exc)
            finally:
                self._queue.task_done()

    async def close(self):
        self.ready = False
        if self._worker:
            await self._queue.put(None)
            await self._worker
            self._worker = None
