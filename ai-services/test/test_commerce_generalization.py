"""Offline counterexamples independent of the published catalog and scenarios."""
import asyncio

import pytest

from app.mcp_servers.mcp_shared.commerce_rules import quote, quote_order

ON = '2028-03-17'


def product(sku, price=100_000, category='van-phong/den'):
    return {'sku': sku, 'name': f'Đèn Nova {sku}', 'brand': 'Nova',
            'category': category, 'list_price_vnd': price, 'stock': 20,
            'attributes': {}, 'variants': []}


def promotion(code='PAIR-SPRING', **changes):
    return {'promo_code': code, 'type': 'percent_second_item', 'discount_percent': 30,
            'applies_to': ['category:van-phong/den'], 'start': '2028-03-01',
            'end': '2028-03-31', 'stackable': False,
            'conditions': {'min_qty': 2}, **changes}


def basket(products, promos, **changes):
    return quote_order(products, promos, {'on': ON,
        'lines': [{'sku': p['sku']} for p in products], **changes})


def test_second_item_uses_promotion_scope_instead_of_air_purifier_category():
    products = [product('SKU-LAMP-A'), product('SKU-LAMP-B', 80_000),
                product('SKU-OTHER', 10_000, 'khac')]
    result = basket(products, [promotion()])
    assert [u['final_price_vnd'] for u in result['units']] == [100_000, 56_000, 10_000]


@pytest.mark.parametrize('changes', [
    {'conditions': {'min_qty': 3}},
    {'conditions': {'min_qty': 2, 'region': ['nam']}},
    {'conditions': {'min_qty': 2, 'requires_owned_sku': 'SKU-OLD-LAMP'}},
    {'end': '2028-03-16'},
])
def test_second_item_respects_promotion_conditions(changes):
    products = [product('SKU-A', category='gia-dung/may-loc-khong-khi'),
                product('SKU-B', category='gia-dung/may-loc-khong-khi')]
    promo = promotion(applies_to=['*'], **changes)
    assert basket(products, [promo])['total_vnd'] == 200_000


def test_multiple_second_item_promotions_apply_to_their_own_products():
    products = [product('SKU-A'), product('SKU-B'),
                product('SKU-C', category='khac'), product('SKU-D', category='khac')]
    result = basket(products, [promotion(), promotion('OTHER-PAIR', applies_to=['category:khac'],
                                                     discount_percent=20)])
    assert result['total_vnd'] == 350_000
    assert {p['promo_code'] for u in result['units'] for p in u['applied_promos']} == {'PAIR-SPRING', 'OTHER-PAIR'}


def test_freeship_uses_promotion_type_instead_of_code():
    result = basket([product('SKU-A')], [promotion('SHIP-NEW', type='freeship',
        stackable=True, conditions={})])
    assert result['freeship'] is True


def test_every_owned_product_promotion_is_allocated_once():
    products = [product('SKU-A'), product('SKU-B')]
    promos = [promotion('LOYAL-A', type='fixed', discount_vnd=10_000,
                        applies_to=['SKU-A'], conditions={'requires_owned_sku': 'SKU-OLD'}),
              promotion('LOYAL-B', type='fixed', discount_vnd=20_000,
                        applies_to=['SKU-B'], conditions={'requires_owned_sku': 'SKU-OLD'})]
    result = quote_order(products, promos, {'on': ON, 'lines': [
        {'sku': 'SKU-A', 'qty': 2}, {'sku': 'SKU-B', 'qty': 2}]}, {'SKU-OLD'})
    codes = [p['promo_code'] for u in result['units'] for p in u['applied_promos']]
    assert codes.count('LOYAL-A') == codes.count('LOYAL-B') == 1


def test_stackable_discounts_are_reflected_in_final_price():
    promos = [promotion('BASE', type='fixed', discount_vnd=10_000, conditions={}),
              promotion('EXTRA', type='fixed', discount_vnd=5_000, stackable=True, conditions={})]
    result = quote([product('SKU-A')], promos, {'on': ON, 'sku': 'SKU-A'})
    assert result['final_price_vnd'] == 85_000


def test_renamed_second_item_code_is_consumed_consistently_by_quote_and_create():
    from app.mcp_servers.mcp_catalog.services.catalog import get_quote_order
    from app.mcp_servers.mcp_order.services.order import create

    class Repo:
        def __init__(self):
            self.orders = []
            self.used = set()

        async def rows(self, session, table):
            return {'products': [product('SKU-A'), product('SKU-B')],
                    'promotions': [promotion()], 'customers': [], 'inventory_events': []}[table]

        async def identity_matches(self, *args):
            return [{'customer_id': 'customer', 'phone': '0900000000'}]

        async def same_day_orders(self, *args):
            return self.orders

        async def used_promos(self, *args):
            return self.used

        async def next_order_id(self, *args):
            return f'order-{len(self.orders)}'

        async def insert_order(self, session, order_id, customer_id, args, price, total, codes):
            self.orders.append({'promos': codes})

        async def use_promo(self, session, phone, code):
            self.used.add((phone, code))

    async def run():
        repo = Repo()
        payload = {'on': ON, 'customer_phone': '0900000000', 'payment': 'bank',
                   'lines': [{'sku': 'SKU-A'}, {'sku': 'SKU-B'}]}
        first = await get_quote_order(repo, None, payload)
        assert first['total_vnd'] == 170_000
        args = {**payload, 'lines': [{'sku': u['sku'], 'qty': 1,
                                     'price_vnd': u['final_price_vnd']} for u in first['units']]}
        assert (await create(repo, None, args, 'customer', payload['customer_phone']))['status'] == 'created'
        refreshed = await get_quote_order(repo, None, payload)
        assert refreshed['total_vnd'] == 200_000
        args['lines'] = [{'sku': u['sku'], 'qty': 1, 'price_vnd': u['final_price_vnd']}
                         for u in refreshed['units']]
        assert (await create(repo, None, args, 'customer', payload['customer_phone']))['status'] == 'created'
    asyncio.run(run())


def test_second_item_filters_ineligible_variants_before_choosing_cheapest():
    item = product('SKU-LAMP')
    item['variants'] = [{'variant_sku': f'SKU-LAMP-{size}', 'size': size, 'color': 'tím',
                         'price_delta_vnd': delta, 'stock': 20}
                        for size, delta in [(40, 30_000), (41, 20_000), (42, 0)]]
    result = quote_order([item], [promotion(conditions={'min_qty': 2, 'exclude_variant_size': [42]})],
        {'on': ON, 'lines': [{'sku': f'SKU-LAMP-{size}'} for size in (40, 41, 42)]})
    assert [u['final_price_vnd'] for u in result['units']] == [130_000, 84_000, 100_000]


def test_second_item_once_per_customer_is_not_bypassed_by_basket_pricing():
    products = [product('SKU-A'), product('SKU-B')]
    promo = promotion(conditions={'min_qty': 2, 'once_per_customer': True})
    result = quote_order(products, [promo], {'on': ON, 'customer_phone': '0900000000',
        'lines': [{'sku': p['sku']} for p in products]}, once_used={('0900000000', promo['promo_code'])})
    assert result['total_vnd'] == 200_000


def test_category_target_does_not_match_sibling_category_prefix():
    item = product('SKU-A', category='van-phong/den-trang-tri')
    result = quote([item], [promotion(type='fixed', discount_vnd=10_000, conditions={})],
                   {'sku': 'SKU-A', 'on': ON})
    assert result['applied_promos'] == []
