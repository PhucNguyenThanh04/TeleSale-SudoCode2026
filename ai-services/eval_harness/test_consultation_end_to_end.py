import asyncio
import json
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage

from eval_harness.benchmark_runner import run_configuration
from eval_harness.test_evidence_continuation_end_to_end import production_case, scripted_tool


def test_changed_quote_requires_customer_confirmation_before_write(tmp_path):
    sku, name = 'SKU-ASTER', 'Aster'
    runtime, gateway, model = production_case(sku=sku, name=name, price=900_000)
    model.replies.extend([
        scripted_tool('catalog.search', {'query': name}),
        scripted_tool('pricing.get_quote', {'sku': sku}),
        AIMessage(content='Aster giá 900.000đ.'),
        scripted_tool('catalog.search', {'query': name}),
        scripted_tool('pricing.get_quote', {'sku': sku}),
        scripted_tool('inventory.check', {'sku': sku}),
        scripted_tool('order.create', {'sku': sku, 'price_vnd': 900_000}),
        AIMessage(content='Aster hiện giá 950.000đ. Anh có đồng ý giá mới không ạ?'),
        scripted_tool('order.create', {'sku': sku, 'price_vnd': 950_000}),
        AIMessage(content='Em đã tạo đơn OD-PRODUCTION.'),
    ])
    scenarios = {'CHANGED-QUOTE': {'calls': {
        'call_1': {'call_date': '2026-11-05', 'customer_turns': ['Aster giá bao nhiêu?']},
        'call_2': {'call_date': '2026-11-06', 'customer_turns': [
            'Lên đơn Aster giá 900.000đ.', 'Tôi đồng ý giá mới 950.000đ, lên đơn Aster nhé.']},
    }}}

    async def wait(*args):
        await gateway.project()
        gateway.price = 950_000

    out = tmp_path / 'trace.jsonl'
    asyncio.run(run_configuration(scenarios=scenarios, config='full', runtime=runtime,
        run_id='scripted', out=out, wait_for_jobs=wait, capture_writes=AsyncMock(return_value={})))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert all(tool['name'] != 'order.create' for tool in rows[1]['tool_calls'])
    assert '950.000đ' in rows[1]['agent_text']
    assert len(gateway.writes) == 1
    assert gateway.writes[0]['sku'] == sku
    assert gateway.writes[0]['price_vnd'] == 950_000
    assert 'OD-PRODUCTION' in rows[2]['agent_text']
