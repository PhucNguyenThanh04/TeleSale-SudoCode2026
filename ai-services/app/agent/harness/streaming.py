from contextvars import ContextVar
from contextlib import aclosing
import asyncio
import re

from app.agent.guardrails.checks import check_answer, check_grounding, mask_pii
from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence


active_stream = ContextVar('guarded_chat_stream', default=None)
active_turn_progress = ContextVar('turn_progress', default=None)
_INTERNAL = re.compile(r'<\/?(?:think|analysis|tool_call)|"(?:tool_calls|function_call)"', re.I)
_SENTENCE_BOUNDARY = re.compile(r'(?<!\d)[.!?](?!\d)\s+|\n+')
_TOOL_PREAMBLE = re.compile(
    r'(?i)\b(?:chờ em|đợi em|để em kiểm tra|để em tra|em đang kiểm tra|em sẽ kiểm tra)\b'
)
_PARTIAL_PII = re.compile(r'(?i)(?:\b0\d{5,}\b|@|\bsố điện thoại\b|\bemail\b|\bcccd\b|\bsố tài khoản\b)')


def internal_output(text):
    return text.lstrip().startswith(('{', '[', '<')) or bool(_INTERNAL.search(text))


def _chunk_text(chunk) -> str:
    if getattr(chunk, 'tool_calls', None) or getattr(chunk, 'tool_call_chunks', None):
        return ''
    content = getattr(chunk, 'content', None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(
            block.get('text', '') for block in content
            if isinstance(block, dict) and block.get('type') == 'text'
        )
    return ''


class GuardedStream:
    def __init__(self, publish=None, *, progressive: bool = False):
        self.publish = publish or self._enqueue
        self.progressive = progressive
        self.published = ''
        self.state = None
        self._queue = asyncio.Queue()
        self._pending = None
        self._disconnected = False
        self._sequence = 0
        self._buffer = ''
        self._message_id = None
        self._held = False
        self._finalized = False

    async def _enqueue(self, text):
        if self._disconnected:
            return False
        self._sequence += 1
        accepted = asyncio.get_running_loop().create_future()
        self._pending = accepted
        self._queue.put_nowait(({'event': 'delta', 'seq': self._sequence, 'text': text}, accepted))
        return await accepted

    def terminal(self, event):
        if not self._disconnected:
            self._queue.put_nowait((event, None))

    def disconnect(self):
        self._disconnected = True
        if self._pending is not None and not self._pending.done():
            self._pending.set_result(False)

    async def events(self):
        while True:
            event, accepted = await self._queue.get()
            if accepted is not None and not accepted.done():
                accepted.set_result(True)
            yield event
            if event['event'] != 'delta':
                return

    def _safe_progressive_prefix(self, candidate: str, state) -> bool:
        if not candidate.strip():
            return False
        if internal_output(candidate) or mask_pii(candidate) != candidate or _PARTIAL_PII.search(candidate):
            return False
        if not self.published and _TOOL_PREAMBLE.search(candidate):
            return False
        if state.get('tool_failed'):
            return False
        calls = build_commerce_evidence(state)
        cumulative = (self.published + candidate).strip()
        if check_grounding(cumulative, calls) is not None:
            return False
        named = resolve_claim_skus(state.get('safe_text', ''), calls)
        focus_sku = next(iter(named)) if len(named) == 1 else None
        _, reason = check_answer(cumulative, calls, state.get('safe_text', ''), focus_sku=focus_sku)
        return reason is None

    async def feed(self, chunk, state):
        self.state = state
        if not self.progressive or self._held or self._disconnected or self._finalized:
            return
        if getattr(chunk, 'tool_calls', None) or getattr(chunk, 'tool_call_chunks', None):
            self._buffer = ''
            return
        msg_id = getattr(chunk, 'id', None)
        if msg_id is not None and msg_id != self._message_id:
            self._buffer = ''
            self._message_id = msg_id
        delta = _chunk_text(chunk)
        if not delta:
            return
        self._buffer += delta
        if internal_output(self._buffer):
            self._held = True
            return
        while True:
            match = _SENTENCE_BOUNDARY.search(self._buffer)
            if match is None:
                break
            candidate = self._buffer[:match.end()]
            if not self._safe_progressive_prefix(candidate, state):
                self._held = True
                break
            await self._append(candidate)
            self._buffer = self._buffer[match.end():]

    async def _append(self, text):
        if text and await self.publish(text):
            self.published += text

    async def finish(self, verified, state):
        verified = mask_pii(verified.strip())
        if (not verified or internal_output(verified)
                or state.get('verified_answer') != verified):
            state['reply_error'] = 'agent_reply_unavailable'
            return self.published
        if self._finalized:
            return self.published
        self._finalized = True
        if not self.published:
            await self._append(verified)
        elif verified.startswith(self.published):
            await self._append(verified[len(self.published):])
        elif verified.startswith(self.published.rstrip()):
            tail = verified[len(self.published.rstrip()):]
            if tail:
                await self._append(tail)
        else:
            sep = '' if self.published.endswith('\n') else '\n'
            await self._append(sep + verified)
        return self.published


async def invoke_agent(agent, inputs, *, config, state):
    stream = active_stream.get()
    result = None
    async with aclosing(agent.astream(inputs, config=config, stream_mode=['messages', 'values'])) as events:
        async for mode, value in events:
            if mode == 'messages' and stream is not None:
                await stream.feed(value[0], state)
            elif mode == 'values':
                result = value
    if result is None:
        raise RuntimeError('agent_stream_incomplete')
    return result
