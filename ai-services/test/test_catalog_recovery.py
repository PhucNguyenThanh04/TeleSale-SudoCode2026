"""A rejected product draft may still yield a sourced, useful answer."""

import asyncio

from app.agent.guardrails.checks import FALLBACK, check_answer, check_grounding
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.harness.session_nodes import safe_catalog_reply


def _state(text, *, price=4_800_000, budget=5_000_000, lock=False):
    sku = "SKU-FILTER-A"
    name = "Máy lọc Filter A"
    return {
        "safe_text": text,
        "agent_draft": f"{name} có khóa trẻ em và HEPA H13 ạ.",
        "tool_calls": [
            {"name": "catalog.search",
             "args": {"query": "máy lọc", "min_room_area_m2": 27,
                      "max_price_vnd": budget},
             "result": {"items": [{"sku": sku, "name": name,
                                   "attributes": {"room_area_m2": 30,
                                                  "child_safe_lock": lock}}],
                        "total": 1}},
            {"name": "pricing.get_quote", "args": {"sku": sku, "on": "2026-10-15"},
             "result": {"sku": sku, "list_price_vnd": price,
                        "final_price_vnd": price, "applied_promos": []}},
        ],
    }


def test_recover_sourced_price_and_child_lock_when_model_claim_is_wrong():
    state = _state("Nhà có em bé, phòng 27m2, chi khoảng 5 triệu thôi.")
    assert check_grounding(state["agent_draft"], state["tool_calls"]) == "unsupported_product_spec"
    result = asyncio.run(AgentNodes(None, None, None, 3, 3).verify_agent(state))
    assert result["agent_text"] != FALLBACK
    assert "4.800.000đ" in result["agent_text"]
    assert "không có khóa trẻ em" in result["agent_text"]
    assert check_answer(result["agent_text"], state["tool_calls"], state["safe_text"])[1] is None


def test_recovery_uses_validated_child_safe_option_with_different_budget():
    state = _state("Có con nhỏ, phòng 27m2, tối đa 6 triệu.",
                   price=5_200_000, budget=6_000_000, lock=True)
    result = safe_catalog_reply(state)
    assert "5.200.000đ" in result
    assert "có khóa trẻ em" in result
    assert check_answer(result, state["tool_calls"], state["safe_text"])[1] is None


def test_recovery_names_product_in_each_feature_sentence_with_multiple_results():
    state = _state("Nhà có con nhỏ, phòng 27m2, ngân sách 5 triệu.")
    state["tool_calls"][0]["result"]["items"].append({
        "sku": "SKU-FILTER-B", "name": "Máy lọc Filter B",
        "attributes": {"room_area_m2": 35, "child_safe_lock": True},
    })
    result = safe_catalog_reply(state)
    assert "Máy lọc Filter A không có khóa trẻ em" in result
    assert check_grounding(result, state["tool_calls"]) is None


def test_recovery_does_not_present_price_above_budget():
    state = _state("Nhà có con nhỏ, chi tối đa 5 triệu.", price=5_200_000)
    result = safe_catalog_reply(state)
    assert "5.200.000đ" not in result
    assert "em tìm thấy" in result


def test_recovery_does_not_invent_child_safety_when_not_asked():
    state = _state("Phòng 27m2, ngân sách 5 triệu.")
    result = safe_catalog_reply(state)
    assert "khóa trẻ em" not in result
    assert check_answer(result, state["tool_calls"], state["safe_text"])[1] is None
