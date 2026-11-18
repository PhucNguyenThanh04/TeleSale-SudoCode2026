"""Turn-local publication of checked answer units, not raw model tokens."""
from contextvars import ContextVar
from contextlib import aclosing
import asyncio
import re

from langchain_core.messages import AIMessage, AIMessageChunk

from app.agent.guardrails.checks import FALLBACK, mask_pii


active_stream = ContextVar('guarded_chat_stream', default=None)
_BOUNDARY = re.compile(r'(?<!\d)[.!?](?=\s)|\n\n')
_HELD = re.compile(r'bao hanh|chinh sach|\bdoi\b|tra hang|hoan tien|cccd|tai khoan|mat khau|'
                   r'chuyen may|goi lai|\bhen\b|xoa du lieu|so dien thoai|\bsdt\b|\bstk\b|\bemail\b|dia chi|'
                   r'lam thu tuc|cap nhat|xac nhan|dong y|\b(?:ok(?:ay)?|vang|u|uh)\b')
_INTERNAL = re.compile(r'<\/?(?:think|analysis|tool_call)|"(?:tool_calls|function_call)"', re.I)
_PROGRESS = re.compile(r'dang (?:xu ly|kiem tra|tra cuu)|xin cho|cho mot chut|da nhan yeu cau')


class GuardedStream:
    def __init__(self, publish=None):
        self.publish = publish or self._enqueue
        self.published = ''
        self.state = None
        self._message_id = None
        self._buffer = ''
        self._tool_message = False
        self._checked_boundary = 0
        self._queue = asyncio.Queue()
        self._pending = None
        self._disconnected = False
        self._sequence = 0

    async def _enqueue(self, text):
        if self._disconnected:
            return False
        self._sequence += 1
        accepted = asyncio.get_running_loop().create_future()
        self._pending = accepted
        self._queue.put_nowait(({'event': 'delta', 'seq': self._sequence, 'text': text}, accepted))
        # One pending delta at a time; the model cannot outrun the consumer.
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

    async def feed(self, chunk, state):
        from app.agent.harness.agent_nodes import _task_answer_complete
        from app.mcp_servers.mcp_shared.commerce_rules import _search_text
        from app.mcp_servers.mcp_shared.consultation import derive_consultation
        from app.mcp_servers.mcp_shared.consultation_followup import followup_task

        if not isinstance(chunk, AIMessageChunk):
            return
        self.state = state
        if chunk.id != self._message_id:
            self._message_id, self._buffer, self._tool_message = chunk.id, '', False
            self._checked_boundary = 0
        self._tool_message |= bool(chunk.tool_call_chunks or chunk.tool_calls)
        if self._tool_message:
            return
        content = chunk.content
        if isinstance(content, list):
            content = ''.join(block.get('text', '') for block in content
                              if isinstance(block, dict) and block.get('type') == 'text')
        if not isinstance(content, str):
            return
        self._buffer += content
        # A tool call can arrive after text chunks in the same model message.
        # Wait for a final stop before allowing any customer-visible output.
        if chunk.response_metadata.get('finish_reason') != 'stop':
            return
        if not _task_answer_complete(self._buffer.strip(), state):
            return
        boundaries = list(_BOUNDARY.finditer(self._buffer))
        if not boundaries:
            return
        boundary = boundaries[-1].end()
        if boundary == self._checked_boundary:
            return
        self._checked_boundary = boundary
        candidate = self._buffer[:boundary].strip()
        folded = _search_text(state['safe_text'] + ' ' + candidate)
        if (followup_task(state).kind == 'policy' or derive_consultation(state).purchase_intent
                or any(call.get('name') in {'order.create', 'order.update', 'schedule.callback', 'handoff.transfer'}
                       for call in state.get('tool_calls', []))
                or _HELD.search(folded) or _PROGRESS.search(_search_text(candidate))
                or candidate.startswith(('{', '[', '<')) or _INTERNAL.search(candidate)
                or mask_pii(candidate) != candidate
                or not _task_answer_complete(candidate, state)):
            return
        if candidate.startswith(self.published):
            await self._append(candidate[len(self.published):])

    async def _append(self, text):
        if text and await self.publish(text):
            self.published += text

    async def finish(self, verified, state):
        from app.agent.harness.agent_nodes import _task_answer_complete

        verified = mask_pii(verified.strip())
        if verified.startswith(('{', '[')) or _INTERNAL.search(verified):
            verified = FALLBACK
        if not self.published:
            await self._append(verified)
        elif verified.startswith(self.published):
            # The whole response already passed the final graph verifier.
            await self._append(verified[len(self.published):])
        elif verified != FALLBACK:
            combined = self.published + '\n\n' + verified
            if _task_answer_complete(combined, state):
                await self._append(combined[len(self.published):])
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
                if stream is not None and stream.published:
                    last = value.get('messages', [])[-1:]
                    if last and isinstance(last[0], AIMessage) and last[0].tool_calls:
                        # A complete checked answer was published; end the business
                        # phase instead of asking the model to retry refused tools.
                        return {'messages': [AIMessage(content=stream.published)]}
    if result is None:
        raise RuntimeError('agent_stream_incomplete')
    return result
