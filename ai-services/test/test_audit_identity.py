import asyncio
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest

from app.agent.harness.session_identity import initialize_identity
from app.agent.mcp.gateway import MCPGateway
from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
from test_write_authorization import OrderRepo, SECRET, current, proposal, wire


@pytest.mark.parametrize('kind', ['catalog', 'order'])
def test_numeric_chat_identity_cannot_fall_back_to_phone_at_repository_boundary(kind):
    from app.mcp_servers.mcp_catalog.repos.postgres import CatalogRepo
    from app.mcp_servers.mcp_order.repos.postgres import OrderRepo as SQLOrderRepo
    cls = CatalogRepo if kind == 'catalog' else SQLOrderRepo
    repo = object.__new__(cls)
    session = SimpleNamespace(execute=AsyncMock(side_effect=[[], [SimpleNamespace(
        _mapping={'customer_id': 'OTHER', 'phone': '0900000027'})]]))
    assert asyncio.run(repo.identity_matches(session, 'chat_fanpage', '0900000027')) == []
    assert session.execute.await_count == 1


def test_a_self_asserted_phone_does_not_load_a_chat_customers_profile():
    calls = []

    async def invoke(name, args):
        calls.append(args)
        return ({'found': True, 'customer_id': 'OTHER', 'phone': '0900000027',
                 'orders': [], 'sessions': []} if args.get('phone') else {'found': False})

    turn = SimpleNamespace(channel='chat_fanpage', channel_identity='unlinked-page-user',
        verified_customer_id=None, verified_phone=None, text='SĐT tôi là 0900000027',
        session_id=uuid4(), client_msg_id=uuid4())
    identity, _ = asyncio.run(initialize_identity(turn, SimpleNamespace(invoke=invoke)))
    assert identity['identity_status'] == 'unknown'
    assert identity['customer_id'] is None
    assert calls == [{'fb_id': 'unlinked-page-user'}]


class UnlinkedRepo(OrderRepo):
    async def identity_matches(self, *args):
        return []


def test_backend_verified_unlinked_channel_can_use_signed_reads_and_writes():
    async def run():
        repo = UnlinkedRepo()
        gateway = MCPGateway(catalog_server(repo, context_secret=SECRET),
            order_server(repo, context_secret=SECRET), None, context_secret=SECRET)
        quote = await gateway.invoke_trusted('pricing.get_quote',
            {'sku': 'DEVICE-RED', 'on': '2032-05-10', 'customer_phone': '0900000027'},
            'OWNER-STUDIO', 'chat_fanpage', 'unlinked-page-user')
        assert quote.get('final_price_vnd') == 97000, quote
        state = current()
        state['request'] = state['request'].model_copy(update={
            'channel': 'chat_fanpage', 'channel_identity': 'unlinked-page-user'})
        context, args = wire(state, 'order.create')
        created = await gateway.invoke_trusted('order.create', args, state['customer_id'],
            'chat_fanpage', 'unlinked-page-user', args['operation_key'], write_context=context)
        assert created.get('status') == 'created', created
        unsigned = await gateway.invoke_trusted('order.status', {'order_id': 'ORDER-STUDIO'},
            None, 'chat_fanpage', 'unlinked-page-user')
        assert unsigned.get('error') == 'identity_required'
    asyncio.run(run())


def test_signed_identity_cannot_override_a_channel_bound_to_another_customer():
    class ConflictingRepo(UnlinkedRepo):
        async def identity_matches(self, *args):
            return [{'customer_id': 'OTHER', 'phone': '0900000999'}]

    async def run():
        repo = ConflictingRepo()
        gateway = MCPGateway(catalog_server(repo, context_secret=SECRET), None, None,
                             context_secret=SECRET)
        result = await gateway.invoke_trusted('pricing.get_quote',
            {'sku': 'DEVICE-RED', 'on': '2032-05-10', 'customer_phone': '0900000027'},
            'OWNER-STUDIO', 'chat_fanpage', 'other-person')
        assert result.get('error') == 'identity_changed'
    asyncio.run(run())
