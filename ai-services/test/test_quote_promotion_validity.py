import asyncio
from copy import deepcopy

from app.mcp_servers.mcp_catalog.services.catalog import get_quote_order, get_quote
from app.mcp_servers.mcp_shared.commerce_rules import quote_order
from app.mcp_servers.mcp_shared.memory_observations import memory_observations


class Repo:
    def __init__(self):
        self.products = [{'sku': 'LAB', 'name': 'Device', 'category': 'test', 'brand': 'Lab',
            'list_price_vnd': 120000, 'stock': 5, 'attributes': {}, 'variants': []}]
        self.promos = [dict(promo_code='LAB-DISCOUNT', name='Discount', type='percent',
            discount_percent=10, start='2032-04-01', end='2032-04-12', applies_to=['LAB']),
            dict(promo_code='LAB-SHIP', name='Shipping', type='freeship', stackable=True,
                 start='2032-04-01', end='2032-04-20', applies_to=['LAB'])]

    async def identity_matches(self, *args):
        return []

    async def rows(self, session, table):
        return {'products': self.products, 'promotions': self.promos, 'inventory_events': []}[table]

    async def used_promos(self, session):
        return set()


def test_basket_and_single_promotions_have_source_expiry_and_preserve_amounts():
    async def run():
        repo = Repo()
        original = deepcopy(repo.promos)
        args = {'lines': [{'sku': 'LAB', 'qty': 2}], 'on': '2032-04-09'}
        expected = quote_order(repo.products, repo.promos, args)
        result = await get_quote_order(repo, None, args)
        assert result['total_vnd'] == expected['total_vnd'] == 216000
        assert result['lines'] == expected['lines']
        assert result['units'][0]['applied_promos'][0]['valid_until'] == '2032-04-12'
        assert result['units'][1]['applied_promos'][0]['valid_until'] == '2032-04-12'
        assert result['order_promos'][0]['valid_until'] == '2032-04-20'
        single = await get_quote(repo, None, {'sku': 'LAB', 'on': args['on']})
        assert {p['promo_code']: p['valid_until'] for p in single['applied_promos']} == {
            'LAB-DISCOUNT': '2032-04-12', 'LAB-SHIP': '2032-04-20'}
        saved = memory_observations([{'name': 'pricing.quote_order', 'args': args, 'result': result}])[0]
        assert saved['result']['units'][1]['applied_promos'][0]['valid_until'] == '2032-04-12'
        assert saved['result']['order_promos'][0]['valid_until'] == '2032-04-20'
        assert repo.promos == original
    asyncio.run(run())
