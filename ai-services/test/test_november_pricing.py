"""Offline differential checks against the November BTC reference implementation."""
import json
from pathlib import Path
from types import ModuleType

import pytest
from app.mcp_servers.mcp_shared import commerce_rules

ROOT = Path(__file__).resolve().parents[2]
BTC = ROOT.parent / 'BTC-Data-Vong1-TEAMS'
PATCH = ROOT / 'BTC-cap-nhat-11-2026'


@pytest.fixture
def reference():
    # November is a partial patch: load its exact code against the original catalog.
    module = ModuleType('november_mock')
    module.__file__ = str(BTC / 'eval/mock_tools.py')
    source = PATCH / 'eval/mock_tools.py'
    exec(compile(source.read_bytes(), str(source), 'exec'), module.__dict__)
    return module


@pytest.mark.parametrize('lines,on,address,owned', [
    ([{'sku': 'SKU-AP-PRO', 'qty': 2}], '2026-10-15', None, False),
    ([{'sku': 'SKU-AP-PRO', 'qty': 3}], '2026-10-15', None, False),
    ([{'sku': 'SKU-SS-AX40'}, {'sku': 'SKU-AP-X'}], '2026-10-15', None, False),
    ([{'sku': 'SKU-AP-PRO', 'qty': 2}], '2026-10-15', None, True),
    ([{'sku': 'SKU-AP-X', 'qty': 2}], '2026-11-02', 'Hồ Chí Minh', False),
    ([{'sku': 'SKU-SN-RUN2-43-DEN', 'qty': 1}], '2026-10-15', None, False),
])
def test_basket_prices_match_november(reference, lines, on, address, owned):
    customer = next(c for c in reference.CRM if any(o['sku'] == 'SKU-AP-X-2024'
                    for o in c.get('orders', []))) if owned else None
    phone = customer['phone'] if customer else None
    owned_skus = {o['sku'] for o in customer['orders'] if o.get('status') == 'delivered'} if customer else set()
    expected = reference.pricing_quote_order(lines, on=on, address=address, customer_phone=phone)
    actual = commerce_rules.quote_order(reference.PRODUCTS, reference.PROMOS,
        {'lines': lines, 'on': on, 'address': address, 'customer_phone': phone}, owned_skus)
    for key in ('units', 'lines', 'total_vnd', 'order_promos', 'freeship'):
        assert actual[key] == expected[key]


def test_equal_price_single_quote_requires_basket_tool(reference):
    args = {'sku': 'SKU-AP-PRO', 'on': '2026-10-15', 'basket_skus': ['SKU-AP-PRO']}
    actual = commerce_rules.quote(reference.PRODUCTS, reference.PROMOS, args)
    expected = reference.pricing_get_quote(**args)
    assert actual['final_price_vnd'] == expected['final_price_vnd']
    assert actual['ineligible_promos'] == expected['ineligible_promos']


@pytest.mark.parametrize('lines', [[], [{'sku': 'SKU-AP-PRO', 'qty': 0}],
    [{'sku': 'SKU-AP-PRO', 'qty': -1}], [{'sku': 'SKU-AP-PRO', 'qty': True}]])
def test_invalid_basket_cannot_produce_quote(reference, lines):
    assert commerce_rules.quote_order(reference.PRODUCTS, reference.PROMOS,
        {'lines': lines, 'on': '2026-10-15'})['error'] == 'invalid_lines'


def test_unknown_basket_sku(reference):
    assert commerce_rules.quote_order(reference.PRODUCTS, reference.PROMOS,
        {'lines': [{'sku': 'SKU-UNKNOWN'}], 'on': '2026-10-15'})['error'] == 'unknown_sku'


def test_catalog_mcp_routes_basket_quote_with_trusted_identity(reference):
    import asyncio
    from contextlib import asynccontextmanager
    from app.agent.mcp.gateway import MCPGateway
    from app.mcp_servers.mcp_catalog.tools.handlers import create_server

    class Repo:
        @asynccontextmanager
        async def transaction(self):
            yield None

        async def rows(self, session, table):
            return {'products': reference.PRODUCTS, 'promotions': reference.PROMOS,
                    'inventory_events': reference.INV, 'customers': reference.CRM}[table]

        async def used_promos(self, session):
            return set()

        async def same_day_orders(self, session, phone, on):
            return []

        async def identity_matches(self, session, channel, identity):
            customer = next(c for c in reference.CRM if c.get(channel == 'hotline' and 'phone' or 'zalo_id') == identity)
            return [{'customer_id': customer['customer_id'], 'phone': customer['phone']}]

    customer = next(c for c in reference.CRM if any(o['sku'] == 'SKU-AP-X-2024' for o in c.get('orders', [])))
    args = {'lines': [{'sku': 'SKU-AP-PRO', 'qty': 2}], 'on': '2026-10-15', 'customer_phone': customer['phone']}
    gateway = MCPGateway(create_server(Repo()), None, None)
    actual = asyncio.run(gateway.invoke_trusted('pricing.quote_order', args, customer['customer_id'],
                                                channel='hotline', channel_identity=customer['phone']))
    assert actual.get('units') == reference.pricing_quote_order(**args)['units']


@pytest.mark.parametrize('payload', [
    {'lines': [{'sku': 'SKU-AP-PRO', 'qty': 1, 'price_vnd': 100}], 'sku': 'SKU-AP-X'},
    {'lines': []}, {'lines': [{'sku': 'SKU-AP-PRO', 'qty': 0, 'price_vnd': 100}]},
    {'lines': [{'sku': 'SKU-AP-PRO', 'qty': 1}]}, {},
])
def test_order_rejects_missing_or_ambiguous_lines(payload):
    from pydantic import ValidationError
    from app.mcp_servers.mcp_order.schemas import CreateInput
    with pytest.raises(ValidationError):
        CreateInput.model_validate({'customer_phone': '0900000000', 'payment': 'bank',
                                    'on': '2026-10-15', **payload})


def test_order_accepts_per_unit_lines():
    from app.mcp_servers.mcp_order.schemas import CreateInput
    lines = [{'sku': 'SKU-AP-PRO', 'qty': 1, 'price_vnd': price} for price in (100, 50)]
    request = CreateInput.model_validate({'customer_phone': '0900000000', 'payment': 'bank',
                                        'on': '2026-10-15', 'lines': lines})
    assert request.model_dump(mode='json', exclude_none=True)['lines'] == lines


class OrderRepo:
    def __init__(self, reference):
        self.reference = reference
        self.orders = []
        self.used = set()
        self.operations = {}
        self.phone = '0984726714'

    def transaction(self):
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def transaction():
            yield None
        return transaction()

    async def identity_matches(self, *args):
        return [{'customer_id': 'C001', 'phone': self.phone}]

    async def rows(self, session, table):
        return {'products': self.reference.PRODUCTS, 'promotions': self.reference.PROMOS,
                'inventory_events': self.reference.INV, 'customers': []}[table]

    async def used_promos(self, session):
        return self.used

    async def same_day_orders(self, session, phone, on):
        return [order for order in self.orders if order['customer_phone'] == phone and order['on'] == on]

    async def next_order_id(self, session):
        return f'OD{600001 + len(self.orders)}'

    async def insert_order(self, session, order_id, customer_id, args, price, total, codes):
        self.orders.append({**args, 'order_id': order_id, 'promos': codes, 'total_vnd': total})

    async def use_promo(self, session, phone, code):
        self.used.add((phone, code))

    async def claim_operation(self, session, key, name, digest):
        if key not in self.operations:
            self.operations[key] = (digest, None)
        old, result = self.operations[key]
        return result if old == digest else {'error': 'operation_key_conflict'}

    async def finish_operation(self, session, key, result):
        self.operations[key] = (self.operations[key][0], result)

    async def lock_customer(self, session, phone):
        pass


def test_basket_quote_matches_create_after_same_day_promotion_use(reference):
    import asyncio
    from app.mcp_servers.mcp_catalog.services.catalog import get_quote_order
    from app.mcp_servers.mcp_order.services.order import create
    async def run():
        repo = OrderRepo(reference)
        payload = {'lines': [{'sku': 'SKU-AP-PRO', 'qty': 2}], 'on': '2026-10-15',
                   'customer_phone': repo.phone, 'source_channel': 'hotline',
                   'source_identity': repo.phone, 'payment': 'bank'}
        first = await get_quote_order(repo, None, payload)
        def order_args(quote):
            return {**payload, 'lines': [{'sku': unit['sku'], 'qty': 1,
                    'price_vnd': unit['final_price_vnd']} for unit in quote['units']]}
        assert (await create(repo, None, order_args(first), 'C001', repo.phone))['status'] == 'created'
        refreshed = await get_quote_order(repo, None, payload)
        assert refreshed['total_vnd'] > first['total_vnd']
        assert (await create(repo, None, order_args(refreshed), 'C001', repo.phone))['status'] == 'created'
    asyncio.run(run())


def test_multiline_order_persists_unit_prices_and_replay(reference):
    import asyncio
    from app.mcp_servers.mcp_order.tools.handlers import invoke
    repo = OrderRepo(reference)
    q = reference.pricing_quote_order([{'sku': 'SKU-AP-PRO', 'qty': 2}])
    lines = [{'sku': unit['sku'], 'qty': 1, 'price_vnd': unit['final_price_vnd']} for unit in q['units']]
    args = {'customer_phone': repo.phone, 'lines': lines, 'payment': 'bank', 'on': '2026-10-15',
            'source_channel': 'hotline', 'source_identity': repo.phone, 'operation_key': 'one-order'}
    async def run():
        first = await invoke(repo, 'order.create', args)
        assert first.get('status') == 'created', first
        assert first['total_vnd'] == q['total_vnd']
        assert await invoke(repo, 'order.create', args) == first
    asyncio.run(run())
    assert len(repo.orders) == 1
    assert repo.orders[0]['lines'] == lines


@pytest.mark.parametrize('change,error', [('wrong_price', 'price_mismatch'),
    ('cod', 'cod_limit_exceeded'), ('aggregate_stock', 'out_of_stock')])
def test_basket_order_rejects_invalid_transaction_without_side_effects(reference, change, error):
    import asyncio
    from app.mcp_servers.mcp_order.tools.handlers import invoke
    repo = OrderRepo(reference)
    q = reference.pricing_quote_order([{'sku': 'SKU-AP-PRO', 'qty': 2}])
    lines = [{'sku': unit['sku'], 'qty': 1, 'price_vnd': unit['final_price_vnd']} for unit in q['units']]
    if change == 'wrong_price':
        lines[1]['price_vnd'] += 1
    if change == 'aggregate_stock':
        reference.INV.append({'sku': 'SKU-AP-PRO', 'date': '2026-10-15', 'qty': 1})
    result = asyncio.run(invoke(repo, 'order.create', {'customer_phone': repo.phone, 'lines': lines,
        'payment': 'COD' if change == 'cod' else 'bank', 'on': '2026-10-15',
        'source_channel': 'hotline', 'source_identity': repo.phone}))
    assert result.get('error') == error, result
    assert repo.orders == [] and repo.used == set()


def test_split_orders_only_discount_one_unit_per_customer_day(reference):
    import asyncio
    from app.mcp_servers.mcp_order.tools.handlers import invoke
    repo = OrderRepo(reference)
    common = {'customer_phone': repo.phone, 'payment': 'bank', 'on': '2026-10-15',
              'source_channel': 'hotline', 'source_identity': repo.phone,
              'sku': 'SKU-AP-PRO', 'qty': 1, 'basket_skus': ['SKU-AP-PRO']}
    reference._ORDERS.clear()
    reference._ONCE_USED.clear()
    regular = reference.pricing_get_quote('SKU-AP-PRO')['final_price_vnd']
    discounted = reference.pricing_quote_order([{'sku': 'SKU-AP-PRO', 'qty': 2}])['units'][1]['final_price_vnd']
    async def run():
        for price in (regular, discounted, regular):
            args = {**common, 'price_vnd': price}
            expected = reference.order_create(**{k: v for k, v in args.items() if not k.startswith('source_')})
            actual = await invoke(repo, 'order.create', args)
            assert actual.get('status') == expected.get('status') == 'created', actual
            assert actual['total_vnd'] == expected['total_vnd']
    asyncio.run(run())
    assert sum('AIR-2ND-50' in order['promos'] for order in repo.orders) == 1


def test_same_sku_aggregate_price_cannot_hide_wrong_per_unit_prices(reference):
    import asyncio
    from app.mcp_servers.mcp_order.tools.handlers import invoke
    repo = OrderRepo(reference)
    q = reference.pricing_quote_order([{'sku': 'SKU-AP-PRO', 'qty': 2}])
    prices = [unit['final_price_vnd'] for unit in q['units']]
    prices[0] -= 1
    prices[1] += 1
    result = asyncio.run(invoke(repo, 'order.create', {'customer_phone': repo.phone,
        'lines': [{'sku': 'SKU-AP-PRO', 'qty': 1, 'price_vnd': price} for price in prices],
        'payment': 'bank', 'on': '2026-10-15', 'source_channel': 'hotline', 'source_identity': repo.phone}))
    assert result.get('error') == 'price_mismatch'
    assert repo.orders == []


def test_multiline_order_through_actual_mcp_server(reference):
    import asyncio
    from app.agent.mcp.gateway import MCPGateway
    from app.mcp_servers.mcp_order.tools.handlers import create_server
    repo = OrderRepo(reference)
    q = reference.pricing_quote_order([{'sku': 'SKU-AP-PRO', 'qty': 2}])
    args = {'customer_phone': repo.phone, 'payment': 'bank', 'on': '2026-10-15',
            'lines': [{'sku': u['sku'], 'qty': 1, 'price_vnd': u['final_price_vnd']} for u in q['units']]}
    gateway = MCPGateway(None, create_server(repo), None)
    result = asyncio.run(gateway.invoke_trusted('order.create', args, 'C001',
        channel='hotline', channel_identity=repo.phone, operation_key='mcp-lines'))
    assert result.get('status') == 'created', result
    assert result['total_vnd'] == q['total_vnd']
    assert repo.orders[0]['lines'] == args['lines']
