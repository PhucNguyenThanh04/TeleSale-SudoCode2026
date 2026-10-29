"""Promotion follow-ups recover from the quote without inventing offers."""

import asyncio

from app.agent.guardrails.checks import FALLBACK, check_answer
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.harness.session_nodes import safe_promotion_reply


def _state(*, sku="SKU-A", name="Máy lọc A", gift="SKU-FILTER-A"):
    return {
        "safe_text": "Mẫu này có ưu đãi gì không?",
        "agent_draft": f"Dạ, {name} đang giảm còn 4 triệu ạ.",
        "tool_calls": [
            {"name": "pricing.get_quote", "args": {"sku": "Tên máy không phải SKU"},
             "result": {"error": "unknown_sku"}},
            {"name": "catalog.search", "args": {"query": name},
             "result": {"items": [
                 {"sku": sku, "name": name, "attributes": {}},
                 {"sku": gift, "name": "Màng lọc thay thế", "attributes": {}},
             ], "total": 2}},
            {"name": "pricing.get_quote", "args": {"sku": sku, "on": "2026-10-15"},
             "result": {"sku": sku, "list_price_vnd": 4_890_000,
                        "final_price_vnd": 4_890_000,
                        "applied_promos": [{"promo_code": "GIFT-A", "type": "gift",
                                            "gift_sku": gift, "discount_vnd": 0}]}},
        ],
    }


def test_rejected_promotion_draft_recovers_from_current_quote():
    state = _state()
    result = asyncio.run(AgentNodes(None, None, None, 3, 3).verify_agent(state))
    assert result["agent_text"] != FALLBACK
    assert "Máy lọc A" in result["agent_text"]
    assert "tặng 1 Màng lọc thay thế" in result["agent_text"]
    assert "4 triệu" not in result["agent_text"]
    assert check_answer(result["agent_text"], state["tool_calls"], state["safe_text"])[1] is None


def test_promotion_recovery_works_for_another_product_and_question_wording():
    state = _state(sku="SKU-B", name="Máy lọc B", gift="SKU-FILTER-B")
    state["safe_text"] = "Mẫu B có khuyến mãi gì?"
    assert "Máy lọc B" in safe_promotion_reply(state)


def test_gift_can_be_reported_by_verified_program_when_gift_name_was_not_loaded():
    state = _state()
    state["tool_calls"][1]["result"]["items"].pop()
    answer = safe_promotion_reply(state)
    assert "GIFT-A" in answer
    assert check_answer(answer, state["tool_calls"], state["safe_text"])[1] is None


def test_no_quote_or_ambiguous_quotes_do_not_create_offer():
    state = _state()
    state["tool_calls"].pop()
    assert safe_promotion_reply(state) is None
    state = _state()
    state["tool_calls"].append({
        "name": "pricing.get_quote", "args": {"sku": "SKU-OTHER"},
        "result": {"sku": "SKU-OTHER", "applied_promos": []},
    })
    assert safe_promotion_reply(state) is None


def test_no_applied_offer_does_not_claim_a_promotion():
    state = _state()
    state["tool_calls"][-1]["result"]["applied_promos"] = []
    assert safe_promotion_reply(state) is None
