"""Regressions from the November 17 saved run; inference and storage stay offline."""
import asyncio
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage

from app.agent.guardrails.checks import check_answer
from test_commerce_evidence import catalog
from test_m1_round2_runtime import runtime_for, turns, tool_message
from test_november_pricing import reference


def mixed_basket_evidence():
    return [catalog('SKU-MB-MON', 'Máy hâm sữa Fatz 4 chức năng'),
        catalog('SKU-MB-BOT', 'Bình sữa Pigeon PPSU 240ml'),
        {'name': 'pricing.quote_order', 'args': {'on': '2026-10-25', 'lines': [
            {'sku': 'SKU-MB-MON', 'qty': 1}, {'sku': 'SKU-MB-BOT', 'qty': 1}]},
         'result': {'units': [
             {'unit': 1, 'sku': 'SKU-MB-MON', 'list_price_vnd': 490000,
              'final_price_vnd': 490000, 'applied_promos': []},
             {'unit': 2, 'sku': 'SKU-MB-BOT', 'list_price_vnd': 289000,
              'final_price_vnd': 289000, 'applied_promos': []}],
             'total_vnd': 779000, 'order_promos': [], 'freeship': False}}]


def test_verified_mixed_basket_is_not_restricted_to_previous_single_product_focus():
    speech = '2 sản phẩm Máy hâm sữa Fatz 4 chức năng và Bình sữa Pigeon PPSU 240ml có tổng giá 779.000đ.'
    customer = 'Ok anh đồng ý tổng giá đó, em lên đơn cả 2 sản phẩm thanh toán COD giúp anh nhé.'
    assert check_answer(speech, mixed_basket_evidence(), customer, focus_sku='SKU-MB-MON')[1] is None


@pytest.mark.parametrize('change', ['total', 'product', 'single_product_request', 'ambiguous_quotes'])
def test_basket_focus_recovery_does_not_accept_wrong_or_unrequested_claims(change):
    speech = '2 sản phẩm Máy hâm sữa Fatz 4 chức năng và Bình sữa Pigeon PPSU 240ml có tổng giá 779.000đ.'
    customer = 'Báo tổng giá giỏ hàng cả 2 sản phẩm giúp anh.'
    evidence = mixed_basket_evidence()
    if change == 'total':
        speech = speech.replace('779.000', '980.000')
    elif change == 'product':
        evidence.append(catalog('SKU-OTHER', 'Máy khác'))
        speech = speech.replace('Bình sữa Pigeon PPSU 240ml', 'Máy khác')
    elif change == 'single_product_request':
        customer = 'Chỉ báo giá Bình sữa Pigeon PPSU 240ml thôi.'
    else:
        evidence.append(deepcopy(evidence[-1]))
        evidence[-1]['result']['total_vnd'] = 980000
    assert check_answer(speech, evidence, customer, focus_sku='SKU-MB-MON')[1] is not None


def test_both_named_products_are_quoted_before_later_cod_acceptance(reference):
    runtime, repo = runtime_for(reference, [AIMessage(content='Em kiểm tra giúp mình.')])

    async def run():
        try:
            replies, states = await turns(runtime, [
                'Anh gọi lại vụ bình sữa Pigeon PPSU 240ml và máy hâm sữa Fatz 4 chức năng hôm trước, em kiểm tra tồn kho và báo tổng giá giỏ hàng của cả 2 sản phẩm đó giúp anh nhé.',
                'Ok anh đồng ý tổng giá đó, em lên đơn cả 2 sản phẩm thanh toán COD giúp anh nhé.',
            ], '2026-10-25')
            assert '779.000' in replies[0].agent_text, replies[0].agent_text
            assert 'Pigeon' in replies[0].agent_text and 'Fatz' in replies[0].agent_text
            assert {c['args']['sku'] for c in states[0]['tool_calls']
                    if c['name'] == 'inventory.check'} == {'SKU-MB-BOT', 'SKU-MB-MON'}
            assert not any(c['name'] == 'order.create' for c in states[0]['tool_calls'])
            assert len(repo.orders) == 1, [r.agent_text for r in replies]
            assert repo.orders[0]['total_vnd'] == 779000
            assert repo.orders[0]['payment'] == 'COD'
            assert {line['sku']: line['qty'] for line in repo.orders[0]['lines']} == {
                'SKU-MB-BOT': 1, 'SKU-MB-MON': 1}
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize('draft', [
    'Máy lọc nước UF Sunhouse có giá 3.290.000đ.',
    'Máy lọc nước UF Sunhouse có chỉ số TDS đầu ra 10 ppm.',
])
def test_missing_tds_is_disclosed_instead_of_price_or_guessed_measurement(reference, draft):
    runtime, repo = runtime_for(reference, [
        tool_message(('catalog.search', {'sku': 'SKU-WF-UF'})), AIMessage(content=draft)])

    async def run():
        try:
            replies, _ = await turns(runtime, [
                'Chị đang xem máy lọc nước UF Sunhouse, lọc xong thì chỉ số TDS đầu ra chính xác còn bao nhiêu ppm?',
            ], '2026-10-22')
            answer = replies[0].agent_text
            assert 'chưa có thông tin' in answer.lower(), answer
            assert 'TDS' in answer
            assert '10 ppm' not in answer
            assert not repo.orders
        finally:
            await runtime.close()

    asyncio.run(run())


def test_unsupported_tds_claim_is_rejected_even_without_an_explicit_tds_question():
    assert check_answer('Máy Aster có TDS đầu ra 10 ppm.', [catalog()], 'Tư vấn máy Aster.')[1] == 'unsupported_product_spec'


def test_sourced_tds_is_answered_and_a_different_measurement_is_rejected():
    from app.agent.harness.session_nodes import safe_product_reply
    from test_commerce_evidence import state
    evidence = catalog()
    evidence['result']['items'][0]['attributes']['tds_output_ppm'] = 10
    current = state('Chỉ số TDS đầu ra của Aster là bao nhiêu ppm?')
    current['tool_calls'] = [evidence]
    answer = safe_product_reply(current)
    assert '10 ppm' in answer
    assert check_answer(answer, [evidence], current['safe_text'])[1] is None
    assert check_answer('Aster có TDS đầu ra 20 ppm.', [evidence])[1] == 'unsupported_product_spec'


@pytest.mark.parametrize('detail', [
    'nên vẫn chưa được bàn giao cho đơn vị vận chuyển',
    'nên vẫn chưa được xuất kho giao đi',
    'tức là vẫn còn ở kho và chưa được giao đi',
])
def test_created_status_does_not_prove_physical_shipping_details(detail):
    evidence = [{'name': 'order.status', 'args': {'order_id': 'OD-TRACE'},
                 'result': {'orders': [{'order_id': 'OD-TRACE', 'status': 'created'}]}}]
    speech = f'Đơn OD-TRACE hiện ở trạng thái created, {detail} ạ.'
    assert check_answer(speech, evidence, 'Kiểm tra trạng thái đơn OD-TRACE giúp tôi.')[1] == 'order_status_unverified'
    assert check_answer('Đơn OD-TRACE đã tạo. Em chưa có thông tin xác minh về việc bàn giao.',
                        evidence, 'Kiểm tra trạng thái đơn OD-TRACE giúp tôi.')[1] is None


def test_shipping_detail_recovery_reports_only_the_verified_order_status():
    from app.agent.harness.agent_nodes import AgentNodes
    from test_commerce_evidence import state

    async def run():
        current = state('Kiểm tra trạng thái đơn OD-TRACE giúp tôi.')
        current['tool_calls'] = [{'name': 'order.status', 'args': {'order_id': 'OD-TRACE'},
            'result': {'orders': [{'order_id': 'OD-TRACE', 'status': 'created'}]}}]
        current['agent_draft'] = 'Đơn OD-TRACE vẫn còn ở kho và chưa được giao đi.'
        result = await AgentNodes(None, None, None, 6, 6).verify_agent(current)
        assert 'đơn đã tạo' in result['agent_text']
        assert 'ở kho' not in result['agent_text']
        assert 'chưa được giao đi' not in result['agent_text']

    asyncio.run(run())


def test_ready_purchase_is_verified_and_created_without_model_round_trip():
    from unittest.mock import patch
    from app.agent.harness.agent_nodes import AgentNodes
    from test_commerce_evidence import state, quote, stock, bind_history_observations
    from test_purchase_continuation import gateway

    async def run():
        current = state('Lấy Aster, lên đơn giúp tôi.')
        current['session_tool_calls'] = [catalog(), quote(), stock()]
        current['history'] = [{'customer': 'Tôi chọn Aster.', 'agent': 'Aster giá 900.000đ.'}]
        bind_history_observations(current)
        calls = []
        with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('unnecessary inference')):
            node = AgentNodes(None, gateway(calls), None, 6, 6)
            current.update(await node.run_agent(current))
            current.update(await node.verify_agent(current))
        assert [name for name, _ in calls] == ['order.create']
        assert 'OD-OFFLINE' in current['agent_text']

    asyncio.run(run())


@pytest.mark.parametrize('include_prior', [True, False])
@pytest.mark.parametrize('price_question', ['giá bao nhiêu và hiện còn hàng không', 'hiện còn hàng không và bao nhiêu tiền'])
def test_explicit_price_and_stock_use_prepared_evidence_without_inference(reference, include_prior, price_question):
    from unittest.mock import patch
    runtime, repo = runtime_for(reference, [])
    runtime.memory.include_prior = include_prior

    async def run():
        try:
            with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('unnecessary inference')):
                replies, states = await turns(runtime, [
                    f'Anh đang xem AirPure Pro {price_question}?',
                ], '2026-10-19')
            answer = replies[0].agent_text
            assert 'hết hàng' in answer and '7.690.000' in answer, answer
            assert {c['name'] for c in states[0]['tool_calls']} >= {
                'catalog.search', 'pricing.get_quote', 'inventory.check'}
            assert not repo.orders
        finally:
            await runtime.close()

    asyncio.run(run())
