import asyncio
from copy import deepcopy

import pytest

from app.agent.mcp.gateway import MCPGateway
from app.mcp_servers.mcp_order.services import order
from app.mcp_servers.mcp_order.tools.handlers import create_server
from test_order_update_lines import Repo


@pytest.fixture
def repo():
    instance = Repo()
    try:
        yield instance
    finally:
        instance.close()


def preview(repo, **extra):
    return asyncio.run(order.preview_update(repo, repo.session, {
        'order_id': 'LINE-ORDER', 'action': 'return', 'on': '2034-06-08', **extra}, 'OWNER-LINES'))


def test_return_preview_uses_paid_lines_and_writes_nothing(repo):
    before = deepcopy(repo.order)
    full = preview(repo)
    assert full['status'] == 'preview' and full['estimate'] is True
    assert full['refund_vnd'] == full['estimated_total_refund_vnd'] == 290000
    assert full['estimated_total_payment_vnd'] == 0 and full['requires_policy_check'] is True
    assert preview(repo, line_index=0, qty=1)['refund_vnd'] == 110000
    assert not asyncio.run(repo.order_updates(repo.session, 'LINE-ORDER'))
    assert not repo.operations and repo.order == before


def test_exchange_preview_matches_execution_and_includes_net_fee_and_stock(repo):
    async def fee_count(*args):
        return 1
    repo.exchange_count = fee_count
    args = {'action': 'exchange_product', 'line_index': 0, 'qty': 2, 'new_variant_sku': 'ITEM-NEW'}
    result = preview(repo, **args)
    assert result['refund_vnd'] == 30000 and result['fee_vnd'] == 60000
    assert result['estimated_total_payment_vnd'] == 30000 and result['estimated_total_refund_vnd'] == 0
    assert result['replacement_inventory']['qty'] == 9
    assert not asyncio.run(repo.order_updates(repo.session, 'LINE-ORDER'))
    written = asyncio.run(order.update(repo, repo.session, {'order_id': 'LINE-ORDER', 'on': '2034-06-08', **args}, 'OWNER-LINES'))
    for field in ('fee_vnd', 'price_diff_vnd', 'refund_vnd', 'extra_payment_vnd', 'selected_lines', 'replacement_lines'):
        assert written[field] == result[field]


@pytest.mark.parametrize('args,error', [
    ({'qty': 1}, 'order_line_required'), ({'line_index': 9}, 'invalid_order_line'),
    ({'line_index': 0, 'qty': 3}, 'invalid_update_quantity'),
    ({'action': 'exchange_product', 'new_variant_sku': 'ITEM-NEW'}, 'order_line_required'),
])
def test_invalid_preview_returns_no_request(repo, args, error):
    assert preview(repo, **args)['error'] == error
    assert not asyncio.run(repo.order_updates(repo.session, 'LINE-ORDER'))


def test_execution_recomputes_stock_after_a_preview(repo):
    args = {'action': 'exchange_product', 'line_index': 0, 'qty': 2, 'new_variant_sku': 'ITEM-NEW'}
    assert preview(repo, **args)['status'] == 'preview'
    repo.stock = 1
    result = asyncio.run(order.update(repo, repo.session, {'order_id': 'LINE-ORDER', 'on': '2034-06-08', **args}, 'OWNER-LINES'))
    assert result['error'] == 'new_variant_out_of_stock'
    assert not asyncio.run(repo.order_updates(repo.session, 'LINE-ORDER'))


def test_signed_shared_phone_preview_is_scoped_and_never_claims_an_operation():
    class Shared(Repo):
        async def identity_matches(self, *args):
            return [{'customer_id': owner, 'phone': '0900000061'} for owner in ('OWNER-LINES', 'OTHER')]

        async def claim_operation(self, *args):
            raise AssertionError('Preview must not claim an operation')

        async def finish_operation(self, *args):
            raise AssertionError('Preview must not finish an operation')

        async def lock_customer(self, *args):
            raise AssertionError('Preview must not acquire a write lock')

    async def run():
        instance = Shared()
        try:
            gateway = MCPGateway(None, create_server(instance, context_secret='preview-secret'), None, context_secret='preview-secret')
            args = {'order_id': 'LINE-ORDER', 'action': 'return', 'on': '2034-06-08', 'operation_key': 'forged'}
            result = await gateway.invoke_trusted('order.preview_update', args, 'OWNER-LINES', 'hotline', '0900000061')
            assert result.get('status') == 'preview', result
            assert result['refund_vnd'] == 290000
            foreign = await gateway.invoke_trusted('order.preview_update', args, 'OTHER', 'hotline', '0900000061')
            assert foreign.get('error') == 'order_not_owned'
            unknown = await gateway.invoke_trusted('order.preview_update', args, None, 'hotline', '0900000061')
            assert unknown.get('error') == 'identity_required'
            assert not await instance.order_updates(instance.session, 'LINE-ORDER')
            denied = await gateway.invoke_trusted('order.update', args, 'OWNER-LINES', 'hotline', '0900000061')
            assert denied['error'] == 'write_authorization_required'
        finally:
            instance.close()
    asyncio.run(run())


def test_preview_identity_proof_binds_selection_date_and_replacement(repo):
    from app.mcp_servers.mcp_shared.identity import sign_identity
    from app.mcp_servers.mcp_order.tools.handlers import invoke
    args = {'order_id': 'LINE-ORDER', 'action': 'return', 'on': '2034-06-08',
            'line_index': 0, 'qty': 1, 'source_channel': 'hotline', 'source_identity': '0900000061'}
    proof = sign_identity('order.preview_update', args, 'OWNER-LINES', 'preview-secret')
    for change in [{'qty': 2}, {'line_index': 1}, {'on': '2034-06-09'},
                   {'action': 'exchange_product', 'new_variant_sku': 'ITEM-NEW'}]:
        result = asyncio.run(invoke(repo, 'order.preview_update', args | change | {'trusted_identity': proof}, context_secret='preview-secret'))
        assert result['error'] == 'identity_required'
    assert not repo.operations and not asyncio.run(repo.order_updates(repo.session, 'LINE-ORDER'))


def test_read_service_ignores_operation_keys_without_writing(repo):
    args = {'order_id': 'LINE-ORDER', 'action': 'return', 'on': '2034-06-08',
            'operation_key': 'must-not-create-a-journal-entry',
            'source_channel': 'hotline', 'source_identity': '0900000061'}
    assert asyncio.run(order.invoke(repo, 'order.preview_update', args))['status'] == 'preview'
    assert not repo.operations and not asyncio.run(repo.order_updates(repo.session, 'LINE-ORDER'))


def test_execution_reprices_after_a_preview(repo):
    rows = repo.rows
    price = [95000]
    async def changed(session, table):
        result = await rows(session, table)
        if table == 'products':
            result[0]['list_price_vnd'] = price[0]
        return result
    repo.rows = changed
    args = {'action': 'exchange_product', 'line_index': 0, 'qty': 1, 'new_variant_sku': 'ITEM-NEW'}
    assert preview(repo, **args)['refund_vnd'] == 15000
    price[0] = 125000
    written = asyncio.run(order.update(repo, repo.session, {'order_id': 'LINE-ORDER', 'on': '2034-06-08', **args}, 'OWNER-LINES'))
    assert written['refund_vnd'] == 0 and written['extra_payment_vnd'] == 15000
