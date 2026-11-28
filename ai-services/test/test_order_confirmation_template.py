import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from langchain_core.messages import AIMessage, ToolMessage

from app.agent.guardrails.checks import check_answer, check_grounding
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.implementations.business_agent import order_confirmation

_CATALOG = {"name": "catalog.search", "args": {"query": "Xiaomi Smart 4 Pro"},
            "result": {"items": [{"sku": "SKU-XM-4P", "name": "Máy lọc không khí Xiaomi Smart 4 Pro",
                                  "list_price_vnd": 5490000, "variants": []}]}}
_QUOTE = {"name": "pricing.get_quote", "args": {"sku": "SKU-XM-4P"},
          "result": {"sku": "SKU-XM-4P", "list_price_vnd": 5490000, "final_price_vnd": 5490000,
                     "applied_promos": []}}


def _created(**result):
    return {"name": "order.create",
            "args": {"sku": "SKU-XM-4P", "qty": 1, "price_vnd": 5490000, "payment": "COD"},
            "result": {"order_id": "OD600001", "status": "created", "total_vnd": 5490000,
                       "needs_confirmation_call": True, "estimated_delivery": "2026-10-28", **result}}


def _state(order, text="Ok em lên đơn cho anh 1 chiếc thanh toán COD nhé."):
    return {"safe_text": text, "identity_status": "known", "honorific": "anh",
            "tool_calls": [_CATALOG, _QUOTE, order], "session_tool_calls": [], "prepared_tool_calls": []}


def _messages(tool="order_create"):
    return [AIMessage(content="", tool_calls=[{"name": tool, "args": {}, "id": "1"}]),
            ToolMessage(content="{}", tool_call_id="1", name=tool)]


def test_created_order_is_confirmed_without_model_and_passes_guardrails():
    state = _state(_created())
    text = order_confirmation(state, _messages())
    assert text == ("Dạ anh, em đã lên đơn 1 Máy lọc không khí Xiaomi Smart 4 Pro cho anh rồi ạ. "
                    "Mã đơn hàng là OD600001, tổng thanh toán 5.490.000đ, thanh toán khi nhận hàng (COD). "
                    "Dự kiến đơn được giao vào ngày 28/10/2026. "
                    "Đơn cần một cuộc gọi xác nhận, anh vui lòng để ý điện thoại giúp em ạ.")
    assert check_grounding(text, state["tool_calls"]) is None
    assert check_answer(text, state["tool_calls"], state["safe_text"])[1] is None


def test_template_is_skipped_when_the_model_must_answer():
    assert order_confirmation(_state(_created(), "Lên đơn giúp anh, mà bao giờ giao em?"), _messages()) is None
    assert order_confirmation(_state(_created(status="pending")), _messages()) is None
    assert order_confirmation(_state({**_created(), "result": {"error": "price_mismatch"}}), _messages()) is None
    assert order_confirmation(_state(_created()), _messages("pricing_get_quote")) is None
    multi = _created()
    multi["args"] = {**multi["args"], "lines": [{"sku": "SKU-XM-4P", "qty": 1}]}
    assert order_confirmation(_state(multi), _messages()) is None
    unknown = _created()
    unknown["args"] = {**unknown["args"], "sku": "SKU-UNKNOWN"}
    assert order_confirmation(_state(unknown), _messages()) is None


def test_exact_receipt_confirmation_does_not_call_semantic_model():
    state = _state(_created())
    draft = order_confirmation(state, _messages())
    state.update(request=SimpleNamespace(on=date(2026, 10, 20), input_mode='clean'), agent_draft=draft)
    model = SimpleNamespace(with_structured_output=Mock())
    result = asyncio.run(AgentNodes(model, None, None, 8, 6).verify_agent(state))
    assert result['verified_answer'] == draft
    model.with_structured_output.assert_not_called()
