import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from app.agent.harness.agent_nodes import AgentNodes
from app.schemas.agent import TextTurnRequest
from test_semantic_grounding import ReviewModel, verdict


def repair_case(*, basket=False):
    product_sku, gift_sku = (prefix + uuid4().hex[:8].translate(str.maketrans('0123456789', 'ghijklmnop'))
                             for prefix in ('ITEM-', 'EXTRA-'))
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(), on='2032-04-10',
        channel='hotline', channel_identity=None, input_mode='clean', text='Mẫu đèn này có quà gì?')
    product = {'sku': product_sku, 'name': 'Đèn đọc sách', 'attributes': {}, 'variants': []}
    gift = {'sku': gift_sku, 'name': 'Túi vải du lịch', 'attributes': {}, 'variants': []}
    quote = {'sku': product_sku, 'list_price_vnd': 860000, 'final_price_vnd': 860000,
        'applied_promos': [{'promo_code': 'TRAVEL-GIFT', 'type': 'gift',
            'gift_sku': gift_sku, 'valid_until': '2032-04-30'}]}
    call = {'name': 'pricing.get_quote', 'args': {'sku': product_sku, 'on': '2032-04-10'},
        'result': quote}
    if basket:
        call = {'name': 'pricing.quote_order', 'args': {'on': '2032-04-10'},
            'result': {'units': [quote], 'total_vnd': 860000, 'order_promos': []}}
    state = {'request': request, 'safe_text': request.text, 'identity_status': 'unknown',
        'agent_draft': 'Được tặng một xe đạp ạ.', 'tool_calls': [],
        'session_tool_calls': [{'name': 'catalog.search', 'args': {},
            'result': {'items': [product]}}, call]}
    gateway = SimpleNamespace(invoke=AsyncMock(return_value={'items': [gift], 'total': 1}))
    return state, gateway, gift


@pytest.mark.parametrize('basket', [False, True])
@pytest.mark.parametrize('repaired', ['Được tặng Túi vải du lịch ạ.',
    'Được tặng **1 chiếc Túi vải du lịch** miễn phí anh nhé.'])
def test_repair_resolves_active_gift_references_for_any_sku_and_quote_type(basket, repaired):
    state, gateway, gift = repair_case(basket=basket)
    before = deepcopy(state['session_tool_calls'])
    model = ReviewModel([verdict()], repaired)
    result = asyncio.run(AgentNodes(model, gateway, None, 6, 6).verify_agent(state))
    assert result['verified_answer'] == repaired
    assert result['tool_count'] == result['tool_attempts'] == 1
    assert result['tool_calls'] == [{'name': 'catalog.get_details',
        'args': {'sku': gift['sku']}, 'result': {'items': [gift], 'total': 1}}]
    assert state['session_tool_calls'] == before
    state.update(result)
    state['session_tool_calls'] += state.pop('tool_calls')
    state['tool_calls'] = []
    state['agent_draft'] = repaired
    next_result = asyncio.run(AgentNodes(ReviewModel([verdict()]), gateway, None, 6, 6).verify_agent(state))
    assert next_result['verified_answer'] == repaired
    assert gateway.invoke.await_count == 1


@pytest.mark.parametrize('blocked', ['budget', 'attempts', 'expired', 'old_date', 'other_owner', 'failed_refresh', 'context_failed'])
def test_repair_does_not_lookup_gifts_without_current_evidence_or_budget(blocked):
    state, gateway, gift = repair_case()
    quote = state['session_tool_calls'][-1]
    if blocked == 'budget':
        state['tool_count'] = 6
    elif blocked == 'attempts':
        state['tool_attempts'] = 12
    elif blocked == 'expired':
        quote['result']['applied_promos'][0]['valid_until'] = '2032-04-09'
    elif blocked == 'old_date':
        quote['args']['on'] = '2032-04-09'
    elif blocked == 'other_owner':
        quote['customer_id'] = 'OTHER'
    elif blocked == 'failed_refresh':
        state['tool_calls'] = [{**quote, 'result': {'error': 'unavailable'}}]
    else:
        state['tool_failed'] = True
    model = ReviewModel([], 'Được tặng Túi vải du lịch ạ.')
    result = asyncio.run(AgentNodes(model, gateway, None, 6, 6).verify_agent(state))
    assert result['verified_answer'] == ''
    assert result['reply_error'] == 'agent_reply_unavailable'
    assert gateway.invoke.await_count == 0


@pytest.mark.parametrize('output', [{'error': 'unavailable'}, {'items': []},
    {'items': [{'sku': 'OTHER', 'name': 'Túi vải du lịch'}]}, None])
def test_failed_or_wrong_gift_lookup_cannot_verify_a_named_gift(output):
    state, gateway, gift = repair_case()
    gateway.invoke.return_value = output
    result = asyncio.run(AgentNodes(ReviewModel([], 'Được tặng Túi vải du lịch ạ.'),
        gateway, None, 6, 6).verify_agent(state))
    assert result['verified_answer'] == ''
    assert result['reply_error'] == 'agent_reply_unavailable'
    assert result['tool_count'] == 1


def test_price_repair_also_fills_missing_gift_evidence():
    state, gateway, gift = repair_case()
    state['agent_draft'] = 'Đèn đọc sách giá 900.000đ, được tặng Túi vải du lịch ạ.'
    repaired = 'Đèn đọc sách giá 860.000đ, được tặng Túi vải du lịch ạ.'
    result = asyncio.run(AgentNodes(ReviewModel([verdict()], repaired), gateway, None, 6, 6).verify_agent(state))
    assert result['verified_answer'] == repaired
    assert result['tool_count'] == 1


@pytest.mark.parametrize('draft', [
    'Giá máy là 860.000đ, được miễn phí vận chuyển và dự kiến giao đến anh vào ngày 14/04/2032. '
    'Khi mua máy anh sẽ được tặng kèm một Túi vải du lịch nữa ạ.',
    'Giá máy là 860.000đ và được tặng Túi vải du lịch, đồng thời miễn phí vận chuyển.',
])
def test_natural_quote_and_gift_reach_semantic_review_without_unnecessary_repair(draft):
    state, gateway, gift = repair_case()
    state['session_tool_calls'][-1]['result'].update(freeship=True, estimated_delivery='2032-04-14')
    state['tool_calls'] = [{'name': 'catalog.get_details', 'args': {'sku': gift['sku']},
        'result': {'items': [gift]}}]
    state['agent_draft'] = draft
    model = ReviewModel([verdict()])
    result = asyncio.run(AgentNodes(model, gateway, None, 6, 6).verify_agent(state))
    assert result['verified_answer'] == draft
    assert model.payloads[0]['answer'] == draft
    assert model.ainvoke.await_count == gateway.invoke.await_count == 0


def test_catalog_gift_anchor_does_not_bypass_review_of_additional_claims():
    state, gateway, gift = repair_case()
    state['tool_calls'] = [{'name': 'catalog.get_details', 'args': {'sku': gift['sku']},
        'result': {'items': [gift]}}]
    state['agent_draft'] = 'Được tặng Túi vải du lịch cùng một xe đạp.'
    repaired = 'Được tặng Túi vải du lịch ạ.'
    model = ReviewModel([verdict(False, 'unsupported_claim', 'một xe đạp'), verdict()], repaired)
    result = asyncio.run(AgentNodes(model, gateway, None, 6, 6).verify_agent(state))
    assert result['verified_answer'] == repaired
    assert [payload['answer'] for payload in model.payloads] == [state['agent_draft'], repaired]
    assert result['verifier_events'][0]['reason'] == 'unsupported_answer_claim'


@pytest.mark.parametrize('delivery', ['run', 'stream'])
def test_real_runtime_persists_gift_evidence_and_reuses_it_next_turn(delivery):
    from app.agent.harness.runtime import AgentHarnessRuntime
    from test_deep_memory import FakeMemory, FakeToolModel

    async def run():
        state, gateway, gift = repair_case()
        product_call, quote_call = state['session_tool_calls']
        reply = 'Được tặng Túi vải du lịch ạ.'
        model = FakeToolModel(replies=[
            AIMessage(content='', tool_calls=[{'id': 'catalog', 'name': 'catalog_search',
                'args': {'sku': quote_call['args']['sku']}}]),
            AIMessage(content='', tool_calls=[{'id': 'quote', 'name': 'pricing_get_quote',
                'args': {'sku': quote_call['args']['sku']}}]),
            AIMessage(content=state['agent_draft']), AIMessage(content=reply), AIMessage(content=reply)])
        memory = FakeMemory()
        memory.commit_turn = AsyncMock(wraps=memory.commit_turn)

        async def invoke(name, args):
            if name == 'catalog.search':
                return product_call['result']
            if name == 'pricing.get_quote':
                return quote_call['result']
            assert name == 'catalog.get_details' and args == {'sku': gift['sku']}
            return {'items': [gift], 'total': 1}

        gateway.invoke.side_effect = invoke
        runtime = AgentHarnessRuntime(model, gateway, memory)
        try:
            if delivery == 'stream':
                events = [event async for event in runtime.stream(state['request'])]
                assert events[-1]['event'] == 'done'
                assert ''.join(event['text'] for event in events if event['event'] == 'delta') == reply
            else:
                assert (await runtime.run(state['request'])).agent_text == reply
            saved = memory.commit_turn.await_args.kwargs['tool_observations']
            assert saved[-1]['name'] == 'catalog.get_details'
            assert saved[-1]['result']['items'] == [gift]
            calls_before = gateway.invoke.await_count
            second_request = state['request'].model_copy(update={'client_msg_id': uuid4(),
                'text': 'Nhắc lại tên quà giúp tôi.'})
            assert (await runtime.run(second_request)).agent_text == reply
            assert gateway.invoke.await_count == calls_before
            assert len(memory.turns[str(state['request'].session_id)]) == 2
        finally:
            await runtime.close()

    asyncio.run(run())


def test_repair_backfills_missing_catalog_details_for_quoted_skus():
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(), on='2032-04-10',
        channel='hotline', channel_identity=None, input_mode='clean', text='Giá mẫu 4 Pro thế nào em?')
    state = {
        'request': request, 'safe_text': request.text, 'identity_status': 'unknown',
        'agent_draft': 'Máy lọc Xiaomi Smart 4 Pro giá 5.490.000đ ạ.',
        'tool_calls': [],
        'session_tool_calls': [
            {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-XM-4P', 'on': '2032-04-10'},
             'result': {'sku': 'SKU-XM-4P', 'list_price_vnd': 5490000, 'final_price_vnd': 5490000,
                        'applied_promos': []}},
            {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-XM-FLT', 'on': '2032-04-10'},
             'result': {'sku': 'SKU-XM-FLT', 'list_price_vnd': 590000, 'final_price_vnd': 590000,
                        'applied_promos': []}},
        ],
    }

    async def invoke(name, args):
        assert name == 'catalog.get_details'
        names = {'SKU-XM-4P': 'Máy lọc Xiaomi Smart 4 Pro', 'SKU-XM-FLT': 'Màng lọc Xiaomi Smart 4'}
        return {'items': [{'sku': args['sku'], 'name': names[args['sku']], 'variants': []}], 'total': 1}

    gateway = SimpleNamespace(invoke=AsyncMock(side_effect=invoke))
    repaired = 'Máy lọc Xiaomi Smart 4 Pro giá bán hôm nay là 5.490.000 đồng ạ.'
    model = ReviewModel([verdict()], repaired)
    result = asyncio.run(AgentNodes(model, gateway, None, 6, 6).verify_agent(state))
    assert result['verified_answer'] == repaired
    assert result['reply_error'] is None
    assert {call['args']['sku'] for call in result['tool_calls']} == {'SKU-XM-4P', 'SKU-XM-FLT'}
