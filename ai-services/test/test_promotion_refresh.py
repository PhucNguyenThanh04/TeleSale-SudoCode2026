import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.agent.harness.agent_nodes import AgentNodes
from app.agent.guardrails.checks import FALLBACK
from app.schemas.agent import TextTurnRequest
from test_deep_memory import FakeToolModel


def test_missing_promotion_quote_refreshes_current_date_and_rewrites_old_offer():
    asyncio.run(_exercise())


def test_quote_failure_keeps_unverified_offer_blocked():
    asyncio.run(_exercise(fail=True))


def test_ambiguous_products_do_not_trigger_guessed_quote():
    asyncio.run(_exercise(multiple=True))


def test_remembered_product_still_requires_a_current_quote():
    asyncio.run(_exercise(memory_only=True))


def turn_state():
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(), channel="hotline",
        channel_identity="0900000000", on=date(2032, 11, 1),
        text="Có tặng gì kèm không?", input_mode="clean")
    return {"request": request, "safe_text": request.text, "identity_status": "known",
        "customer_id": "TEST", "customer_phone": "0900000000", "tool_calls": [],
        "tool_count": 0, "session_tool_calls": [{"name": "pricing.get_quote",
            "args": {"sku": "SKU-EXAMPLE", "on": "2032-10-01"},
            "result": {"sku": "SKU-EXAMPLE", "final_price_vnd": 1200000,
                       "applied_promos": [{"promo_code": "GIFT-OLD", "type": "gift"}]}}]}


async def _exercise(fail=False, multiple=False, memory_only=False):
    current = turn_state()
    if multiple:
        current["session_tool_calls"].append({"name": "pricing.get_quote",
            "args": {"sku": "SKU-OTHER", "on": "2032-10-01"}, "result": {"sku": "SKU-OTHER"}})
    if memory_only:
        current["session_tool_calls"] = []
        current["scoped_facts"] = {"product": {"SKU-EXAMPLE": {
            "product_advised": {"value": "SKU-EXAMPLE", "source_kind": "tool"}}}}
    quote = {'sku': 'SKU-EXAMPLE', 'final_price_vnd': 1200000,
        'list_price_vnd': 1200000, 'applied_promos': [], 'freeship': False}
    reply = ('Anh đang hỏi mẫu nào ạ?' if multiple else
        'Em chưa tra được thông tin, anh cho em kiểm tra lại nhé.' if fail else
        'Hiện không có quà tặng kèm. Giá hiện tại là 1.200.000đ ạ.')

    async def invoke(name, args):
        if name == 'catalog.get_details':
            return {'items': [{'sku': 'SKU-EXAMPLE', 'name': 'Đèn bàn thử nghiệm',
                'attributes': {}, 'variants': []}], 'total': 1}
        assert name == 'pricing.get_quote'
        assert args['on'] == '2032-11-01'
        return {'error': 'tool_unavailable'} if fail else quote

    gateway = SimpleNamespace(invoke=AsyncMock(side_effect=invoke))
    reads = [] if multiple else [
        AIMessage(content='', tool_calls=[{'id': 'catalog', 'name': 'catalog_get_details',
            'args': {'sku': 'SKU-EXAMPLE'}}]),
        AIMessage(content='', tool_calls=[{'id': 'quote', 'name': 'pricing_get_quote',
            'args': {'sku': 'SKU-EXAMPLE'}}])]
    model = FakeToolModel(replies=[*reads, AIMessage(content=reply)])
    node = AgentNodes(model, gateway, None, 5, 6)
    current.update(await node.run_agent(current))
    verified = await node.verify_agent(current)
    assert verified['verified_answer'] == reply
    assert verified['reply_error'] is None
    assert [call['name'] for call in current['tool_calls']] == (
        [] if multiple else ['catalog.get_details', 'pricing.get_quote'])
    assert not model.replies
    if fail:
        assert current['tool_calls'][-1]['result'] == {'error': 'tool_unavailable'}


def test_skipping_refresh_cannot_reuse_a_stale_promotion():
    current = turn_state()
    current['agent_draft'] = 'Mẫu này đang tặng kèm màng lọc.'
    model = FakeToolModel(replies=[AIMessage(content=current['agent_draft'])])
    gateway = SimpleNamespace(invoke=AsyncMock())
    result = asyncio.run(AgentNodes(model, gateway, None, 5, 6).verify_agent(current))
    assert result['agent_text'] == FALLBACK
    assert result['reply_error'] == 'agent_reply_unavailable'
    assert gateway.invoke.await_count == 0
