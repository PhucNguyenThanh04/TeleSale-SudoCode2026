"""Catalog behavior with products and variants absent from published scenarios."""
import asyncio
from datetime import date, datetime
from uuid import uuid4

import pytest

from app.agent.harness.policy import prepare_tool_call
from app.agent.harness.state import Decision
from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
from app.mcp_servers.mcp_shared.commerce_rules import _catalog
from app.schemas.agent import TextTurnRequest


def state(text, items):
    return {'request': TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
        channel='hotline', channel_identity='offline', on=date(2028, 3, 17), text=text, input_mode='clean'),
        'safe_text': text, 'tool_calls': [{'name': 'catalog.search', 'args': {'query': 'Nova'},
        'result': {'items': items}}], 'tool_count': 0}


def product(sku, name):
    return {'sku': sku, 'name': name, 'brand': 'Nova', 'category': 'van-phong/den',
            'list_price_vnd': 100_000, 'attributes': {}, 'variants': []}


@pytest.mark.parametrize('size,color', [('3XL', 'tím than'), ('38.5', 'vàng kem'), ('one size', 'hồng phấn')])
def test_claim_variant_values_come_from_catalog(size, color):
    item = product('SKU-NOVA', 'Đèn Nova Lumi')
    item['variants'] = [{'variant_sku': 'SKU-NOVA-CHOSEN', 'size': size, 'color': color},
                        {'variant_sku': 'SKU-NOVA-OTHER', 'size': 'M', 'color': 'trắng'}]
    s = state(f'Nova Lumi size {size} màu {color} có giá 100.000đ.', [item])
    assert resolve_claim_skus(s['safe_text'], s['tool_calls']) == {'SKU-NOVA-CHOSEN'}


def test_unknown_model_version_is_not_replaced_with_existing_version():
    item = product('SKU-NOVA-800', 'Đèn Nova 800')
    assert _catalog([item], {'query': 'Nova 900'})['items'] == []


def test_verified_sku_without_published_prefix_can_be_quoted():
    item = product('LAMP:2028-A', 'Đèn Nova Lumi')
    s = state('Nova Lumi giá bao nhiêu?', [item])
    s['decision'] = Decision(action='tool', tool_name='pricing.get_quote', tool_args={'sku': item['sku']})
    prepared = prepare_tool_call(s, datetime.now)
    assert prepared is not None and prepared[1]['sku'] == item['sku']
    # A model's arbitrary product label still cannot supply a verified identifier.
    s['tool_calls'] = []
    assert prepare_tool_call(s, datetime.now) is None


@pytest.mark.parametrize('count', [2, 3, 4])
def test_basket_preparation_accepts_explicit_one_each_for_any_product_count(count):
    from app.agent.implementations.business_agent import BusinessTools
    items = [product(f'SKU-NOVA-{i}', f'Đèn Nova N{i}') for i in range(count)]
    text = 'Tổng giá giỏ hàng ' + ', '.join(p['name'] for p in items) + ', mỗi sản phẩm 1 nhé.'
    s = state(text, items)

    class Gateway:
        async def invoke(self, name, args):
            if name == 'pricing.quote_order':
                return {'total_vnd': count * 100_000, 'units': [], 'lines': args['lines']}
            if name == 'pricing.get_quote':
                return {'sku': args['sku'], 'final_price_vnd': 100_000}
            return {'items': items}

    asyncio.run(BusinessTools(Gateway(), s, 10, datetime.now).prepare_consultation())
    quotes = [c for c in s['tool_calls'] if c['name'] == 'pricing.quote_order']
    assert len(quotes) == 1
    assert quotes[0]['args']['lines'] == [{'sku': sku, 'qty': 1} for sku in sorted(p['sku'] for p in items)]
    assert not any(c['name'] == 'order.create' for c in s['tool_calls'])


@pytest.mark.parametrize('phrase,quantity', [('2 máy', 2), ('ba chiếc', 3), ('4 đôi', 4), ('năm bộ', 5)])
def test_quantity_parser_and_evidence_share_spoken_and_numeric_units(phrase, quantity):
    from app.mcp_servers.mcp_shared.consultation import requested_quantity
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    item = product('SKU-NOVA', 'Đèn Nova Lumi')
    s = state(f'Báo giá {phrase} Nova Lumi.', [item])
    s['tool_calls'] += [{'name': 'pricing.get_quote',
        'args': {'sku': item['sku'], 'qty': n, 'on': '2028-03-17'},
        'result': {'sku': item['sku'], 'final_price_vnd': 100_000}}
        for n in (1, quantity)]
    assert requested_quantity(s) == quantity
    assert [c['args']['qty'] for c in build_commerce_evidence(s)
            if c['name'] == 'pricing.get_quote'] == [quantity]


@pytest.mark.parametrize('quantity', [2, 3])
def test_multiple_units_of_one_product_prepare_a_basket_quote(quantity):
    from app.agent.implementations.business_agent import BusinessTools
    from app.mcp_servers.mcp_shared.commerce_rules import quote_order
    item = product('SKU-NOVA', 'Đèn Nova Lumi')
    s = state(f'Báo giá {quantity} máy Nova Lumi.', [item])

    class Gateway:
        async def invoke(self, name, args):
            if name == 'pricing.quote_order':
                return quote_order([item], [], args)
            if name == 'pricing.get_quote':
                return {'sku': item['sku'], 'final_price_vnd': 100_000}
            return {'items': [item]}

    asyncio.run(BusinessTools(Gateway(), s, 10, datetime.now).prepare_consultation())
    quotes = [c for c in s['tool_calls'] if c['name'] == 'pricing.quote_order']
    assert len(quotes) == 1 and len(quotes[0]['result']['units']) == quantity


@pytest.mark.parametrize('phrase,expected', [('mười một chiếc', 11), ('hai mươi ba máy', 23),
                                            ('một trăm linh năm bộ', 105)])
def test_compound_spoken_quantity_is_not_truncated_to_last_digit(phrase, expected):
    from app.mcp_servers.mcp_shared.consultation import requested_quantity
    assert requested_quantity({'safe_text': phrase}) == expected


def test_basket_preparation_resolves_selected_variants_from_metadata():
    from app.agent.implementations.business_agent import BusinessTools
    from app.mcp_servers.mcp_shared.commerce_rules import quote_order
    item = product('SKU-NOVA', 'Giày Nova Lumi')
    item['variants'] = [{'variant_sku': 'SKU-NOVA-VIOLET', 'size': '38.5', 'color': 'tím',
                         'price_delta_vnd': 0},
                        {'variant_sku': 'SKU-NOVA-BLUE', 'size': '39', 'color': 'xanh',
                         'price_delta_vnd': 0}]
    s = state('Báo giá 3 đôi Nova Lumi size 38.5 màu tím.', [item])

    class Gateway:
        async def invoke(self, name, args):
            if name == 'pricing.quote_order':
                return quote_order([item], [], args)
            if name == 'pricing.get_quote':
                return {'sku': args['sku'], 'final_price_vnd': 100_000}
            return {'items': [item]}

    asyncio.run(BusinessTools(Gateway(), s, 10, datetime.now).prepare_consultation())
    quotes = [c for c in s['tool_calls'] if c['name'] == 'pricing.quote_order']
    assert len(quotes) == 1
    assert quotes[0]['args']['lines'] == [{'sku': 'SKU-NOVA-VIOLET', 'qty': 3}]


def test_variant_selection_uses_longest_catalog_value_for_decimal_size_and_color():
    from app.agent.harness.policy import resolve_product_selection
    item = product('SKU-NOVA', 'Giày Nova Lumi')
    item['variants'] = [{'variant_sku': 'SKU-NOVA-EXACT', 'size': '38.5', 'color': 'xanh dương'},
                        {'variant_sku': 'SKU-NOVA-SHORT', 'size': '38', 'color': 'xanh'}]
    s = state('Nova Lumi size 38.5 màu xanh dương.', [item])
    assert resolve_product_selection(s, {'sku': item['sku']}).sku == 'SKU-NOVA-EXACT'
    assert resolve_claim_skus(s['safe_text'], s['tool_calls']) == {'SKU-NOVA-EXACT'}


def test_unspecified_variant_is_not_confused_with_vietnamese_words_co_or_mau():
    item = product('SKU-NOVA', 'Giày Nova Lumi')
    item['variants'] = [{'variant_sku': 'SKU-NOVA-38', 'size': '38', 'color': 'tím'},
                        {'variant_sku': 'SKU-NOVA-39', 'size': '39', 'color': 'xanh'}]
    s = state('Mẫu Nova Lumi có giá bao nhiêu?', [item])
    assert resolve_claim_skus(s['safe_text'], s['tool_calls']) == {'SKU-NOVA', 'SKU-NOVA-38', 'SKU-NOVA-39'}
