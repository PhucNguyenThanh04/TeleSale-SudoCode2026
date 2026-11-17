"""K0 customer speech through real catalog, consent and tools; no model or DB."""
import asyncio
import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from uuid import uuid4
import pytest

from app.agent.implementations.business_agent import BusinessTools
from app.agent.harness.session_nodes import safe_consultation_reply
from app.mcp_servers.mcp_shared.commerce_rules import _catalog, _inventory, quote
from app.mcp_servers.mcp_shared.consultation import derive_consultation
from app.agent.memory.store import safe_observations
from test_commerce_evidence import state

BTC = Path(__file__).resolve().parents[3] / 'BTC-Data-Vong1-TEAMS'
PRODUCTS = json.loads((BTC / 'catalog/products.json').read_text())['products']
PROMOS = json.loads((BTC / 'catalog/promotions.json').read_text())['promotions']
EVENTS = json.loads((BTC / 'catalog/inventory_timeline.json').read_text())['events']


class OfflineCommerce:
    def __init__(self):
        self.calls = []

    async def invoke_trusted(self, name, args, *_args, **_kwargs):
        self.calls.append((name, deepcopy(args)))
        if name == 'catalog.search':
            return _catalog(PRODUCTS, args)
        if name == 'pricing.get_quote':
            return quote(PRODUCTS, PROMOS, args, set(), set())
        if name == 'inventory.check':
            return _inventory(PRODUCTS, EVENTS, args['sku'], args['on'])
        if name == 'pricing.quote_order':
            from app.mcp_servers.mcp_shared.commerce_rules import quote_order
            return quote_order(PRODUCTS, PROMOS, args)
        if name == 'order.create':
            return {'status': 'created', 'order_id': 'OD-OFFLINE'}
        raise AssertionError(name)


@pytest.mark.parametrize('suffix,prepared', [
    ('mỗi món 1 chiếc nhé.', True),
    ('mỗi món 2 chiếc nhé.', False),
    ('hay chỉ lấy một món thì sao?', False),
])
def test_explicit_two_product_total_is_prepared_before_purchase_consent(suffix, prepared):
    async def run():
        s = state('Anh hỏi bình sữa Pigeon PPSU 240ml và máy hâm sữa Fatz 4 chức năng.')
        s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 23)})
        gateway = OfflineCommerce()
        tools = BusinessTools(gateway, s, 8, lambda: None)
        for sku in ('SKU-MB-BOT', 'SKU-MB-MON'):
            await tools.invoke('catalog.search', {'sku': sku})
        commit(s, 'Em đã tìm thấy hai sản phẩm mình hỏi.')
        next_turn(s, 'Báo tổng giá giỏ hàng bình sữa Pigeon PPSU 240ml và máy hâm sữa Fatz 4 chức năng, ' + suffix)
        tools = BusinessTools(gateway, s, 8, lambda: None)
        await tools.prepare_consultation()
        basket = [c for c in s['tool_calls'] if c['name'] == 'pricing.quote_order']
        assert bool(basket) is prepared
        if not prepared:
            assert not any(name == 'order.create' for name, _ in gateway.calls)
            return
        assert len(basket) == 1
        assert basket[0]['args']['lines'] == [{'sku': 'SKU-MB-BOT', 'qty': 1}, {'sku': 'SKU-MB-MON', 'qty': 1}]
        assert basket[0]['result']['total_vnd'] == 779000
        assert not any(name == 'order.create' for name, _ in gateway.calls)
        commit(s, 'Bình sữa Pigeon PPSU 240ml và Máy hâm sữa Fatz 4 chức năng, 2 sản phẩm có tổng giá 779.000đ.')
        next_turn(s, 'Ok anh đồng ý tổng giá đó, em lên đơn cả 2 sản phẩm thanh toán COD giúp anh nhé.')
        result = await BusinessTools(gateway, s, 8, lambda: None).complete_purchase_if_ready()
        assert result and result.get('status') == 'created', safe_consultation_reply(s)
    asyncio.run(run())


def test_t17_cross_session_variant_facts_and_actual_smoke_speech_can_close():
    async def run():
        run = Path(__file__).resolve().parents[1] / 'eval_harness/results/smoke-repairs/20261112T060044Z-17ffa366'
        rows = list(map(json.loads, (run / 'full.diagnostics_full.jsonl').read_text().splitlines()))
        first, offered, accepted = [next(r for r in rows if (r['scenario_id'], r['call'], r['turn']) == key)
            for key in [('SC-T17', 'call_1', 1), ('SC-T17', 'call_2', 1), ('SC-T17', 'call_2', 2)]]
        s = state(offered['user_text'])
        s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 27)})
        facts = {}
        source = f'langmem:{uuid4()}:{uuid4()}'
        for write in first['memory_writes']:
            if write['scope_id'] == 'SKU-SN-RUN1':
                facts[write['key']] = {'value': write['value'], 'source': source,
                    'source_kind': 'customer' if write['key'].startswith('preferred_') else 'tool', 'status': 'active'}
        s['scoped_facts'] = {'product': {'SKU-SN-RUN1': facts}, 'room': {}}
        s['tool_calls'] = offered['tool_calls']
        commit(s, offered['agent_text'])
        next_turn(s, accepted['user_text'])
        s['tool_calls'] = accepted['tool_calls']
        s['tool_count'] = len(s['tool_calls'])
        gateway = OfflineCommerce()
        result = await BusinessTools(gateway, s, 5, lambda: None).complete_purchase_if_ready()
        from app.mcp_servers.mcp_shared.consultation import purchase_arguments, purchase_block_reason
        args = purchase_arguments(s)
        assert result and result.get('status') == 'created', (args, purchase_block_reason(s, args) if args else derive_consultation(s))
    asyncio.run(run())


def test_t10_accepts_exact_delivered_smoke_basket_sentence():
    async def run():
        run = Path(__file__).resolve().parents[1] / 'eval_harness/results/smoke-repairs/20261112T060044Z-17ffa366'
        rows = list(map(json.loads, (run / 'full.diagnostics_full.jsonl').read_text().splitlines()))
        offered, accepted = [next(r for r in rows if (r['scenario_id'], r['call'], r['turn']) ==
                                 ('SC-T10', 'call_1', turn)) for turn in (2, 3)]
        s = state(offered['user_text'])
        s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 23)})
        gateway = OfflineCommerce()
        tools = BusinessTools(gateway, s, 8, lambda: None)
        for sku in ('SKU-MB-CAR', 'SKU-MB-STR1'):
            await tools.invoke('catalog.search', {'sku': sku})
        await tools.prepare_consultation()
        commit(s, offered['agent_text'])
        next_turn(s, accepted['user_text'])
        from app.agent.harness.agent_nodes import AgentNodes
        # Real limit is five; no model is available to consume the write budget.
        result = await AgentNodes(None, gateway, None, 5, 6).run_agent(s)
        assert 'OD-OFFLINE' in result['agent_draft'], result
        assert len([c for c in s['tool_calls'] if c['name'] == 'order.create']) == 1
        assert s['tool_count'] <= 5
    asyncio.run(run())


def test_t18_total_request_fetches_missing_metadata_before_preparing_basket():
    async def run():
        scenario = json.loads((Path(__file__).resolve().parents[1] /
            'eval_harness/scenarios/SC-T18.json').read_text())
        s = state(scenario['calls']['call_2']['customer_turns'][0])
        s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 25)})
        s['consultation_scope'] = {'known': True, 'skus': ['SKU-MB-BOT', 'SKU-MB-MON']}
        gateway = OfflineCommerce()
        await BusinessTools(gateway, s, 8, lambda: None).prepare_consultation()
        baskets = [c for c in s['tool_calls'] if c['name'] == 'pricing.quote_order']
        assert len(baskets) == 1
        assert baskets[0]['args']['lines'] == [{'sku': 'SKU-MB-BOT', 'qty': 1}, {'sku': 'SKU-MB-MON', 'qty': 1}]
        assert baskets[0]['result']['total_vnd'] == 779000
        assert not any(c['name'] == 'pricing.get_quote' for c in s['tool_calls'])
    asyncio.run(run())


def test_t09_current_price_request_refreshes_previous_day_quote():
    async def run():
        scenario = json.loads((Path(__file__).resolve().parents[1] /
            'eval_harness/scenarios/SC-T09.json').read_text())
        s = state('Anh hỏi máy lọc không khí AirPure Pro, giá hôm nay bao nhiêu?')
        s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 21)})
        gateway = OfflineCommerce()
        tools = BusinessTools(gateway, s, 8, lambda: None)
        await tools.invoke('catalog.search', {'sku': 'SKU-AP-PRO'})
        await tools.invoke('pricing.get_quote', {'sku': 'SKU-AP-PRO'})
        commit(s, 'Máy lọc không khí AirPure Pro có giá 7.690.000đ.')
        next_turn(s, scenario['calls']['call_3']['customer_turns'][0])
        s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 22)})
        await BusinessTools(gateway, s, 8, lambda: None).prepare_consultation()
        quotes = [c for c in s['tool_calls'] if c['name'] == 'pricing.get_quote']
        assert len(quotes) == 1 and quotes[0]['args']['on'] == '2026-10-22'
        assert quotes[0]['args']['sku'] == 'SKU-AP-PRO'
        assert quotes[0]['result']['final_price_vnd'] == 7690000
        assert not any(c['name'] == 'order.create' for c in s['tool_calls'])
    asyncio.run(run())


def test_t13_explicit_new_search_reconsiders_previous_recommendation_with_current_budget():
    async def run():
        scenario = json.loads((Path(__file__).resolve().parents[1] /
            'eval_harness/scenarios/SC-T13.json').read_text())
        call = scenario['calls']['call_3']
        s = state('Tìm máy lọc không khí cho phòng 25m2, ngân sách tối đa 3 triệu.')
        s['request'] = s['request'].model_copy(update={'on': date(2026, 11, 5)})
        gateway = OfflineCommerce()
        await BusinessTools(gateway, s, 8, lambda: None).invoke('catalog.search', {'sku': 'SKU-XM-4L'})
        commit(s, 'Em đề xuất Máy lọc không khí Xiaomi Smart 4 Lite.')
        next_turn(s, call['customer_turns'][0])
        await BusinessTools(gateway, s, 8, lambda: None).prepare_consultation()
        searches = [c for c in s['tool_calls'] if c['name'] == 'catalog.search'
                    and c['args'].get('max_price_vnd') == 5500000]
        assert len(searches) == 1
        assert searches[0]['args']['category'] == 'gia-dung/may-loc-khong-khi'
        assert searches[0]['args']['min_room_area_m2'] == 25
        from app.agent.harness.session_nodes import safe_product_reply, safe_catalog_reply
        assert safe_product_reply(s) is None
        answer = safe_catalog_reply(s)
        assert 'AirPure Y' in answer, answer
        await BusinessTools(gateway, s, 8, lambda: None).prepare_consultation()
        assert len([c for c in s['tool_calls'] if c['name'] == 'catalog.search'
                    and c['args'].get('max_price_vnd') == 5500000]) == 1
        assert not any(name == 'order.create' for name, _ in gateway.calls)
    asyncio.run(run())


@pytest.mark.parametrize('budget,created', [('9 triệu', True), ('7 triệu', False)])
def test_t10_corrected_catalog_names_prepare_the_expected_two_item_total(budget, created):
    async def run():
        scenario = json.loads((Path(__file__).resolve().parents[1] /
            'eval_harness/scenarios/SC-T10.json').read_text())
        call = scenario['calls']['call_1']
        s = state(call['customer_turns'][0].replace('9 triệu', budget))
        s['request'] = s['request'].model_copy(update={'on': date.fromisoformat(call['call_date'])})
        gateway = OfflineCommerce()
        tools = BusinessTools(gateway, s, 8, lambda: None)
        for sku in ('SKU-MB-CAR', 'SKU-MB-STR1'):
            await tools.invoke('catalog.search', {'sku': sku})
        commit(s, 'Ghế ngồi ô tô Chicco và xe đẩy Joie Pact đều còn hàng.')
        next_turn(s, call['customer_turns'][1])
        await BusinessTools(gateway, s, 8, lambda: None).prepare_consultation()
        basket = next(c for c in s['tool_calls'] if c['name'] == 'pricing.quote_order')
        assert basket['args']['lines'] == [
            {'sku': 'SKU-MB-CAR', 'qty': 1}, {'sku': 'SKU-MB-STR1', 'qty': 1}]
        assert basket['result']['total_vnd'] == call['success_if']['total_match_vnd']
        assert not any(name == 'order.create' for name, _ in gateway.calls)
        commit(s, 'Ghế ngồi ô tô Chicco và xe đẩy Joie Pact, 2 sản phẩm có tổng giá 8.480.000đ.')
        next_turn(s, call['customer_turns'][2])
        result = await BusinessTools(gateway, s, 8, lambda: None).complete_purchase_if_ready()
        if created:
            assert result and result.get('status') == 'created', safe_consultation_reply(s)
        else:
            assert not result
            assert 'ngân sách' in safe_consultation_reply(s)
            assert not any(name == 'order.create' for name, _ in gateway.calls)
    asyncio.run(run())


def test_k0_split_stock_and_price_sentence_retains_exact_hikepro_offer():
    async def run():
        s = state('Anh hỏi HikePro size 41 màu xám, giá và tồn kho hôm nay nhé.')
        s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 21)})
        tools = BusinessTools(OfflineCommerce(), s, 6, lambda: None)
        await tools.invoke('catalog.search', {'sku': 'SKU-SN-TRK'})
        await tools.invoke('pricing.get_quote', {'sku': 'SKU-SN-TRK-41-XAM'})
        await tools.invoke('inventory.check', {'sku': 'SKU-SN-TRK-41-XAM'})
        commit(s, 'Đôi HikePro màu xám size 41 hiện vẫn còn hàng. Giá bán hôm nay là 1.990.000đ ạ.')
        next_turn(s, 'Ok em lên đơn cho anh 1 đôi theo đúng phiên bản đó, thanh toán COD nhé.')
        gateway = OfflineCommerce()
        result = await BusinessTools(gateway, s, 6, lambda: None).complete_purchase_if_ready()
        assert result and result.get('status') == 'created', safe_consultation_reply(s)
        assert gateway.calls[-1][1]['sku'] == 'SKU-SN-TRK-41-XAM'
    asyncio.run(run())


@pytest.mark.parametrize('spoken', [
    'Giày chạy bộ RunLite 1 size 41 màu đen hiện còn hàng, giá hiện tại 1.290.000đ.',
    'Giày chạy bộ RunLite 1 có giá cuối 1.290.000đ theo ngày cuộc gọi.',
])
def test_k0_expired_discount_acknowledgement_still_accepts_current_runlite_price(spoken):
    async def run():
        s = state('Anh hỏi giày chạy bộ RunLite 1 size 41 màu đen, giá và tồn kho hôm nay nhé.')
        s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 27)})
        gateway = OfflineCommerce()
        tools = BusinessTools(gateway, s, 6, lambda: None)
        for name, args in [('catalog.search', {'sku': 'SKU-SN-RUN1'}),
                           ('pricing.get_quote', {'sku': 'SKU-SN-RUN1-41-DEN'}),
                           ('inventory.check', {'sku': 'SKU-SN-RUN1-41-DEN'})]:
            await tools.invoke(name, args)
        commit(s, spoken)
        next_turn(s, 'À mã giảm 10% hết hạn rồi nên về giá niêm yết 1.290.000 đồng hả em, ok vậy em lên đơn cho anh 1 đôi đúng phiên bản đó, anh thanh toán chuyển khoản nhé.')
        result = await BusinessTools(gateway, s, 6, lambda: None).complete_purchase_if_ready()
        assert result and result.get('status') == 'created', safe_consultation_reply(s)
        assert gateway.calls[-1][1]['sku'] == 'SKU-SN-RUN1-41-DEN'
        assert gateway.calls[-1][1]['payment'] == 'bank'
    asyncio.run(run())


def commit(s, reply):
    tid = str(s['request'].client_msg_id)
    s['history'].append({'customer': s['safe_text'], 'agent': reply,
                         'source_turn_id': tid, 'on': str(s['request'].on)})
    # Use the production persistence allowlist, including sourced product names.
    s['session_tool_calls'].extend({**call, 'source_turn_id': tid,
        'customer_id': s['customer_id'], 'session_id': str(s['request'].session_id)}
        for call in safe_observations(s['tool_calls']))


def next_turn(s, text):
    s.update(safe_text=text, tool_calls=[], tool_count=0)
    s.pop('consultation_scope', None)
    s['request'] = s['request'].model_copy(update={'text': text, 'client_msg_id': uuid4()})


def test_windbreak_choice_survives_real_metadata_and_memory_allowlist_then_creates_once():
    async def run():
        s = state('Anh muốn mua áo Windbreak size M màu navy, xem giá giúp anh.')
        s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 15)})
        gateway = OfflineCommerce()
        tools = BusinessTools(gateway, s, 5, lambda: None)
        await tools.invoke('catalog.search', {'query': 'áo khoác Windbreak navy size M'})
        await tools.invoke('pricing.get_quote', {'sku': 'SKU-JK-WND-M-NAVY'})
        await tools.invoke('inventory.check', {'sku': 'SKU-JK-WND-M-NAVY'})
        commit(s, 'Áo khoác gió Windbreak size M màu navy hiện còn hàng, giá 690.000đ.')
        next_turn(s, 'Anh xác nhận mua một áo Windbreak size M màu navy, thanh toán COD. Em tạo đơn giúp anh nhé.')
        tools = BusinessTools(gateway, s, 3, lambda: None)
        await tools.prepare_consultation()
        result = await tools.complete_purchase_if_ready()
        assert result and result['status'] == 'created', safe_consultation_reply(s)
        await tools.complete_purchase_if_ready()
        orders = [args for name, args in gateway.calls if name == 'order.create']
        assert len(orders) == 1 and orders[0]['sku'] == 'SKU-JK-WND-M-NAVY'
    asyncio.run(run())


def test_price_and_stock_offer_allows_polite_order_confirmation_with_real_source_product():
    async def run():
        s = state('Anh đặt một nồi Lock&Lock 4 lít, thanh toán COD.')
        gateway = OfflineCommerce()
        tools = BusinessTools(gateway, s, 5, lambda: None)
        await tools.invoke('catalog.search', {'query': 'Lock 4'})
        await tools.invoke('pricing.get_quote', {'sku': 'SKU-AF-4L'})
        await tools.invoke('inventory.check', {'sku': 'SKU-AF-4L'})
        commit(s, 'Nồi chiên không dầu Lock&Lock 4L hiện có sẵn hàng với giá 1.890.000đ. Anh xác nhận để em lên đơn COD nhé?')
        next_turn(s, 'được rồi, cảm ơn em')
        tools = BusinessTools(gateway, s, 3, lambda: None)
        await tools.prepare_consultation()
        result = await tools.complete_purchase_if_ready()
        assert result and result['status'] == 'created', safe_consultation_reply(s)
        assert [a['sku'] for name, a in gateway.calls if name == 'order.create'] == ['SKU-AF-4L']
    asyncio.run(run())


def test_spectra_choice_does_not_authorize_combo_from_previous_agent_advice():
    s = state('ok, vậy chị lấy Spectra, trả Momo nhé')
    s['tool_calls'] = [{'name': 'catalog.search', 'args': {'query': 'Spectra S1'},
                        'result': _catalog(PRODUCTS, {'query': 'Spectra S1'})}]
    assert derive_consultation(s).snapshot.selected_sku == 'SKU-MB-PUMP1'


def test_unrelated_price_read_from_k0_is_blocked_after_named_catalog_lookup():
    async def run():
        s = state('Chị hỏi máy lọc nước Sunhouse UF.')
        gateway = OfflineCommerce()
        tools = BusinessTools(gateway, s, 5, lambda: None)
        await tools.invoke('catalog.search', {'query': 'máy lọc nước Sunhouse UF'})
        result = await tools.invoke('pricing.get_quote', {'sku': 'SKU-MB-MON'})
        assert result['error'] == 'unverified_sku'
        assert [name for name, _ in gateway.calls] == ['catalog.search']
    asyncio.run(run())


def test_spectra_short_name_cannot_authorize_a_previously_quoted_combo_order():
    async def run():
        s = state('ok, vậy chị lấy Spectra, chị trả Momo nhé')
        gateway = OfflineCommerce()
        tools = BusinessTools(gateway, s, 5, lambda: None)
        await tools.invoke('catalog.search', {'query': 'Spectra S1'})
        await tools.invoke('pricing.get_quote', {'sku': 'SKU-BDL-MOM'})
        await tools.invoke('inventory.check', {'sku': 'SKU-BDL-MOM'})
        result = await tools.invoke('order.create', {'sku': 'SKU-BDL-MOM', 'qty': 1,
            'price_vnd': 4790000, 'payment': 'momo'})
        assert result.get('error')
        assert not any(name == 'order.create' for name, _ in gateway.calls)
    asyncio.run(run())


def test_actual_agent_prepares_and_answers_owned_order_when_model_asks_for_id_again():
    from unittest.mock import patch
    from langchain_core.messages import AIMessage
    from app.agent.harness.agent_nodes import AgentNodes
    async def run():
        s = state('Anh hỏi tình trạng đơn đã mua hôm trước, em tra giúp nhé.')
        s['owned_order_ids'] = ['OD-OFFLINE']
        class Gateway(OfflineCommerce):
            async def invoke_trusted(self, name, args, *_args, **_kwargs):
                if name == 'order.status':
                    self.calls.append((name, dict(args)))
                    return {'orders': [{'order_id': 'OD-OFFLINE', 'status': 'shipping'}]}
                return await super().invoke_trusted(name, args, *_args, **_kwargs)
        class Agent:
            async def astream(self, *_args, **_kwargs):
                yield 'values', {'messages': [AIMessage(content='Anh cho em xin mã đơn hàng nhé.')]}
        gateway = Gateway()
        with patch('app.agent.harness.agent_nodes.build_agent', return_value=Agent()), \
             patch('app.agent.harness.agent_nodes.text_prompt', return_value='offline'):
            node = AgentNodes(None, gateway, None, 5, 6)
            s.update(await node.run_agent(s))
            result = await node.verify_agent(s)
        assert 'OD-OFFLINE' in result['agent_text'] and 'đơn đang giao' in result['agent_text']
        assert [name for name, _ in gateway.calls] == ['order.status']
    asyncio.run(run())
