import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_commerce_evidence import state, catalog, stock
from app.agent.implementations.business_agent import BusinessTools


def basket_state(text='Đồng ý mua cả hai máy, chuyển khoản nhé.'):
    current = state(text)
    tid = str(uuid4())
    current['history'] = [{'customer': 'Báo giá 2 máy Aster.',
                          'agent': '2 máy Aster có tổng giá 1.350.000đ.', 'source_turn_id': tid}]
    current['session_tool_calls'] = [catalog(), stock(), {'name': 'pricing.quote_order',
        'source_turn_id': tid, 'args': {'lines': [{'sku': 'SKU-ASTER', 'qty': 2}], 'on': '2026-11-05'},
        'result': {'units': [
            {'unit': 1, 'line': 0, 'sku': 'SKU-ASTER', 'list_price_vnd': 900000, 'final_price_vnd': 900000, 'applied_promos': []},
            {'unit': 2, 'line': 0, 'sku': 'SKU-ASTER', 'list_price_vnd': 900000, 'final_price_vnd': 450000,
             'applied_promos': [{'promo_code': 'SECOND', 'type': 'percent_second_item', 'discount_vnd': 450000}]}],
        'total_vnd': 1350000, 'order_promos': [], 'freeship': False}}]
    return current


def args():
    return {'lines': [{'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000},
                      {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 450000}], 'payment': 'bank'}


def invoke(current, proposed=None):
    gateway = AsyncMock()
    gateway.invoke_trusted.return_value = {'order_id': 'OD1', 'status': 'created', 'total_vnd': 1350000}
    business = BusinessTools(gateway, current, 5, lambda: datetime.now(timezone.utc))
    result = asyncio.run(business.invoke('order.create', proposed or args()))
    return result, gateway


def test_customer_can_accept_delivered_basket_without_repeating_prices():
    result, gateway = invoke(basket_state())
    assert result.get('status') == 'created', result
    assert gateway.invoke_trusted.await_count == 1
    assert gateway.invoke_trusted.await_args.args[1]['lines'] == args()['lines']




@pytest.mark.parametrize('change', ['unheard', 'no_consent', 'hypothetical', 'revoke',
    'quantity', 'price', 'stock', 'day', 'owner', 'address', 'failed_refresh', 'terms', 'shipping'])
def test_changed_or_unconfirmed_basket_never_writes(change):
    current = basket_state()
    proposed = args()
    if change == 'unheard':
        current['history'][0]['agent'] = ''
    elif change == 'no_consent':
        current['safe_text'] = 'Giá cả hai máy là bao nhiêu?'
    elif change == 'hypothetical':
        current['safe_text'] = 'Nếu đồng ý mua cả hai máy thì sao?'
    elif change == 'revoke':
        current['safe_text'] = 'Không mua nữa.'
    elif change == 'quantity':
        current['safe_text'] = 'Chỉ lấy 1 máy Aster thôi.'
    elif change == 'price':
        proposed['lines'][1]['price_vnd'] += 1
    elif change == 'stock':
        current['session_tool_calls'][1]['result']['qty'] = 1
    elif change == 'day':
        current['session_tool_calls'][-1]['args']['on'] = '2026-11-04'
    elif change == 'owner':
        current['session_tool_calls'][-1]['customer_id'] = 'OTHER'
    elif change == 'address':
        proposed['address'] = 'Region B'
    elif change == 'failed_refresh':
        old = current['session_tool_calls'][-1]
        current['tool_calls'] = [{**deepcopy(old), 'result': {'error': 'unavailable'}}]
    elif change == 'terms':
        newer = deepcopy(current['session_tool_calls'][-1])
        newer.pop('source_turn_id')
        newer['result']['units'][1]['applied_promos'] = []
        current['tool_calls'] = [newer]
    elif change == 'shipping':
        newer = deepcopy(current['session_tool_calls'][-1])
        newer.pop('source_turn_id')
        newer['result']['freeship'] = True
        current['tool_calls'] = [newer]
    result, gateway = invoke(current, proposed)
    assert 'error' in result
    assert not any(call.args[0] == 'order.create' for call in gateway.invoke_trusted.await_args_list)


def test_model_discovers_november_basket_tool():
    business = BusinessTools(AsyncMock(), state(), 5, lambda: datetime.now(timezone.utc))
    tools = {tool.name: tool for tool in business.langchain_tools()}
    assert 'pricing_quote_order' in tools
    assert 'lines' in tools['order_create'].args


def test_basket_memory_keeps_unit_evidence_without_private_fields():
    import json
    from app.mcp_servers.mcp_shared.memory_observations import memory_observations
    quote = deepcopy(basket_state()['session_tool_calls'][-1])
    quote['args']['customer_phone'] = '0912345678'
    quote['args']['address'] = '12 Đường Riêng Tư'
    quote['args']['lines'][0]['internal_cost_vnd'] = 123
    quote['result']['units'][0]['supplier'] = 'Nhà cung cấp bí mật'
    quote['result']['units'][1]['applied_promos'][0]['private_note'] = 'Không chia sẻ'
    result = memory_observations([quote])
    assert result[0]['args']['lines'] == [{'sku': 'SKU-ASTER', 'qty': 2}]
    assert result[0]['result']['units'][1]['final_price_vnd'] == 450000
    encoded = json.dumps(result, ensure_ascii=False)
    for forbidden in ('0912345678', 'Đường Riêng', 'internal_cost', 'supplier', 'private_note'):
        assert forbidden not in encoded


def test_verified_basket_total_can_be_spoken_but_wrong_total_cannot():
    from app.agent.guardrails.checks import check_answer
    current = basket_state()
    evidence = current['session_tool_calls']
    assert check_answer('2 máy Aster có tổng giá 1.350.000đ.', evidence)[1] is None
    assert check_answer('2 máy Aster có tổng giá 1.800.000đ.', evidence)[1] is not None


def test_old_scalar_quote_cannot_validate_wrong_basket_total():
    from app.agent.guardrails.checks import check_answer
    from test_commerce_evidence import quote
    evidence = basket_state()['session_tool_calls']
    evidence.insert(1, quote(qty=2))
    assert check_answer('2 máy Aster có tổng giá 1.800.000đ.', evidence)[1] is not None
    assert check_answer('2 máy Aster có tổng giá 1.350.000đ.', evidence)[1] is None


def test_old_scalar_quote_cannot_override_a_discounted_unit_price():
    from app.agent.guardrails.checks import check_answer
    from test_commerce_evidence import quote
    evidence = basket_state()['session_tool_calls']
    evidence.insert(1, quote())
    assert check_answer('Máy thứ 2 Aster giá 900.000đ.', evidence)[1] is not None
    assert check_answer('Máy thứ 2 Aster giá 450.000đ.', evidence)[1] is None
    evidence.extend([catalog('SKU-BRIO', 'Brio'), quote('SKU-BRIO', 800000)])
    assert check_answer('Máy thứ 2 Aster giá 450.000đ. Brio giá 800.000đ.', evidence)[1] is None


def test_accepting_basket_cannot_create_scalar_order_from_an_older_quote():
    from test_commerce_evidence import quote
    current = basket_state()
    current['history'][0]['customer'] = 'Lấy Aster, báo giá 2 máy.'
    current['session_tool_calls'].insert(2, quote())
    result, gateway = invoke(current, {'sku': 'SKU-ASTER', 'qty': 1,
                                      'price_vnd': 900000, 'payment': 'bank'})
    assert 'error' in result
    assert not any(call.args[0] == 'order.create' for call in gateway.invoke_trusted.await_args_list)


def test_repeated_basket_create_in_one_turn_does_not_create_twice():
    async def run():
        current = basket_state()
        gateway = AsyncMock()
        gateway.invoke_trusted.return_value = {'order_id': 'OD1', 'status': 'created', 'total_vnd': 1350000}
        tools = BusinessTools(gateway, current, 5, lambda: datetime.now(timezone.utc))
        first = await tools.invoke('order.create', args())
        assert first.get('status') == 'created'
        assert await tools.invoke('order.create', args()) == first
        assert gateway.invoke_trusted.await_count == 1
    asyncio.run(run())




def test_customer_can_accept_quote_repeated_after_interrupted_delivery():
    current = basket_state()
    speech = current['history'][0]['agent']
    current['history'][0]['agent'] = 'Dạ, em có báo giá.'
    current['history'].append({'customer': 'Đọc lại báo giá giúp tôi.', 'agent': speech,
                               'source_turn_id': str(uuid4())})
    result, gateway = invoke(current)
    assert result.get('status') == 'created', result
    assert gateway.invoke_trusted.await_count == 1


def test_basket_variant_requires_delivered_terms_and_respects_new_customer_size():
    current = basket_state()
    item = current['session_tool_calls'][0]['result']['items'][0]
    item['variants'] = [{'variant_sku': 'SKU-ASTER-39', 'size': 39, 'color': 'đen'},
                        {'variant_sku': 'SKU-ASTER-40', 'size': 40, 'color': 'đen'}]
    current['session_tool_calls'][1]['args']['sku'] = 'SKU-ASTER-39'
    current['session_tool_calls'][1]['result']['sku'] = 'SKU-ASTER-39'
    current['session_tool_calls'][-1]['args']['lines'][0]['sku'] = 'SKU-ASTER-39'
    for unit in current['session_tool_calls'][-1]['result']['units']:
        unit['sku'] = 'SKU-ASTER-39'
    proposed = args()
    for line in proposed['lines']:
        line['sku'] = 'SKU-ASTER-39'
    result, gateway = invoke(current, proposed)
    assert 'error' in result
    assert not gateway.invoke_trusted.await_count
    current['history'][0]['agent'] = '2 máy Aster size 39 màu đen có tổng giá 1.350.000đ.'
    result, _ = invoke(deepcopy(current), proposed)
    assert result.get('status') == 'created', result
    current['safe_text'] = 'Đồng ý mua cả hai Aster size 40 màu đen, chuyển khoản nhé.'
    result, gateway = invoke(current, proposed)
    assert 'error' in result
    assert not gateway.invoke_trusted.await_count






def test_discount_percentage_is_bound_to_the_discounted_physical_unit():
    from app.agent.guardrails.checks import check_answer
    calls = basket_state()['session_tool_calls']
    assert check_answer('Máy thứ 2 Aster được giảm 50%.', calls)[1] is None
    assert check_answer('Máy thứ 1 Aster được giảm 50%.', calls)[1] is not None
    assert check_answer('Cả hai máy Aster đều được giảm 50%.', calls)[1] is not None


def test_order_freeship_does_not_require_a_single_discounted_unit():
    from app.agent.guardrails.checks import check_answer
    calls = basket_state()['session_tool_calls']
    calls[-1]['result']['freeship'] = True
    calls[-1]['result']['order_promos'] = [{'promo_code': 'SHIP-ALL', 'type': 'freeship'}]
    assert check_answer('Cả đơn được miễn phí vận chuyển.', calls)[1] is None
    assert check_answer('Cả đơn dùng mã SHIP-ALL được miễn phí vận chuyển.', calls)[1] is None
    assert check_answer('Cả đơn được giảm 50% và miễn phí vận chuyển.', calls)[1] is not None
    assert check_answer('Cả đơn dùng mã SHIP-OTHER được miễn phí vận chuyển.', calls)[1] is not None
    calls[-1]['result']['freeship'] = False
    assert check_answer('Cả đơn được miễn phí vận chuyển.', calls)[1] is not None


@pytest.mark.parametrize('condition', ['payment', 'spoken_quantity', 'room', 'child_lock'])
def test_basket_respects_customer_transaction_and_product_constraints(condition):
    current = basket_state()
    proposed = args()
    if condition == 'payment':
        proposed['payment'] = 'COD'
    elif condition == 'spoken_quantity':
        current['safe_text'] = 'Chỉ lấy một máy Aster, chuyển khoản nhé.'
    elif condition == 'room':
        current['profile'] = {'room_area_m2': {'value': 100}}
        current['session_tool_calls'][0]['result']['items'][0]['category'] = 'gia-dung/may-loc-khong-khi'
    elif condition == 'child_lock':
        current['safe_text'] = 'Đồng ý mua cả hai, cần khóa trẻ em nhé, chuyển khoản.'
    result, gateway = invoke(current, proposed)
    assert 'error' in result
    assert not gateway.invoke_trusted.await_count


@pytest.mark.parametrize('budget,allowed', [
    ('tối đa 1 triệu mỗi máy', True), ('tối đa 1 triệu tổng cả đơn', False),
    ('ngân sách 2 triệu', True), ('ngân sách 1 triệu', False),
    ('tối đa 0đ tổng cả đơn', False)])
def test_basket_distinguishes_unit_total_and_unknown_budget(budget, allowed):
    current = basket_state(f'Đồng ý mua cả hai máy, {budget}, chuyển khoản nhé.')
    result, gateway = invoke(current)
    assert (result.get('status') == 'created') is allowed, result
    assert bool(gateway.invoke_trusted.await_count) is allowed
