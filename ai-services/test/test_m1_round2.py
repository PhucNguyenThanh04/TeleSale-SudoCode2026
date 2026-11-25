import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.agent.guardrails.checks import check_answer
from app.agent.implementations.business_agent import BusinessTools
from test_commerce_evidence import state, catalog, stock


def variant_catalog():
    return catalog(name='Giày Aster', variants=[
        {'variant_sku': 'SKU-ASTER-41-XAM', 'size': 41, 'color': 'xam'},
        {'variant_sku': 'SKU-ASTER-42-XAM', 'size': 42, 'color': 'xam'},
    ])


def test_unowned_exchange_does_not_trigger_lookup_or_write():
    current = state('Đổi sang size 42 nhé.')
    current['tool_calls'] = [variant_catalog()]
    gateway = SimpleNamespace(invoke_trusted=AsyncMock())
    tools = BusinessTools(gateway, current, 8, lambda: datetime(2026, 11, 5, tzinfo=timezone.utc))
    result = asyncio.run(tools.invoke('order.update', {'order_id': 'OD-OTHER',
        'action': 'exchange_product', 'new_variant_sku': 'SKU-ASTER-42-XAM'}))
    assert 'error' in result
    gateway.invoke_trusted.assert_not_awaited()


def test_stock_wording_cannot_bypass_exact_variant_grounding():
    calls = [variant_catalog(), stock()]
    assert check_answer('Giày Aster size 42 màu xám có sẵn trong kho.', calls)[1] is not None
    calls[-1] = stock('SKU-ASTER-42-XAM')
    assert check_answer('Giày Aster size 42 màu xám có sẵn trong kho.', calls)[1] is None
    calls[-1]['result'].update(in_stock=False, qty=0)
    assert check_answer('Giày Aster size 42 màu xám có sẵn trong kho.', calls)[1] is not None
    assert check_answer('Giày Aster size 42 màu xám không có sẵn trong kho.', calls)[1] is None
