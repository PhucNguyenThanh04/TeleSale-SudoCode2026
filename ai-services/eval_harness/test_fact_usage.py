"""Cross-session use must have valid provenance and scope, not just a matching literal."""
import pytest
from eval_harness.reference_adapter import facts_used, _source_session_id


@pytest.mark.parametrize("source,expected", [
    ("langmem:prior:turn-1", "prior"), ("prior:turn-1", "prior"),
    ("langmem:prior", None), ("langmem::turn-1", None), ("garbage", None), (None, None)])
def test_source_parser(source, expected):
    assert _source_session_id(source) == expected


def fact(value, source="langmem:prior:turn-1"):
    return {"value": value, "source": source}


def test_same_session_unknown_source_and_customer_repetition_are_not_recall():
    for source in ["langmem:now:turn-1", "garbage", None]:
        assert facts_used("Mẫu SKU-LOCAL có sẵn.", [], {"product_advised": fact("SKU-LOCAL", source)}, current_session_id="now") == []
    assert facts_used("Ngân sách 2 triệu.", [], {"budget_vnd": fact(2000000)},
                      current_session_id="now", customer_text="Ngân sách tôi 2 triệu") == []


def test_money_and_boolean_meaning():
    assert facts_used("Giá đã báo 2731k.", [], {"price_quoted_vnd": fact(2731000)}, current_session_id="now") == ["price_quoted_vnd"]
    assert facts_used("Vì bé nhà mình, mẫu này có khóa trẻ em.", [], {"has_children": fact(True)}, current_session_id="now") == ["has_children"]
    assert facts_used("Nhà không có trẻ nhỏ.", [], {"has_children": fact(True)}, current_session_id="now") == []
    assert facts_used("Dạ", [{"name": "catalog.search", "args": {"include_discontinued": True}}], {"has_children": fact(True)}, current_session_id="now") == []


def test_product_scope_and_argument_semantics():
    scoped = {"product": {"SKU-A": {"price_quoted_vnd": fact(730000)},
                          "SKU-B": {"competitor_price_vnd": fact(730000)}}}
    calls = [{"name": "order.create", "args": {"sku": "SKU-A", "price_vnd": 730000}}]
    assert facts_used("Dạ", calls, {}, scoped, "now") == ["price_quoted_vnd"]
    assert facts_used("Giá 730000đ.", [], {}, scoped, "now") == []
    assert facts_used("SKU-A giá 730000đ.", [], {}, scoped, "now") == ["price_quoted_vnd"]


def test_harness_uses_call_start_snapshot_not_current_turn_memory():
    import asyncio
    from datetime import date
    from types import SimpleNamespace
    from eval_harness.benchmark_runner import run_scenario_call

    class Runtime:
        count = 0
        async def run(self, request):
            self.count += 1
            return SimpleNamespace(agent_text="SKU-LOCAL", call_brief=None)
        def state_for(self, request):
            source = "langmem:prior:turn-1" if self.count == 1 else f"langmem:{request.session_id}:turn-1"
            return {"profile": {"product_advised": fact("SKU-LOCAL", source)},
                    "tool_calls": [], "memory_writes": []}

    rows = asyncio.run(run_scenario_call(Runtime(), "LOCAL", "call_2",
        {"customer_turns": ["Chào em", "Tiếp tục nhé"]}, date(2026, 11, 2), "0900000000"))
    assert [r["facts_used"] for r in rows] == [["product_advised"], ["product_advised"]]
