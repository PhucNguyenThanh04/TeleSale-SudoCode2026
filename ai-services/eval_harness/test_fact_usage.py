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
    calls = [{"name": "order.create", "args": {"sku": "SKU-A", "price_vnd": 730000}, "result":{"ok":True}}]
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


@pytest.mark.parametrize('text', ['Phòng ngủ 25m2 phù hợp.', 'Phòng NGỦ rộng 25 m² nhé.', 'Bedroom 25m2 phù hợp.'])
def test_room_alias_requires_previous_session_scope_and_value(text):
    scoped={'room':{'bedroom':{'room_area_m2':fact(25)}}}
    assert facts_used(text,[],{},scoped,'now') == ['room_area_m2']
    for source in ('langmem:now:1', 'invalid', None):
        assert facts_used(text,[],{}, {'room':{'bedroom':{'room_area_m2':fact(25,source)}}}, 'now') == []


@pytest.mark.parametrize('text', [
    'Phòng khách 25m2 phù hợp.', 'Phòng ngủ 30m2 phù hợp.', '25m2 phù hợp.',
    'Phòng ngủ 30m2 và phòng khách 25m2.', 'Phòng ngủ không phải 25m2.',
    'Phòng ngủ 25m2 hay 30m2?', 'Phòng ngủ 25m2x phù hợp.',
])
def test_room_scope_cannot_borrow_value_or_negated_question(text):
    scoped={'room':{'bedroom':{'room_area_m2':fact(25)}}}
    assert facts_used(text,[],{},scoped,'now') == []


def test_customer_repetition_is_checked_in_the_same_room():
    scoped={'room':{'bedroom':{'room_area_m2':fact(25)}}}
    assert facts_used('Phòng ngủ 25m2.',[],{},scoped,'now',customer_text='Phòng ngủ 25m2.') == []
    assert facts_used('Phòng ngủ 25m2.',[],{},scoped,'now',customer_text='Phòng khách 25m2.') == ['room_area_m2']


@pytest.mark.parametrize('result', [{'error':'failed'}, {'ok':False}, {'success':False}])
def test_failed_tool_is_not_evidence_of_use(result):
    calls=[{'name':'order.create','args':{'sku':'SKU-A','price_vnd':730000},'result':result}]
    assert facts_used('Dạ',calls,{}, {'product':{'SKU-A':{'price_quoted_vnd':fact(730000)}}}, 'now') == []


def test_product_identity_boundary_and_unknown_session_are_conservative():
    scoped={'product':{'SKU-A':{'price_quoted_vnd':fact(730000)}}}
    assert facts_used('SKU-AB giá 730000đ.',[],{},scoped,'now') == []
    assert facts_used('SKU-A giá 730000đ.',[],{},scoped) == []


@pytest.mark.parametrize('text,expected', [
    ('Lần trước chị cần bàn với ông xã trước khi mua.', ['blocker']),
    ('Chị cần hỏi ý kiến chồng trước khi chốt.', ['blocker']),
    ('Chị đã bàn với chồng và anh đồng ý rồi.', []),
    ('Chị cần hỏi vợ trước khi mua.', []),
    ('Chị có cần bàn với chồng không?', []),
])
def test_controlled_blocker_paraphrase_keeps_dependency_polarity(text,expected):
    assert facts_used(text,[],{'blocker':fact('cần hỏi chồng')},current_session_id='now') == expected


def test_area_before_single_room_and_correction_keeps_scope():
    scoped={'room':{'bedroom':{'room_area_m2':fact(31)}}}
    assert facts_used('Diện tích 31m2 của phòng ngủ phù hợp.',[],{},scoped,'now') == ['room_area_m2']
    assert facts_used('Phòng ngủ không phải 25m2 mà là 31m2.',[],{},scoped,'now') == ['room_area_m2']
    assert facts_used('Phòng ngủ không phải 25m2 mà là 31m2.',[],{}, {'room':{'bedroom':{'room_area_m2':fact(25)}}},'now') == []


def test_identical_area_in_other_room_is_not_the_prior_fact():
    scoped={'room':{'bedroom':{'room_area_m2':fact(31)}, 'living_room':{'room_area_m2':fact(25)}}}
    assert facts_used('Phòng ngủ 25m2 và phòng khách 31m2.',[],{},scoped,'now') == []


def test_negation_in_product_category_does_not_negate_spoken_price():
    assert facts_used('Máy lọc không khí có giá 730000đ.',[],{'price_quoted_vnd':fact(730000)},current_session_id='now') == ['price_quoted_vnd']


def test_unknown_other_room_does_not_supply_bedroom_value():
    scoped={'room':{'bedroom':{'room_area_m2':fact(25)}}}
    assert facts_used('Phòng ngủ 30m2 và phòng trẻ em 25m2.',[],{},scoped,'now') == []


def test_unscoped_customer_repetition_does_not_create_scoped_memory_credit():
    scoped={'room':{'bedroom':{'room_area_m2':fact(31)}}}
    assert facts_used('Phòng ngủ 31m2.',[],{},scoped,'now',customer_text='Diện tích 31m2 nhé.') == []


@pytest.mark.parametrize('source',['langmem: :t1',' prior:t1','langmem:prior: '])
def test_whitespace_source_is_not_valid_provenance(source):
    assert facts_used('Phòng 31m2.',[],{'room_area_m2':fact(31,source)},current_session_id='now') == []


def test_confirming_known_previous_fact_is_still_observable_use():
    scoped={'room':{'bedroom':{'room_area_m2':fact(31)}}}
    assert facts_used('Phòng ngủ 31m2 đúng không?',[],{},scoped,'now') == ['room_area_m2']
    assert facts_used('Phòng ngủ 31m2 đúng không?',[],{},scoped,'now',customer_text='Phòng ngủ 31m2.') == []
