import asyncio

import pytest

from app.agent.mcp.gateway import MCPGateway
from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
from test_write_authorization import OrderRepo, SECRET, current, proposal, wire


class SharedRepo(OrderRepo):
    async def identity_matches(self, *args):
        return [{'customer_id': owner, 'phone': '0900000027'}
                for owner in ['OWNER-STUDIO', 'OWNER-OTHER']]


@pytest.mark.parametrize('name', ['order.create', 'order.update', 'schedule.callback', 'handoff.transfer'])
def test_verified_shared_phone_write_selects_only_the_signed_member(name):
    async def run():
        state, repo = current(), SharedRepo()
        context, args = wire(state, name)
        gateway = MCPGateway(None, order_server(repo, context_secret=SECRET), None, context_secret=SECRET)
        result = await gateway.invoke_trusted(name, args, state['customer_id'],
            state['request'].channel, state['request'].channel_identity,
            args['operation_key'], write_context=context)
        assert 'error' not in result, result
        assert len(repo.writes) == 1
        assert await gateway.invoke_trusted(name, args, state['customer_id'],
            state['request'].channel, state['request'].channel_identity,
            args['operation_key'], write_context=context) == result
        assert len(repo.writes) == 1
    asyncio.run(run())


def test_verified_shared_phone_status_is_owned_and_unsigned_lookup_stays_ambiguous():
    async def run():
        repo = SharedRepo()
        gateway = MCPGateway(None, order_server(repo, context_secret=SECRET), None, context_secret=SECRET)
        result = await gateway.invoke_trusted('order.status', {'order_id': 'ORDER-STUDIO'},
            'OWNER-STUDIO', 'hotline', '0900000027')
        assert result['orders'][0]['order_id'] == 'ORDER-STUDIO'
        foreign = await gateway.invoke_trusted('order.status', {'order_id': 'ORDER-STUDIO'},
            'OWNER-OTHER', 'hotline', '0900000027')
        assert foreign.get('error') == 'order_not_owned'
        unsigned = await gateway.invoke_trusted('order.status', {'order_id': 'ORDER-STUDIO'},
            None, 'hotline', '0900000027')
        assert unsigned.get('error') == 'identity_required'
    asyncio.run(run())


def test_shared_phone_pricing_uses_the_verified_members_own_orders():
    class Repo(SharedRepo):
        async def rows(self, session, table):
            if table == 'customers':
                return [{'customer_id': 'OWNER-STUDIO', 'orders': [{'sku': 'OLD-DEVICE', 'status': 'delivered'}]},
                        {'customer_id': 'OWNER-OTHER', 'orders': []}]
            if table == 'promotions':
                return [{'promo_code': 'REUSE-CREDIT', 'name': 'Owned-device credit', 'type': 'fixed',
                    'discount_vnd': 12000, 'applies_to': ['DEVICE-RED'], 'stackable': False,
                    'start': '2032-01-01', 'end': '2032-12-31',
                    'conditions': {'requires_owned_sku': 'OLD-DEVICE'}}]
            return await super().rows(session, table)

    async def run():
        repo = Repo()
        gateway = MCPGateway(catalog_server(repo, context_secret=SECRET), None, None, context_secret=SECRET)
        args = {'sku': 'DEVICE-RED', 'on': '2032-05-10', 'customer_phone': '0900000027'}
        first = await gateway.invoke_trusted('pricing.get_quote', args, 'OWNER-STUDIO', 'hotline', '0900000027')
        other = await gateway.invoke_trusted('pricing.get_quote', args, 'OWNER-OTHER', 'hotline', '0900000027')
        assert first['final_price_vnd'] == 85000 and other['final_price_vnd'] == 97000
    asyncio.run(run())


def test_identity_proof_is_bound_to_tool_arguments_owner_channel_and_time(monkeypatch):
    from app.mcp_servers.mcp_shared import identity
    args = {'sku': 'DEVICE-RED', 'on': '2032-05-10', 'customer_phone': '0900000027',
            'source_channel': 'hotline', 'source_identity': '0900000027'}
    monkeypatch.setattr(identity.time, 'time', lambda: 2_000_000_000)
    signed = identity.sign_identity('pricing.get_quote', args, 'OWNER-STUDIO', SECRET)
    payload = {**args, 'trusted_identity': signed}
    assert identity.verify_identity('pricing.get_quote', payload, SECRET) == 'OWNER-STUDIO'
    for changes in [{'sku': 'OTHER'}, {'source_identity': '0900000028'}, {'trusted_identity': '{}'}]:
        with pytest.raises(PermissionError):
            identity.verify_identity('pricing.get_quote', {**payload, **changes}, SECRET)
    with pytest.raises(PermissionError):
        identity.verify_identity('order.status', payload, SECRET)
    monkeypatch.setattr(identity.time, 'time', lambda: 2_000_000_121)
    with pytest.raises(PermissionError):
        identity.verify_identity('pricing.get_quote', payload, SECRET)


def test_raw_identity_metadata_cannot_choose_a_shared_phone_owner():
    async def run():
        repo = SharedRepo()
        gateway = MCPGateway(None, order_server(repo, context_secret=SECRET), None, context_secret=SECRET)
        result = await gateway.invoke('order.status', {'order_id': 'ORDER-STUDIO',
            'verified_customer_id': 'OWNER-STUDIO', 'trusted_identity': 'forged',
            'source_channel': 'hotline', 'source_identity': '0900000027'})
        assert result.get('error') == 'identity_required' and not repo.writes
    asyncio.run(run())
