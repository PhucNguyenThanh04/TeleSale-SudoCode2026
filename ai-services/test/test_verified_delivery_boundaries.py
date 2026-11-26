import asyncio
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk

from app.agent.harness.agent_nodes import _contextual_safe_fallback, SAFE_VERIFICATION_FALLBACK
from app.agent.harness.streaming import GuardedStream
from test_commerce_evidence import state, catalog, quote


@pytest.mark.parametrize('prefix', ['Em có thể hỗ trợ mình. ', 'Aster có giá 900.000đ. '])
def test_progressive_draft_waits_for_whole_answer_review(prefix):
    async def run():
        sink = AsyncMock(return_value=True)
        stream = GuardedStream(sink, progressive=True)
        current = state('Giá Aster bao nhiêu?')
        current['tool_calls'] = [catalog(), quote()]
        await stream.feed(AIMessageChunk(content=prefix, id='draft'), current)
        assert not sink.called
        final = 'Em cần kiểm tra lại thông tin trước khi xác nhận.'
        current['verified_answer'] = final
        assert await stream.finish(final, current) == final
        assert ''.join(call.args[0] for call in sink.await_args_list) == final
    asyncio.run(run())


def test_fallback_does_not_treat_a_gift_detail_as_customer_product():
    calls = [
        {'name': 'pricing.get_quote', 'args': {'sku': 'MAIN-77'}, 'result': {
            'sku': 'MAIN-77', 'applied_promos': [{'type': 'gift', 'gift_sku': 'GIFT-91'}]}},
        {'name': 'catalog.get_details', 'args': {'sku': 'GIFT-91'}, 'result': {
            'items': [{'sku': 'GIFT-91', 'name': 'Túi quà Nebula', 'variants': []}]}},
    ]
    assert _contextual_safe_fallback(state('Mẫu chính có ưu đãi gì?'), calls,
                                     'promotion_unverified') == SAFE_VERIFICATION_FALLBACK


def test_fallback_does_not_ask_for_quantity_and_location_already_given():
    current = state('Tôi cần một chiếc Aster giao tới Huế, giá bao nhiêu?')
    answer = _contextual_safe_fallback(current, [catalog()], 'price_without_quote')
    assert '?' not in answer
    assert 'cho em biết' not in answer.lower()


def test_rejected_draft_and_gift_refresh_cannot_choose_fallback_product():
    calls = [
        {'name': 'pricing.get_quote', 'args': {'sku': 'MAIN-77'}, 'result': {
            'sku': 'MAIN-77', 'applied_promos': [{'type': 'gift', 'gift_sku': 'GIFT-91'}]}},
        {'name': 'catalog.get_details', 'args': {'sku': 'GIFT-91'}, 'result': {
            'items': [{'sku': 'GIFT-91', 'name': 'Túi quà Nebula', 'variants': []}]}},
        {'name': 'pricing.get_quote', 'args': {'sku': 'GIFT-91'}, 'result': {
            'sku': 'GIFT-91', 'final_price_vnd': 74000}},
    ]
    current = state('Nhà có con nhỏ, ngân sách tôi đã nói ở trên.')
    current['agent_draft'] = 'Túi quà Nebula phù hợp với mình.'
    answer = _contextual_safe_fallback(current, calls, 'price_without_quote')
    assert answer == SAFE_VERIFICATION_FALLBACK
    from app.agent.memory.reported_facts import reported_tool_candidates
    assert not any(f['key'] == 'product_advised' for f in reported_tool_candidates(answer, calls))


def test_fallback_may_name_the_product_explicitly_requested_by_customer():
    current = state('Tôi đang hỏi Aster, giá bao nhiêu?')
    answer = _contextual_safe_fallback(current, [catalog()], 'price_without_quote')
    assert 'Aster' in answer
