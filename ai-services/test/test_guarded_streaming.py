"""Streaming checks run before publication, never after a leaked draft."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk

from test_commerce_evidence import state, catalog, quote, stock


def collector():
    from app.agent.harness.streaming import GuardedStream
    sink = AsyncMock(return_value=True)
    return GuardedStream(sink), sink


def chunk(text, **kwargs):
    return AIMessageChunk(content=text, id='answer-1', **kwargs)


def test_answer_waits_for_message_completion_before_publication():
    async def run():
        stream, sink = collector()
        current = state('Tôi muốn hỏi về Aster, em có thể giúp gì?')
        await stream.feed(chunk('Em có thể kiểm tra giá và tồn kho giúp mình. '), current)
        assert not sink.called
        await stream.feed(chunk('Mình cần kiểm tra thông tin nào trước ạ?',
                                response_metadata={'finish_reason':'stop'}), current)
        assert sink.await_count == 1
        final = await stream.finish('Em có thể kiểm tra giá và tồn kho giúp mình. Mình cần kiểm tra thông tin nào trước ạ?', current)
        assert final == ''.join(c.args[0] for c in sink.await_args_list)
    asyncio.run(run())


@pytest.mark.parametrize('text', [
    'Aster có giá 1.000.000đ. ',
    'Aster hiện hết hàng. ',
    'Dạ, em đang kiểm tra giúp mình. ',
    'Số điện thoại là 0901234567. ',
    '<think>Em cần gọi tool trước.</think> ',
    '{"tool_calls": [{"name": "pricing.get_quote"}]}\n\n',
])
def test_unsupported_facts_pii_internal_tokens_and_progress_ack_are_not_published(text):
    async def run():
        stream, sink = collector()
        current = state('Aster giá bao nhiêu và còn hàng không?')
        current['tool_calls'] = [catalog(), quote(), stock()]
        for piece in [text[:10], text[10:]]:
            await stream.feed(chunk(piece), current)
        await stream.feed(chunk('', response_metadata={'finish_reason':'stop'}), current)
        assert not sink.called
    asyncio.run(run())


def test_request_for_price_and_stock_does_not_emit_only_price():
    async def run():
        stream, sink = collector()
        current = state('Aster giá bao nhiêu và còn hàng không?')
        current['tool_calls'] = [catalog(), quote(), stock()]
        await stream.feed(chunk('Aster có giá 900.000đ. '), current)
        assert not sink.called
        await stream.feed(chunk('Aster hiện còn hàng. ', response_metadata={'finish_reason':'stop'}), current)
        assert sink.await_count == 1
    asyncio.run(run())


def test_policy_is_held_until_conditions_and_final_verification_are_available():
    async def run():
        stream, sink = collector()
        current = state('Chính sách đổi trả thế nào?')
        await stream.feed(chunk('Anh được đổi hàng miễn phí. '), current)
        await stream.feed(chunk('Nếu còn trong thời hạn và giữ nguyên tem. '), current)
        assert not sink.called
        verified = 'Em cần xác minh ngày nhận hàng trước khi xác nhận quyền lợi đổi trả.'
        assert await stream.finish(verified, current) == verified
        assert sink.await_args.args[0] == verified
    asyncio.run(run())


def test_tool_argument_chunks_are_never_customer_output():
    async def run():
        stream, sink = collector()
        await stream.feed(chunk('', tool_call_chunks=[{'name': 'pricing.get_quote',
            'args': '{"sku":"SKU-ASTER"}', 'index': 0, 'id': 'tool-1'}]), state('Giá Aster?'))
        assert not sink.called
    asyncio.run(run())


def test_rejected_suffix_cannot_retract_or_corrupt_published_answer():
    async def run():
        stream, sink = collector()
        current = state('Aster giá bao nhiêu?')
        current['tool_calls'] = [catalog(), quote()]
        await stream.feed(chunk('Aster có giá 900.000đ. ',
                                response_metadata={'finish_reason':'stop'}), current)
        published = stream.published
        assert published
        final = await stream.finish('Aster có giá 1.000.000đ.', current)
        assert final == published
        assert '1.000.000' not in ''.join(c.args[0] for c in sink.await_args_list)
    asyncio.run(run())


def test_disconnected_sink_does_not_become_delivered_history():
    async def run():
        stream, sink = collector()
        sink.return_value = False
        final = await stream.finish('Em có thể hỗ trợ tư vấn sản phẩm.', state('Xin tư vấn'))
        assert final == stream.published == ''
    asyncio.run(run())


@pytest.mark.parametrize('text', ['{"name":"order.create","arguments":{"sku":"SKU-ASTER"}}',
                                  '<think>PRIVATE REASONING</think>Xin chào.'])
def test_final_recovery_never_exposes_machine_output(text):
    from app.agent.guardrails.checks import FALLBACK
    async def run():
        stream, sink = collector()
        assert await stream.finish(text, state('Xin tư vấn')) == FALLBACK
        assert sink.await_args.args[0] == FALLBACK
    asyncio.run(run())


@pytest.mark.parametrize('customer_text,answer', [
    ('Tôi muốn đổi sang sản phẩm khác.', 'Em có thể tư vấn sản phẩm trong danh mục. '),
    ('Xin tư vấn sản phẩm.', 'Số điện thoại của mình là 090123. '),
    ('Xin tư vấn sản phẩm.', 'Email của mình là thanh. '),
])
def test_sensitive_actions_and_incomplete_pii_stay_buffered(customer_text, answer):
    async def run():
        stream, sink = collector()
        await stream.feed(chunk(answer), state(customer_text))
        assert not sink.called
    asyncio.run(run())


def test_complete_sourced_answer_can_stream_at_message_stop():
    from test_consultation_followup import consultation_state, quoted
    from app.agent.harness.session_nodes import safe_followup_reply
    async def run():
        stream, sink = collector()
        current = quoted(consultation_state('Aster Air bên kia bán 4590k, sao bên em đắt hơn?'),
                         promos=[{'type':'freecod', 'promo_code':'COD-ZERO', 'discount_vnd':0}])
        answer = safe_followup_reply(current)
        assert '5.200.000' in answer and 'COD' in answer
        await stream.feed(chunk(answer+'\n\n', response_metadata={'finish_reason':'stop'}), current)
        assert sink.called and stream.published == answer
    asyncio.run(run())
