import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.mcp_servers.mcp_order.repos.postgres import OrderRepo
from app.mcp_servers.mcp_order.schemas import UpdateInput
from app.mcp_servers.mcp_order.services.order import status, update


class Session:
    def __init__(self, connection):
        self.connection = connection

    async def execute(self, sql, args):
        query = str(sql).replace('CAST(:result AS jsonb)', ':result')
        return list(self.connection.execute(query, args))


class Repo:
    def __init__(self, order=None):
        self.connection = sqlite3.connect(':memory:')
        self.connection.execute("ATTACH DATABASE ':memory:' AS runtime")
        self.connection.execute('CREATE TABLE runtime.tool_updates(id INTEGER PRIMARY KEY,order_id TEXT,action TEXT,result TEXT)')
        self.session = Session(self.connection)
        self.order = order or {'order_id': 'LINE-ORDER', 'customer_phone': '0900000061',
            'sku': 'ITEM-A', 'qty': 3, 'price_vnd': 110000, 'total_vnd': 290000,
            'lines': [{'sku': 'ITEM-A', 'qty': 2, 'price_vnd': 110000},
                      {'sku': 'ITEM-B', 'qty': 1, 'price_vnd': 70000}], 'status': 'delivered',
            'created_on': '2034-06-01', 'received_on': '2034-06-05'}
        self.stock = 9
        self.promotions = []
        self.operations = {}

    @asynccontextmanager
    async def transaction(self):
        with self.connection:
            yield self.session

    async def identity_matches(self, *args):
        return [{'customer_id': 'OWNER-LINES', 'phone': '0900000061'}]

    async def lock_customer(self, *args):
        pass

    async def claim_operation(self, session, key, name, digest):
        old = self.operations.get(key)
        if old and old[:2] != (name, digest):
            return {'error': 'operation_key_conflict'}
        if old:
            return deepcopy(old[2])
        self.operations[key] = (name, digest, None)

    async def finish_operation(self, session, key, result):
        self.operations[key] = (*self.operations[key][:2], deepcopy(result))

    async def order_owned(self, session, order_id, customer_id):
        return order_id == 'LINE-ORDER' and customer_id == 'OWNER-LINES'

    async def rows(self, session, table):
        return {'customers': [], 'inventory_events': [], 'promotions': self.promotions, 'products': [{
            'sku': 'ITEM-NEW', 'name': 'Replacement', 'stock': self.stock, 'list_price_vnd': 95000,
            'attributes': {}, 'variants': []}]}[table]

    async def runtime_orders(self, session, customer_id, order_id):
        return [deepcopy(self.order)]

    async def order_updates(self, session, order_id):
        return await OrderRepo.order_updates(self, self.session, order_id)

    async def insert_update(self, session, order_id, action, result):
        await OrderRepo.insert_update(self, self.session, order_id, action, result)

    async def exchange_count(self, *args):
        return 0

    async def used_promos(self, *args):
        return set()

    def close(self):
        self.connection.close()


@pytest.fixture
def repo():
    instance = Repo()
    try:
        yield instance
    finally:
        instance.close()


def perform(repo, action='return', **args):
    return asyncio.run(update(repo, repo.session, {'order_id': 'LINE-ORDER',
        'action': action, 'on': '2034-06-08', **args}, 'OWNER-LINES'))


def test_full_return_uses_all_paid_lines_and_units(repo):
    result = perform(repo)
    assert result['refund_vnd'] == 290000
    assert result['selected_lines'] == [
        {'line_index': 0, 'sku': 'ITEM-A', 'qty': 2, 'price_vnd': 110000},
        {'line_index': 1, 'sku': 'ITEM-B', 'qty': 1, 'price_vnd': 70000}]


@pytest.mark.parametrize('line,qty,refund', [(0, 1, 110000), (0, 2, 220000), (1, 1, 70000)])
def test_partial_return_selects_the_exact_line_and_quantity(repo, line, qty, refund):
    result = perform(repo, line_index=line, qty=qty)
    assert result['refund_vnd'] == refund and result['selected_lines'][0]['qty'] == qty


@pytest.mark.parametrize('args,error', [
    ({'qty': 1}, 'order_line_required'), ({'line_index': 9}, 'invalid_order_line'),
    ({'line_index': 0, 'qty': 3}, 'invalid_update_quantity'),
    ({'line_index': 0, 'qty': 0}, 'invalid_update_quantity'),
])
def test_invalid_or_ambiguous_return_writes_no_request(repo, args, error):
    assert perform(repo, **args).get('error') == error
    assert repo.connection.execute('SELECT count(*) FROM runtime.tool_updates').fetchone()[0] == 0


def test_multiline_exchange_requires_target_and_uses_selected_quantity(repo):
    assert perform(repo, 'exchange_product', new_variant_sku='ITEM-NEW').get('error') == 'order_line_required'
    result = perform(repo, 'exchange_product', new_variant_sku='ITEM-NEW', line_index=0, qty=2)
    assert result['price_diff_vnd'] == -30000 and result['refund_vnd'] == 30000
    assert result['selected_lines'][0]['qty'] == 2


def test_exchange_checks_stock_for_all_requested_units(repo):
    repo.stock = 1
    assert perform(repo, 'exchange_product', new_variant_sku='ITEM-NEW', line_index=0, qty=2).get('error') == 'new_variant_out_of_stock'
    assert not asyncio.run(repo.order_updates(repo.session, 'LINE-ORDER'))


def test_exchange_quotes_the_selected_quantity_as_a_basket(repo):
    repo.promotions = [{'promo_code': 'SECOND-UNIT', 'type': 'percent_second_item',
        'applies_to': ['ITEM-NEW'], 'discount_percent': 50, 'stackable': False,
        'start': '2034-01-01', 'end': '2034-12-31', 'conditions': {'min_qty': 2}}]
    result = perform(repo, 'exchange_product', new_variant_sku='ITEM-NEW', line_index=0, qty=2)
    assert result['price_diff_vnd'] == -77500 and result['refund_vnd'] == 77500


def test_address_projection_does_not_mutate_a_crm_source_record(repo):
    source = deepcopy(repo.order)
    original_rows = repo.rows

    async def rows(session, table):
        if table == 'customers':
            return [{'customer_id': 'OWNER-LINES', 'orders': [source]}]
        return await original_rows(session, table)

    repo.rows = rows

    async def no_runtime(*args):
        return []

    repo.runtime_orders = no_runtime
    perform(repo, 'update_address', address='Changed delivery location')
    assert source == repo.order


def test_legacy_single_unit_order_still_returns_its_paid_amount(repo):
    repo.order = {'order_id': 'LINE-ORDER', 'sku': 'LEGACY', 'price_vnd': 123000, 'status': 'delivered'}
    assert perform(repo)['refund_vnd'] == 123000


def test_per_unit_lines_without_qty_mean_one_unit_each(repo):
    repo.order['lines'] = [{'sku': 'ITEM-A', 'price_vnd': 110000},
                           {'sku': 'ITEM-A', 'price_vnd': 90000}]
    repo.order['total_vnd'] = 200000
    result = perform(repo)
    assert result['refund_vnd'] == 200000
    assert [line['qty'] for line in result['selected_lines']] == [1, 1]
    repo.order['lines'][0]['qty'] = None
    assert perform(repo).get('error') == 'order_data_inconsistent'


def test_json_encoded_lines_are_decoded_and_inconsistent_totals_are_rejected(repo):
    repo.order['lines'] = json.dumps(repo.order['lines'])
    assert perform(repo)['refund_vnd'] == 290000
    repo.order['total_vnd'] = 1
    assert perform(repo).get('error') == 'order_data_inconsistent'


def test_delivery_address_survives_the_schema_journal_and_subsequent_owned_read(repo):
    original = deepcopy(repo.order)
    args = UpdateInput.model_validate({'order_id': 'LINE-ORDER', 'action': 'update_address',
        'address': 'Delivery location supplied by customer', 'on': '2034-06-08'}).model_dump(mode='json', exclude_none=True)
    assert args['address'] == 'Delivery location supplied by customer'
    result = asyncio.run(update(repo, repo.session, args, 'OWNER-LINES'))
    assert result['status'] == 'updated'
    loaded = asyncio.run(status(repo, repo.session, {'order_id': 'LINE-ORDER'}, 'OWNER-LINES'))
    assert loaded['orders'][0]['address'] == args['address']
    assert repo.order == original
    assert asyncio.run(status(repo, repo.session, {'order_id': 'LINE-ORDER'}, 'FOREIGN')).get('error') == 'order_not_owned'


@pytest.mark.parametrize('fields', [{}, {'address': ''}, {'address': '   '}])
def test_address_update_requires_a_nonblank_new_address(fields):
    with pytest.raises(ValidationError):
        UpdateInput.model_validate({'order_id': 'LINE-ORDER', 'action': 'update_address',
            'on': '2034-06-08', **fields})


@pytest.mark.parametrize('args', [
    {'action': 'return', 'line_index': 0, 'qty': 1},
    {'action': 'update_address', 'address': 'Customer supplied destination'},
])
def test_model_tool_passes_selected_units_and_address_through_signed_mcp_and_replay(repo, args):
    from unittest.mock import AsyncMock
    from test_write_authorization import business, current

    async def run():
        state = current('Thực hiện đúng thay đổi đơn đang trao đổi giúp tôi.')
        state.update(customer_id='OWNER-LINES', customer_phone='0900000061', owned_order_ids=['LINE-ORDER'])
        state['request'] = state['request'].model_copy(update={'channel_identity': '0900000061'})
        reviewer = AsyncMock(return_value=True)
        tools = business(state, repo, reviewer)
        tool = next(tool for tool in tools.langchain_tools() if tool.name == 'order_update')
        payload = {'order_id': 'LINE-ORDER', **args}
        first = await tool.ainvoke(payload)
        assert 'error' not in first
        assert await tool.ainvoke(payload) == first
        assert reviewer.await_count == 1
        assert repo.connection.execute('SELECT count(*) FROM runtime.tool_updates').fetchone()[0] == 1
        if args['action'] == 'return':
            assert first['refund_vnd'] == 110000
            assert reviewer.await_args.args[1]['qty'] == 1
        else:
            loaded = await tools.gateway.invoke_trusted('order.status', {'order_id': 'LINE-ORDER'},
                'OWNER-LINES', 'hotline', '0900000061')
            assert loaded['orders'][0]['address'] == args['address']
            assert 'address' not in first
    asyncio.run(run())
