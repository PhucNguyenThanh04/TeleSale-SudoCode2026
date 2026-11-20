
import asyncio

from app.agent.guardrails.checks import FALLBACK, check_answer, check_grounding
from app.agent.harness.agent_nodes import AgentNodes


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
             "result": {"items": [{"sku": sku, "name": name, "variants": [],
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
