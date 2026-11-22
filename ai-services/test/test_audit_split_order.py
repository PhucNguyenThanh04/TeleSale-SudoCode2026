from copy import deepcopy
import asyncio
from unittest.mock import AsyncMock

from app.agent.harness.authorization import build_write_context
from app.agent.implementations.business_agent import BusinessTools
from app.mcp_servers.mcp_order.write_authorization import write_operation_key
from test_business_completion import state
from app.configs import Settings


def test_model_can_provide_split_basket_context_to_order_creation():
    tools = {tool.name: tool for tool in BusinessTools(AsyncMock(), state(), 8, lambda: None).langchain_tools()}
    assert 'basket_skus' in tools['order_create'].args


def test_distinct_authorized_creates_have_distinct_stable_retry_keys():
    current = state()
    first = {'customer_phone': current['customer_phone'], 'sku': 'SKU-A', 'qty': 1,
             'price_vnd': 100000, 'payment': 'COD', 'on': current['request'].on.isoformat(),
             'basket_skus': ['SKU-B']}
    second = {**deepcopy(first), 'sku': 'SKU-B', 'basket_skus': ['SKU-A']}
    one = build_write_context(current, 'order.create', first)
    two = build_write_context(current, 'order.create', second)
    assert write_operation_key(one, first) != write_operation_key(two, second)
    assert write_operation_key(one, first) == write_operation_key(
        build_write_context(current, 'order.create', deepcopy(first)), deepcopy(first))


def test_default_budget_completes_four_product_catalog_stock_quote_and_create_offline():
    async def run():
        current = state()
        current['safe_text'] = 'Chốt 4 sản phẩm SKU-A, SKU-B, SKU-C, SKU-D, mỗi loại 1 chiếc, giá 100000đ/chiếc, chuyển khoản.'
        skus = ['SKU-A', 'SKU-B', 'SKU-C', 'SKU-D']
        settings = Settings(_env_file=None, llm_api_key='offline', llm_model='offline')
        gateway = AsyncMock()

        async def invoke(name, args, *routing, **kwargs):
            if name == 'catalog.search':
                return {'items': [{'sku': sku, 'variants': []} for sku in skus]}
            if name == 'inventory.check':
                return {'sku': args['sku'], 'in_stock': True, 'qty': 10}
            if name == 'pricing.quote_order':
                return {'units': [{'unit': i+1, 'line': i, 'sku': sku,
                                   'final_price_vnd': 100000, 'applied_promos': []}
                                  for i, sku in enumerate(skus)], 'total_vnd': 400000,
                        'order_promos': [], 'freeship': False}
            return {'order_id': 'OD-FOUR', 'status': 'created', 'total_vnd': 400000}

        gateway.invoke_trusted.side_effect = invoke
        business = BusinessTools(gateway, current, settings.agent_max_tool_calls, lambda: None,
                                 authorize_write=AsyncMock(return_value=True))
        await business.invoke('catalog.search', {'query': 'sản phẩm'})
        for sku in skus:
            assert (await business.invoke('inventory.check', {'sku': sku}))['in_stock']
        await business.invoke('pricing.quote_order', {'lines': [{'sku': sku, 'qty': 1} for sku in skus]})
        result = await business.invoke('order.create', {'lines': [
            {'sku': sku, 'qty': 1, 'price_vnd': 100000} for sku in skus], 'payment': 'bank'})
        assert result['status'] == 'created'
        assert gateway.invoke_trusted.await_count == 7
    asyncio.run(run())
