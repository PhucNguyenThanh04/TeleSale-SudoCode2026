from contextvars import ContextVar
from contextlib import aclosing
import asyncio
import re

from app.agent.guardrails.checks import mask_pii


active_stream = ContextVar('guarded_chat_stream', default=None)
active_turn_progress = ContextVar('turn_progress', default=None)
_INTERNAL = re.compile(r'<\/?(?:think|analysis|tool_call)|"(?:tool_calls|function_call)"', re.I)


def internal_output(text):
    return text.lstrip().startswith(('{', '[', '<')) or bool(_INTERNAL.search(text))



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

    async def feed(self, chunk, state):
        self.state = state

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
