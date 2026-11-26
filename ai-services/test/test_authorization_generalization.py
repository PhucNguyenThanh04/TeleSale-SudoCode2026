import asyncio
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.agent.harness.authorization import authorize_write, deterministic_fast_authorize
from app.schemas.agent import TextTurnRequest


@pytest.fixture(params=[('CONTROL-81', 'Bộ điều khiển Lumen', 275000),
                       ('PANEL-B7', 'Tấm điều khiển Boreal', 830000)])
def purchase(request):
    sku, name, price = request.param
    text = f'Ok em lên đơn cho tôi 1 chiếc {name}, thanh toán COD nhé.'
    turn = TextTurnRequest(session_id=uuid4(), client_msg_id=uuid4(),
        channel='hotline', channel_identity='0900000081', on=date(2033, 5, 10),
        text=text, input_mode='clean')
    state = {'request': turn, 'safe_text': text, 'identity_status': 'known',
        'customer_id': 'OWNER-INDEPENDENT', 'customer_phone': '0900000081',
        'tool_calls': [], 'session_tool_calls': [
            {'name': 'catalog.search', 'args': {}, 'result': {'items': [
                {'sku': sku, 'name': name, 'variants': []},
                {'sku': 'OTHER-92', 'name': 'Thiết bị Vega', 'variants': []}]}},
            {'name': 'inventory.check', 'args': {'sku': sku, 'on': '2033-05-10'},
             'result': {'sku': sku, 'qty': 12, 'in_stock': True}},
            {'name': 'pricing.get_quote', 'args': {'sku': sku, 'on': '2033-05-10',
                'customer_phone': '0900000081'},
             'result': {'sku': sku, 'final_price_vnd': price, 'applied_promos': []}}]}
    args = {'sku': sku, 'qty': 1, 'price_vnd': price, 'payment': 'COD',
        'customer_phone': '0900000081', 'on': '2033-05-10'}
    return state, args, name


@pytest.mark.parametrize('change', ['target', 'quantity', 'payment', 'delivery',
                                  'third_party', 'question', 'negation', 'condition'])
def test_fast_approval_requires_the_exact_current_request(purchase, change):
    state, args, name = purchase
    state['safe_text'] = {
        'target': 'Ok em lên đơn cho tôi 1 chiếc Thiết bị Vega, thanh toán COD nhé.',
        'quantity': f'Ok em lên đơn cho tôi 2 chiếc {name}, thanh toán COD nhé.',
        'payment': f'Ok em lên đơn cho tôi 1 chiếc {name}, chuyển khoản nhé.',
        'delivery': f'Ok em lên đơn cho tôi 1 chiếc {name}, giao trước sáu giờ nhé.',
        'third_party': f'Khách hàng khác nói: "Ok em lên đơn cho tôi 1 chiếc {name}".',
        'question': f'Lên đơn cho tôi 1 chiếc {name} có được không?',
        'negation': f'Đừng lên đơn cho tôi 1 chiếc {name}.',
        'condition': f'Chỉ lên đơn cho tôi 1 chiếc {name} khi đã gọi xác nhận.',
    }[change]
    state['request'] = state['request'].model_copy(update={'text': state['safe_text']})
    assert deterministic_fast_authorize('order.create', args, state) is not True


@pytest.mark.parametrize('change', ['stale_quote', 'wrong_owner', 'wrong_session',
                                  'failed_refresh', 'wrong_quantity', 'wrong_address'])
def test_fast_approval_uses_latest_bound_commerce_evidence(purchase, change):
    state, args, _ = purchase
    quote = state['session_tool_calls'][-1]
    if change == 'stale_quote':
        quote['args']['on'] = '2033-05-09'
    elif change == 'wrong_owner':
        quote['customer_id'] = 'OTHER-OWNER'
    elif change == 'wrong_session':
        quote['session_id'] = str(uuid4())
    elif change == 'failed_refresh':
        state['tool_calls'].append({**deepcopy(quote), 'result': {'error': 'unavailable'}})
    elif change == 'wrong_quantity':
        quote['args']['qty'] = 2
    else:
        quote['args']['address'] = 'Hà Nội'
    assert deterministic_fast_authorize('order.create', args, state) is not True


def test_clear_unfamiliar_purchase_keeps_the_fast_path(purchase):
    state, args, _ = purchase
    model = AsyncMock()
    model.with_structured_output.side_effect = AssertionError('Unexpected model call')
    assert asyncio.run(authorize_write(model, state, 'order.create', args, 6)) is True


def test_unrecognized_request_is_still_reviewed_independently(purchase):
    state, args, _ = purchase
    state['safe_text'] = 'Mình đồng ý với phương án vừa trao đổi, nhờ bạn thực hiện.'
    reviewer = SimpleNamespace(ainvoke=AsyncMock(return_value={
        'allowed': True, 'basis': 'customer_request',
        'customer_quote': state['safe_text'], 'reason': 'authorized'}))
    model = SimpleNamespace(with_structured_output=Mock(return_value=reviewer))
    assert asyncio.run(authorize_write(model, state, 'order.create', args, 6)) is True
    reviewer.ainvoke.assert_awaited_once()
