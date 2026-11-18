"""Real graph streaming with token barriers, no services or wall-clock benchmarks."""
import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from unittest.mock import AsyncMock, patch
from langchain_core.outputs import ChatGenerationChunk

from app.agent.harness.runtime import AgentHarnessRuntime
from test_deep_memory import FakeToolModel, FakeMemory, FakeGateway, turn


class StreamingModel(FakeToolModel):
    release: Any = None
    started: Any = None
    calls: int = 0

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.started.set()
        yield ChatGenerationChunk(message=AIMessageChunk(
            content='Em có thể tư vấn các sản phẩm trong danh mục. '))
        await self.release.wait()
        yield ChatGenerationChunk(message=AIMessageChunk(content='Mình muốn tìm hiểu loại sản phẩm nào ạ?',
            response_metadata={'finish_reason':'stop'}))


def setup():
    model = StreamingModel(replies=[], release=asyncio.Event(), started=asyncio.Event())
    memory = FakeMemory()
    runtime = AgentHarnessRuntime(model, FakeGateway(), memory)
    return model, memory, runtime


@pytest.mark.parametrize('delivery_mode', ['text', 'voice'])
def test_collected_reply_uses_the_same_streaming_model_core(delivery_mode):
    class StreamOnlyModel(StreamingModel):
        def _generate(self, *args, **kwargs):
            raise AssertionError('A second, nonstreaming model path must not run')

    async def run():
        model = StreamOnlyModel(replies=[], release=asyncio.Event(), started=asyncio.Event())
        model.release.set()
        memory = FakeMemory()
        runtime = AgentHarnessRuntime(model, FakeGateway(), memory)
        request = turn('Em có thể hỗ trợ gì?').model_copy(update={'delivery_mode': delivery_mode})
        try:
            response = await runtime.run(request)
            assert model.calls == 1
            assert response.agent_text.startswith('Em có thể tư vấn')
            assert response.memory_update.turn_saved is (delivery_mode == 'text')
            if delivery_mode == 'voice':
                assert not memory.turns
        finally:
            await runtime.close()
    asyncio.run(run())


def test_delta_waits_for_complete_message_and_done_follows_persistence():
    async def run():
        model, memory, runtime = setup()
        request = turn('Em có thể hỗ trợ gì?')
        stream = runtime.stream(request)
        try:
            pending = asyncio.create_task(anext(stream))
            await asyncio.wait_for(model.started.wait(), 3)
            assert not pending.done() and not memory.turns
            model.release.set()
            first = await asyncio.wait_for(pending, 3)
            assert first['event'] == 'delta' and first['text']
            rest = [event async for event in stream]
            assert rest[-1]['event'] == 'done'
            answer = first['text'] + ''.join(e['text'] for e in rest if e['event'] == 'delta')
            assert rest[-1]['agent_text'] == answer
            assert memory.turns[str(request.session_id)][0]['agent'] == answer
            assert rest[-1]['memory_update']['turn_saved']
            assert model.calls == 1
        finally:
            model.release.set()
            await stream.aclose()
            await runtime.close()
    asyncio.run(run())


def test_disconnect_saves_only_emitted_prefix_and_retry_does_not_run_model_again():
    async def run():
        model, memory, runtime = setup()
        request = turn('Em có thể hỗ trợ gì?')
        stream = runtime.stream(request)
        try:
            model.release.set()
            first = await asyncio.wait_for(anext(stream), 3)
            await stream.aclose()
            model.release.set()
            await runtime.close()
            saved = memory.turns[str(request.session_id)]
            assert len(saved) == 1 and saved[0]['agent'] == first['text']
            replay = [event async for event in runtime.stream(request)]
            assert replay[-1]['event'] == 'done'
            assert model.calls == 1 and len(saved) == 1
        finally:
            model.release.set()
            await runtime.close()
    asyncio.run(run())


def test_cancel_before_any_delta_saves_customer_without_unemitted_assistant_text():
    async def run():
        model, memory, runtime = setup()
        request = turn('Chính sách bảo hành thế nào?')
        stream = runtime.stream(request)
        consumer = asyncio.create_task(anext(stream))
        try:
            await asyncio.wait_for(model.started.wait(), 3)
            assert not consumer.done()
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await consumer
            model.release.set()
            await runtime.close()
            assert memory.turns[str(request.session_id)][0]['agent'] == ''
        finally:
            model.release.set()
            await stream.aclose()
            await runtime.close()
    asyncio.run(run())


def test_streaming_voice_is_rejected_before_generation():
    async def run():
        model, _, runtime = setup()
        with pytest.raises(ValueError):
            await anext(runtime.stream(turn('Xin chào').model_copy(update={'delivery_mode': 'voice'})))
        assert model.calls == 0
        await runtime.close()
    asyncio.run(run())


def test_streaming_cannot_run_with_answer_guardrails_disabled():
    async def run():
        model, _, runtime = setup()
        runtime.nodes.guardrails_enabled = False
        with pytest.raises(ValueError):
            await anext(runtime.stream(turn('Xin tư vấn')))
        assert model.calls == 0
        await runtime.close()
    asyncio.run(run())


def test_later_business_tool_cannot_change_published_evidence_or_write():
    from app.agent.harness.streaming import GuardedStream, active_stream
    from app.agent.implementations.business_agent import BusinessTools
    from test_commerce_evidence import state
    from unittest.mock import AsyncMock

    async def run():
        stream = GuardedStream(AsyncMock(return_value=True))
        stream.published = 'Aster có giá 900.000đ.'
        gateway = FakeGateway()
        token = active_stream.set(stream)
        try:
            business = BusinessTools(gateway, state('Giá Aster?'), 6, None)
            assert 'error' in await business.invoke('pricing.get_quote', {'sku': 'SKU-ASTER'})
            assert 'error' in await business.invoke('order.create', {'sku': 'SKU-ASTER'})
            assert gateway.calls == []
        finally:
            active_stream.reset(token)
    asyncio.run(run())


def test_openai_sse_waits_for_stop_before_publication():
    import json
    import httpx
    from langchain_openai import ChatOpenAI

    async def run():
        release = asyncio.Event()
        calls = []
        started = asyncio.Event()

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                def frame(text, finish=None):
                    return ('data: ' + json.dumps({'id':'offline-completion', 'object':'chat.completion.chunk',
                        'created':1, 'model':'offline', 'choices':[{'index':0,
                            'delta':{'role':'assistant', 'content':text}, 'finish_reason':finish}]}) + '\n\n').encode()
                yield frame('Em có thể tư vấn sản phẩm trong danh mục. ')
                started.set()
                await release.wait()
                yield frame('Mình cần tư vấn loại nào ạ?', 'stop')
                yield b'data: [DONE]\n\n'

        async def handler(request):
            payload = json.loads(request.content)
            assert payload['stream'] is True
            calls.append(payload)
            return httpx.Response(200, stream=Body(), headers={'content-type':'text/event-stream'})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            model = ChatOpenAI(model='offline', api_key='offline', base_url='https://offline.invalid/v1',
                               http_async_client=http)
            memory = FakeMemory()
            runtime = AgentHarnessRuntime(model, FakeGateway(), memory)
            request = turn('Em có thể hỗ trợ gì?')
            stream = runtime.stream(request)
            try:
                pending = asyncio.create_task(anext(stream))
                await asyncio.wait_for(started.wait(), 3)
                assert not pending.done()
                release.set()
                first = await asyncio.wait_for(pending, 3)
                assert first['event'] == 'delta'
                rest = [e async for e in stream]
                assert rest[-1]['event'] == 'done' and len(calls) == 1
                assert memory.turns[str(request.session_id)][0]['agent'] == rest[-1]['agent_text']
            finally:
                release.set()
                await stream.aclose()
                await runtime.close()
    asyncio.run(run())


def test_disconnect_during_callback_settles_once_and_zero_delivery_retry_is_explicit():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class Gateway(FakeGateway):
            async def invoke(self, name, args):
                if name == 'schedule.callback':
                    self.calls.append((name, args))
                    entered.set()
                    await release.wait()
                    return {'callback_id':'CB-STREAM', 'callback_at':args['callback_at']}
                return await super().invoke(name, args)
        gateway, memory = Gateway(), FakeMemory()
        model = FakeToolModel(replies=[AIMessage(content='', tool_calls=[{
            'name':'schedule_callback','args':{'callback_at':'2026-10-16T10:00'},'id':'callback-1'}]),
            AIMessage(content='Em đã đặt lịch gọi lại cho mình.')])
        runtime = AgentHarnessRuntime(model, gateway, memory)
        request = turn('Em đặt lịch gọi lại cho anh ngày mai lúc 10 giờ nhé.')
        stream = runtime.stream(request)
        with patch('app.agent.harness.authorization.authorize_write', AsyncMock(return_value=True)):
            consumer = asyncio.create_task(anext(stream))
            await asyncio.wait_for(entered.wait(), 3)
        try:
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError): await consumer
            release.set()
            await runtime.close()
            assert memory.turns[str(request.session_id)][0]['agent'] == ''
            replay = [e async for e in runtime.stream(request)]
            assert [e['event'] for e in replay] == ['error']
            assert replay[0]['code'] == 'turn_interrupted'
            assert sum(name == 'schedule.callback' for name, _ in gateway.calls) == 1
            assert len(memory.turns[str(request.session_id)]) == 1
        finally:
            release.set()
            await stream.aclose()
            await runtime.close()
    asyncio.run(run())


def test_fragmented_model_tool_arguments_execute_before_answer_without_leaking():
    class ToolStream(StreamingModel):
        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            if self.calls == 1:
                yield ChatGenerationChunk(message=AIMessageChunk(content='', tool_call_chunks=[
                    {'name':'catalog_search', 'args':'{"query":"Air', 'id':'lookup-1', 'index':0}]))
                yield ChatGenerationChunk(message=AIMessageChunk(content='', tool_call_chunks=[
                    {'name':None, 'args':'Pure X"}', 'id':None, 'index':0}]))
            else:
                yield ChatGenerationChunk(message=AIMessageChunk(content='Em có thể tư vấn sản phẩm trong danh mục. '))
                yield ChatGenerationChunk(message=AIMessageChunk(content='Mình cần tư vấn loại nào ạ?'))

    async def run():
        model, gateway, memory = ToolStream(replies=[]), FakeGateway(), FakeMemory()
        runtime = AgentHarnessRuntime(model, gateway, memory)
        try:
            events = [e async for e in runtime.stream(turn('Em có thể hỗ trợ gì?'))]
            assert events[-1]['event'] == 'done'
            assert model.calls == 2
            assert any(name == 'catalog.search' and args['query'] == 'AirPure X' for name, args in gateway.calls)
            text = ''.join(e['text'] for e in events if e['event'] == 'delta')
            assert 'catalog_search' not in text and '{"query"' not in text
        finally:
            await runtime.close()
    asyncio.run(run())
