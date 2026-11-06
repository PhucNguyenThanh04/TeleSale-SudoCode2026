"""Catalog-based selection contracts, independent of benchmark product IDs."""
import asyncio
from datetime import date
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent.harness.policy import prepare_tool_call, resolve_product_selection
from app.agent.harness.state import Decision
from app.agent.implementations.business_agent import BusinessTools
from app.mcp_servers.mcp_order.services.order import create
from app.schemas.agent import TextTurnRequest


def state():
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
        channel="hotline", channel_identity="0900000000", on=date(2026, 11, 2),
        text="Lên đơn giúp tôi", input_mode="clean")
    return {"request": request, "safe_text": request.text, "identity_status": "known",
            "customer_id": "C-LOCAL", "customer_phone": "0900000000",
            "tool_calls": [], "session_tool_calls": [], "tool_count": 0}



def selected_customer_offer(current, sku):
    """Committed customer choice survives even when catalog metadata needs hydration."""
    ref = {'customer_id': 'C-LOCAL', 'session_id': str(current['request'].session_id),
           'source_turn_id': str(uuid4()), 'source_kind': 'customer',
           'evidence_quote': f'Tôi chọn {sku}.'}
    current['current_episode'] = {'customer_id': 'C-LOCAL', 'topics': [
        {'scope_type': 'global', 'consultation': {'selected_sku': sku,
         'source_refs': {'selected_sku': ref}}}]}
    current['safe_text'] = current['request'].text = f'Mua {sku} giá 730 nghìn giúp tôi'


def catalog(sku):
    return {"sku": sku, "variants": [
        {"variant_sku": sku + "-R", "size": 37, "color": "do"},
        {"variant_sku": sku + "-B", "size": 37, "color": "xanh"}]}


def evidence(sku, price=730000, **extra):
    args = {"sku": sku, "on": "2026-11-02", **extra}
    return [{"name": "inventory.check", "args": args,
             "result": {"sku": sku, "in_stock": True, "qty": 5}},
            {"name": "pricing.get_quote", "args": args,
             "result": {"sku": sku, "final_price_vnd": price}}]


@pytest.mark.parametrize("sku", ["SKU-LOCAL-BOOT", "SKU-LOCAL-HAT"])
def test_metadata_and_selection_states(sku):
    current = state()
    assert resolve_product_selection(current, {"sku": sku}).status == "catalog_required"
    current["tool_calls"] = [{"name": "catalog.search", "result": {"items": [catalog(sku)]}}]
    assert resolve_product_selection(current, {"sku": sku, "size": 37}).missing_fields == ("color",)
    assert resolve_product_selection(current, {"sku": sku, "size": 44}).status == "selection_unavailable"
    current["scoped_facts"] = {"product": {sku: {"color": {"value": "xanh"}}}}
    selection = resolve_product_selection(current, {"sku": sku, "size": 37, "color": "đỏ"})
    assert selection.sku == sku + "-R"
    current["tool_calls"][0]["result"]["items"][0]["variants"].reverse()
    assert resolve_product_selection(current, {"sku": sku, "color": "đỏ"}).sku == sku + "-R"


@pytest.mark.parametrize("mismatch", ["parent", "day", "qty", "address", "basket"])
def test_create_requires_exact_stock_and_quote(mismatch):
    current = state()
    sku = "SKU-LOCAL-BOOT"
    current["tool_calls"] = [{"name": "catalog.search", "result": {"items": [catalog(sku)]}}]
    current["session_tool_calls"] = evidence(sku + "-R")
    if mismatch == "parent":
        current["session_tool_calls"] = evidence(sku)
    elif mismatch == "day":
        current["session_tool_calls"][1]["args"]["on"] = "2026-11-01"
    elif mismatch == "qty":
        current["session_tool_calls"][1]["args"]["qty"] = 2
    elif mismatch == "address":
        current["session_tool_calls"][1]["args"]["address"] = "Other region"
    else:
        current["session_tool_calls"][1]["args"]["basket_skus"] = ["SKU-OTHER"]
    current["decision"] = Decision(action="tool", tool_name="order.create",
        tool_args={"sku": sku, "size": 37, "color": "đỏ", "price_vnd": 730000})
    assert prepare_tool_call(current, lambda: None) is None


def test_returning_create_hydrates_catalog_without_recursive_lock():
    async def run():
        current = state()
        selected_customer_offer(current, "SKU-LOCAL-BOOT")
        current["safe_text"] = current["request"].text = "Mua SKU-LOCAL-BOOT size 37 màu đỏ giá 730 nghìn giúp tôi"
        current["session_tool_calls"] = evidence("SKU-LOCAL-BOOT-R")
        gateway = AsyncMock()
        async def invoke(name, args, *rest):
            if name == "catalog.search":
                return {"items": [catalog("SKU-LOCAL-BOOT")]}
            return {"status": "created", "order_id": "ODLOCAL1"}
        gateway.invoke_trusted.side_effect = invoke
        tools = BusinessTools(gateway, current, 4, lambda: None)
        result = await asyncio.wait_for(tools.invoke("order.create", {
            "sku": "SKU-LOCAL-BOOT", "size": 37, "color": "đỏ", "price_vnd": 730000}), 1)
        assert result.get("status") == "created", result
        assert [c["name"] for c in current["tool_calls"]] == ["catalog.search", "order.create"]
        assert current["tool_calls"][-1]["args"]["sku"] == "SKU-LOCAL-BOOT-R"
        assert current["tool_count"] == 2
    asyncio.run(run())


def test_mcp_rejects_parent_before_allocating_order_or_consuming_promo():
    async def run():
        repo = AsyncMock()
        repo.rows.return_value = [catalog("SKU-LOCAL-BOOT")]
        result = await create(repo, object(), {"sku": "SKU-LOCAL-BOOT", "qty": 1,
            "customer_phone": "0900000000", "payment": "COD"}, "C-LOCAL", "0900000000")
        assert result == {"error": "variant_selection_required"}
        repo.next_order_id.assert_not_awaited()
        repo.insert_order.assert_not_awaited()
        repo.use_promo.assert_not_awaited()
    asyncio.run(run())


def test_explicit_variant_overrides_old_preferences():
    current = state()
    current['tool_calls'] = [{'name':'catalog.search','result':{'items':[catalog('SKU-LOCAL-BOOT')]}}]
    current['scoped_facts'] = {'product':{'SKU-LOCAL-BOOT':{'color':{'value':'xanh'}}}}
    assert resolve_product_selection(current, {'sku':'SKU-LOCAL-BOOT-R'}).sku == 'SKU-LOCAL-BOOT-R'


def test_latest_read_can_invalidate_prior_evidence():
    for name, result in [('inventory.check', {'in_stock':False, 'qty':0}),
                         ('pricing.get_quote', {'final_price_vnd':999000})]:
        current = state()
        current['tool_calls'] = [{'name':'catalog.search','result':{'items':[catalog('SKU-LOCAL-BOOT')]}}]
        current['tool_calls'] += evidence('SKU-LOCAL-BOOT-R')
        current['tool_calls'].append({'name':name, 'args':{'sku':'SKU-LOCAL-BOOT-R','on':'2026-11-02'}, 'result':result})
        current['decision'] = Decision(action='tool',tool_name='order.create',tool_args={
            'sku':'SKU-LOCAL-BOOT-R','price_vnd':730000})
        assert prepare_tool_call(current, lambda:None) is None


def test_customer_selection_cannot_be_overwritten_by_model_or_memory():
    current = state()
    current['safe_text'] = 'Lấy size 37 màu đỏ, lên đơn giúp tôi.'
    current['tool_calls'] = [{'name':'catalog.search','result':{'items':[catalog('SKU-LOCAL-BOOT')]}}]
    current['scoped_facts'] = {'product':{'SKU-LOCAL-BOOT':{'color':{'value':'xanh'}}}}
    assert resolve_product_selection(current, {'sku':'SKU-LOCAL-BOOT-B'}).sku != 'SKU-LOCAL-BOOT-B'


def test_unknown_identity_does_not_hydrate_or_create_order():
    async def run():
        current = state()
        current['identity_status'] = 'unknown'
        gateway = AsyncMock()
        tools = BusinessTools(gateway,current,4,lambda:None)
        result = await tools.invoke('order.create', {'sku':'SKU-LOCAL-BOOT','price_vnd':730000})
        assert result['error'] == 'identity_required'
        gateway.invoke_trusted.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('variant,price,expected_error', [
    ('R',550000,None), ('R',495000,'price_mismatch'), ('B',450000,None), (None,450000,None)])
def test_mcp_reprices_variant_surcharge_and_size_exclusion(variant, price, expected_error):
    async def run():
        product = {'sku':'SKU-SYNTHETIC','list_price_vnd':500000,'stock':10,'attributes':{},'variants':[
            {'variant_sku':'SKU-SYNTHETIC-R','size':37,'color':'do','stock':2,'price_delta_vnd':50000},
            {'variant_sku':'SKU-SYNTHETIC-B','size':38,'color':'xanh','stock':2,'price_delta_vnd':0}] if variant else []}
        promo = {'promo_code':'LOCAL-PERCENT','start':'2026-01-01','end':'2026-12-31',
                 'applies_to':['SKU-SYNTHETIC'],'type':'percent','discount_percent':10,
                 'conditions':{'exclude_variant_size':[37]},'stackable':False}
        repo = AsyncMock()
        async def rows(session, table):
            return {'products':[product],'promotions':[promo],'inventory_events':[],'customers':[]}[table]
        repo.rows.side_effect = rows
        repo.used_promos.return_value = set()
        repo.next_order_id.return_value = 'ODLOCAL88'
        sku = 'SKU-SYNTHETIC' + ('-'+variant if variant else '')
        result = await create(repo,object(),{'sku':sku,'qty':1,'payment':'COD','price_vnd':price,
            'customer_phone':'0900000000','on':'2026-11-02'},'C-LOCAL','0900000000')
        if expected_error:
            assert result['error'] == expected_error
            repo.insert_order.assert_not_awaited()
            repo.use_promo.assert_not_awaited()
        else:
            assert result['status'] == 'created'
            assert result['total_vnd'] == price
            assert repo.insert_order.await_args.args[3]['sku'] == sku
    asyncio.run(run())


def test_failed_catalog_and_budget_exhaustion_never_create():
    async def run(budget):
        current = state()
        selected_customer_offer(current, 'SKU-LOCAL-A')
        gateway = AsyncMock()
        gateway.invoke_trusted.return_value = {'error':'catalog_unavailable'}
        tools = BusinessTools(gateway,current,budget,lambda:None)
        result = await tools.invoke('order.create',{'sku':'SKU-LOCAL-A','price_vnd':730000})
        assert 'error' in result
        assert all(call.args[0] != 'order.create' for call in gateway.invoke_trusted.await_args_list)
        assert gateway.invoke_trusted.await_count == (1 if budget else 0)
    asyncio.run(run(0))
    asyncio.run(run(2))
