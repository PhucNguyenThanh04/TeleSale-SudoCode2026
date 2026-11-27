import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.agent.harness.agent_nodes import AgentNodes, _contextual_safe_fallback
from app.schemas.agent import TextTurnRequest


def _turn_state(text: str, draft: str, calls: list[dict], *, honorific: str | None = "chị") -> dict:
    req = TextTurnRequest(
        session_id=uuid4(),
        client_msg_id=uuid4(),
        channel="hotline",
        channel_identity="0900000001",
        input_mode="clean",
        text=text,
        on=date(2026, 10, 20),
    )
    return {
        "request": req,
        "safe_text": text,
        "identity_status": "known",
        "customer_id": "C001",
        "customer_phone": "0900000001",
        "honorific": honorific,
        "agent_draft": draft,
        "tool_calls": calls,
        "session_tool_calls": [],
        "tool_count": len(calls),
        "tool_attempts": len(calls),
        "history": [],
        "profile": {},
        "scoped_facts": {"product": {}, "room": {}},
        "episodes": [],
        "current_episode": None,
        "call_brief": None,
    }


def test_p1_verify_backfills_missing_quote_and_inventory_before_repair():
    gateway = AsyncMock()
    gateway.invoke_trusted.side_effect = [
        {"sku": "SKU-AP-X", "list_price_vnd": 4890000, "final_price_vnd": 4890000, "applied_promos": []},
        {"sku": "SKU-AP-X", "in_stock": True, "qty": 10},
    ]
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="Máy lọc không khí AirPure X hiện còn hàng với giá 4.890.000 đồng ạ.")
    nodes = AgentNodes(
        llm=llm,
        tools=gateway,
        memory=AsyncMock(),
        max_tool_calls=6,
        prompt_history_turns=6,
        clock=lambda: datetime.now(timezone.utc),
        max_repair_attempts=1,
        safe_fallback_on_rejection=True,
        semantic_review_enabled=False,
    )
    catalog_call = {
        "name": "catalog.search",
        "args": {"query": "AirPure X"},
        "result": {
            "items": [
                {"sku": "SKU-AP-X", "name": "Máy lọc không khí AirPure X", "list_price_vnd": 4890000, "variants": []}
            ]
        },
    }
    st = _turn_state("Máy lọc không khí AirPure X giá bao nhiêu và còn hàng không?",
                     "Máy lọc không khí AirPure X có giá 4.890.000đ và hiện còn hàng.",
                     [catalog_call])
    out = asyncio.run(nodes.verify_agent(st))
    assert out["reply_error"] is None
    assert "4.890.000" in out["verified_answer"]
    called_tools = [call.args[0] for call in gateway.invoke_trusted.await_args_list]
    assert "pricing.get_quote" in called_tools
    assert "inventory.check" in called_tools


def test_p1_contextual_safe_fallback_preserves_product_and_asks_variant_when_needed():
    variant_catalog = {
        "name": "catalog.search",
        "args": {"query": "Giày chạy bộ RunLite 2 Pro"},
        "result": {
            "items": [
                {
                    "sku": "SKU-SN-RUN2",
                    "name": "Giày chạy bộ RunLite 2 Pro",
                    "variants": [
                        {"variant_sku": "SKU-SN-RUN2-40-DEN", "size": "40", "color": "den"},
                        {"variant_sku": "SKU-SN-RUN2-41-DEN", "size": "41", "color": "den"},
                    ],
                }
            ]
        },
    }
    st = _turn_state("Giày chạy bộ RunLite 2 Pro giá bao nhiêu?", "Giá 1.690.000đ.", [variant_catalog])
    fb = _contextual_safe_fallback(st, [variant_catalog], "price_without_quote")
    assert "Giày chạy bộ RunLite 2 Pro" in fb
    assert "size" in fb.lower() or "màu" in fb.lower()
    assert "1.690.000" not in fb


def _backfill_nodes(quote_price: int, repair_text: str):
    gateway = AsyncMock()
    gateway.invoke_trusted.side_effect = [
        {"sku": "SKU-AP-X", "list_price_vnd": quote_price, "final_price_vnd": quote_price, "applied_promos": []},
        {"sku": "SKU-AP-X", "in_stock": True, "qty": 10},
    ]
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content=repair_text)
    nodes = AgentNodes(llm=llm, tools=gateway, memory=AsyncMock(), max_tool_calls=6, prompt_history_turns=6,
                       clock=lambda: datetime.now(timezone.utc), max_repair_attempts=1,
                       safe_fallback_on_rejection=True, semantic_review_enabled=False)
    catalog_call = {"name": "catalog.search", "args": {"query": "AirPure X"},
                    "result": {"items": [{"sku": "SKU-AP-X", "name": "Máy lọc không khí AirPure X",
                                          "list_price_vnd": 4890000, "variants": []}]}}
    return nodes, llm, catalog_call


def test_backfilled_evidence_accepts_original_draft_without_repair_call():
    nodes, llm, catalog_call = _backfill_nodes(4890000, "Không dùng bản sửa này.")
    draft = "Máy lọc không khí AirPure X có giá 4.890.000đ và hiện còn hàng."
    st = _turn_state("Máy lọc không khí AirPure X giá bao nhiêu và còn hàng không?", draft, [catalog_call])
    out = asyncio.run(nodes.verify_agent(st))
    assert out["reply_error"] is None
    assert out["verified_answer"] == draft
    llm.ainvoke.assert_not_awaited()


def test_backfilled_evidence_still_repairs_draft_with_wrong_price():
    nodes, llm, catalog_call = _backfill_nodes(
        4590000, "Máy lọc không khí AirPure X hiện còn hàng với giá 4.590.000 đồng ạ.")
    st = _turn_state("Máy lọc không khí AirPure X giá bao nhiêu và còn hàng không?",
                     "Máy lọc không khí AirPure X có giá 4.890.000đ và hiện còn hàng.", [catalog_call])
    out = asyncio.run(nodes.verify_agent(st))
    assert out["reply_error"] is None
    assert "4.890.000" not in out["verified_answer"]
    llm.ainvoke.assert_awaited()
