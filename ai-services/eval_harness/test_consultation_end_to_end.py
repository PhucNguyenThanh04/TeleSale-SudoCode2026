import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from eval_harness.benchmark_runner import StreamingMeasurementError, run_configuration
from eval_harness.test_evidence_continuation_end_to_end import production_case, scripted_tool


@pytest.mark.parametrize('drafts,accepted', [
    (['Giá 5 triệu 490 nghìn đồng. Hiện còn hàng. **Phí COD:** 0 VNĐ.'], True),
    (['Giá 5,5 triệu đồng. Hiện còn hàng.', 'Giá 5.490.000đ. Hiện còn hàng.'], True),
    (['Giá 5,5 triệu đồng. Hiện còn hàng.'] * 2, False),
], ids=['verified-quote', 'verified-repair', 'rejected-repair'])
def test_team_01_first_turn_saves_only_verified_quote(tmp_path, drafts, accepted):
    root = Path(__file__).resolve().parents[2]
    scenario = json.loads((root / 'eval/scenario_final/TEAM-01.json').read_text())
    call = scenario['calls']['call_1']
    scenarios = {'TEAM-01': {'calls': {'call_1': {
        'call_date': call['call_date'], 'customer_turns': call['customer_turns'][:1],
    }}}}
    sku = 'SKU-XM-4P'
    runtime, gateway, model = production_case(sku=sku, name='Máy lọc không khí Xiaomi Smart 4 Pro',
                                              price=5_490_000)
    gateway.promos = [{'promo_code': 'COD-0', 'type': 'freecod', 'discount_vnd': 0}]
    model.replies.extend([
        scripted_tool('catalog.search', {'query': 'Xiaomi Smart Air Purifier 4 Pro'}),
        scripted_tool('pricing.get_quote', {'sku': sku}),
        scripted_tool('inventory.check', {'sku': sku}),
        *(AIMessage(content=text) for text in drafts),
    ])
    out = tmp_path / 'trace.jsonl'

    async def run():
        try:
            await run_configuration(scenarios=scenarios, config='full', runtime=runtime,
                run_id='scripted', out=out, btc_root=root.parent / 'BTC-Data-Vong1-TEAMS',
                wait_for_jobs=lambda _: gateway.project(), capture_writes=AsyncMock(return_value={}))
        finally:
            await runtime.close()

    if accepted:
        asyncio.run(run())
        row = json.loads(out.read_text())
        assert row['agent_text'] == drafts[-1]
        assert row['latency']['stream_completed'] is True
        assert [claim['value'] for claim in row['claims'] if claim['field'] == 'price_vnd'] == [5_490_000]
    else:
        with pytest.raises(StreamingMeasurementError) as failure:
            asyncio.run(run())
        assert failure.value.verification_rejections == ['price_without_quote'] * 2
        assert out.read_text() == ''


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
