"""Labeled conversational price-intent cases, including ASR and teencode."""

import re
import asyncio
import unicodedata

import pytest

from app.agent.price_intent import detect_price_intent, normalize_match_text
from app.agent.guardrails import check_answer
from app.agent.policy import response_price_precondition
from app.agent.state import Decision, parse_decision
from test_graph import FakeModel, FakeTools, harness, turn


CASES = [
    # Direct prices
    ("AirPure X giá bao nhiêu?", True),
    ("airpure x gia bao nhieu", True),
    ("gia may loc bn z", True),
    ("gia máy lọc bnh vậy", True),
    ("Máy này bao nhiêu tiền ạ", True),
    ("may nay bao nhiu tien a", True),
    ("mẫu đó hết bao nhiêu", True),
    ("mau do het bao nhieu", True),
    ("tổng cộng bao nhiêu anh ơi", True),
    ("tong cong bao nhiu anh oi", True),
    ("cho em hỏi giá máy lọc không khí airpure x", True),
    ("a lo cho anh hoi gia may loc khong khi", True),
    # Promotions
    ("AirPure X đang giảm giá không?", True),
    ("airpure x dang giam gia ko", True),
    ("máy này giảm 10% à", True),
    ("may nay giam 500k ha", True),
    ("mẫu này giảm % không", True),
    ("km gi k em", True),
    ("co km gi cho may loc ko", True),
    ("Máy lọc có khuyến mãi gì?", True),
    ("may loc co khuyen mai gi", True),
    ("Có ưu đãi nào hôm nay?", True),
    ("co uu dai nao hom nay", True),
    ("máy Xiaomi đang sale hả", True),
    ("may xiaomi dang sale ha", True),
    # Competitor comparisons
    ("Bên kia chị thấy đang bán 4590k thôi, sao bên em đắt hơn?", True),
    ("ben kia chi thay dang ban 4590k thoi sao ben em dat hon", True),
    ("chị thấy giá bên kia có 500K", True),
    ("chi thay gia ben kia co 500k", True),
    ("shop khác bán rẻ hơn bên mình à", True),
    ("shop khac ban re hon ben minh a", True),
    # Broad catalog questions
    ("máy lọc không khí có loại nào đang khuyến mãi không em?", True),
    ("may loc khong khi co loai nao dang khuyen mai ko em", True),
    ("giá các mẫu máy lọc không khí bao nhiêu", True),
    ("gia cac mau may loc khong khi bn z", True),
    ("những mẫu nào đang giảm giá", True),
    ("nhung mau nao dang giam gia", True),
    ("Máy lọc không khí có loại nào?", True),
    ("may loc khong khi co loai nao", True),
    # Not price questions
    ("máy này giảm bụi tốt không", False),
    ("may nay giam bui tot ko", False),
    ("máy này giảm ồn được không", False),
    ("may nay giam mui tot khong", False),
    ("lọc được bao nhiêu mét vuông", False),
    ("loc duoc bao nhiu met vuong", False),
    ("tốn bao nhiêu điện", False),
    ("ton bao nhieu dien", False),
    ("lọc được bao nhiêu bụi", False),
    ("phòng 25m2 dùng mẫu nào", False),
    ("máy này gia tăng hiệu quả lọc không", False),
]


OLD_PRICE_INTENT = re.compile(
    r"(?i)\b(?:giá|bao nhiêu|mấy tiền|khuyến mãi|giảm|ưu đãi|sale|"
    r"bên kia|bên khác|đắt hơn|rẻ hơn)\b"
)


@pytest.mark.parametrize(("sentence", "expected"), CASES)
def test_price_intent_cases(sentence, expected):
    assert detect_price_intent(sentence).needs_price is expected


def test_normalization_handles_composed_and_decomposed_vietnamese():
    sentence = "Giá máy lọc có khuyến mãi không?"
    decomposed = unicodedata.normalize("NFD", sentence)
    assert normalize_match_text(sentence) == normalize_match_text(decomposed)
    assert detect_price_intent(sentence) == detect_price_intent(decomposed)
    assert "gia" in normalize_match_text("đ giá")[1]
    assert " d " in normalize_match_text("đ giá")[1]


def test_price_intent_categories_are_distinct():
    broad_promo = detect_price_intent("may loc co loai nao km gi k")
    assert broad_promo.needs_price and broad_promo.promotion and broad_promo.broad
    assert not broad_promo.competitor
    objection = detect_price_intent("ben kia ban 4590k sao ben em dat hon")
    assert objection.needs_price and objection.competitor
    assert not objection.promotion
    assert not detect_price_intent("may nay giam bui tot khong").promotion


def test_detector_error_rates(capsys):
    positives = sum(expected for _, expected in CASES)
    negatives = len(CASES) - positives
    old_miss = sum(expected and not OLD_PRICE_INTENT.search(sentence)
                   for sentence, expected in CASES)
    old_false = sum(not expected and bool(OLD_PRICE_INTENT.search(sentence))
                    for sentence, expected in CASES)
    new_miss = sum(expected and not detect_price_intent(sentence).needs_price
                   for sentence, expected in CASES)
    new_false = sum(not expected and detect_price_intent(sentence).needs_price
                    for sentence, expected in CASES)
    print(f"price intent: {len(CASES)} cases ({positives} positive, {negatives} negative); "
          f"before miss={old_miss}/{positives}, false={old_false}/{negatives}; "
          f"after miss={new_miss}/{positives}, false={new_false}/{negatives}")
    assert new_miss == new_false == 0


def test_money_in_draft_requires_quote_for_matching_sku():
    catalog = {"name": "catalog.search", "args": {"query": "máy lọc"},
               "result": {"items": [
                   {"sku": "SKU-AP-X", "name": "AirPure X"},
                   {"sku": "SKU-AP-Y", "name": "AirPure Y"}]}}
    quote = {"name": "pricing.get_quote", "args": {"sku": "SKU-AP-X", "on": "2026-09-15"},
             "result": {"sku": "SKU-AP-X", "list_price_vnd": 4890000,
                        "final_price_vnd": 4390000,
                        "applied_promos": [{"discount_vnd": 500000}]}}
    for answer in ("AirPure X giá 4.390.000đ.",
                   "AirPure X giá niêm yết 4.890.000đ.",
                   "AirPure X giảm 500k."):
        assert check_answer(answer, [catalog, quote])[1] is None
    for answer, calls in (
        ("AirPure X giá 4.390.000đ.", [catalog]),
        ("AirPure X giá 4.490.000đ.", [catalog, quote]),
        ("AirPure Y giá 4.390.000đ.", [catalog, quote]),
        ("SKU-AP-Y giá 4.390.000đ.", [catalog, quote]),
        ("Bên kia bán 4.590.000đ.", [catalog, quote]),
    ):
        assert check_answer(answer, calls)[1] == "price_without_quote"
    other_quote = {"name": "pricing.get_quote",
                   "args": {"sku": "SKU-AP-Y", "on": "2026-09-15"},
                   "result": {"sku": "SKU-AP-Y", "final_price_vnd": 5200000}}
    good_pair = "AirPure X: 4.390.000đ; AirPure Y: 5.200.000đ."
    bad_pair = "AirPure X: 5.200.000đ; AirPure Y: 4.390.000đ."
    assert check_answer(good_pair, [catalog, quote, other_quote])[1] is None
    assert check_answer(bad_pair, [catalog, quote, other_quote])[1] == "price_without_quote"


def test_json_fence_and_optional_llm_price_flag():
    decision, ignored, fenced = parse_decision(
        '```json\n{"action":"tool","tool_name":"catalog.search",'
        '"tool_args":{"query":"máy lọc"},"needs_price":true}\n```')
    assert decision.needs_price is True
    assert ignored == 0 and fenced is True
    assert parse_decision('{"action":"respond","response":"Dạ."}')[0].needs_price is False


def test_policy_returns_quote_requirement_to_plan():
    request = turn(on="2026-09-15", text="xem mẫu này")
    state = {"request": request,
             "decision": Decision(action="respond", response="AirPure X giá 4.390.000đ."),
             "tool_calls": [{"name": "catalog.search", "args": {"query": "AirPure X"},
                             "result": {"items": [{"sku": "SKU-AP-X", "name": "AirPure X"}]}}]}
    assert response_price_precondition(state) == ("price_without_quote", "SKU-AP-X")


def test_policy_uses_single_quoted_variant_of_catalog_product():
    state = {"request": turn(on="2026-09-15"),
             "decision": Decision(action="respond", response="Dạ, mẫu này giá 890.000đ ạ."),
             "tool_calls": [
                 {"name": "catalog.search", "args": {"query": "Urban Classic"},
                  "result": {"items": [{"sku": "SKU-SN-CAS",
                                        "name": "Giày sneaker Urban Classic",
                                        "variants": [{"variant_sku": "SKU-SN-CAS-39-DEN"},
                                                     {"variant_sku": "SKU-SN-CAS-40-DEN"}]}]}},
                 {"name": "pricing.get_quote",
                  "args": {"sku": "SKU-SN-CAS-39-DEN", "on": "2026-09-15"},
                  "result": {"sku": "SKU-SN-CAS-39-DEN", "final_price_vnd": 890000}},
             ]}
    assert response_price_precondition(state) is None
    state["tool_calls"].append({"name": "pricing.get_quote",
                                "args": {"sku": "SKU-SN-CAS-40-DEN", "on": "2026-09-15"},
                                "result": {"sku": "SKU-SN-CAS-40-DEN",
                                           "final_price_vnd": 890000}})
    assert response_price_precondition(state) == ("price_without_quote", None)


def test_llm_price_flag_triggers_sweep_when_regex_misses():
    assert detect_price_intent("xem giúp hai mẫu này").needs_price is False
    model = FakeModel({"action": "tool", "needs_price": True,
                       "tool_name": "catalog.search", "tool_args": {"query": "máy lọc"}})
    tools = FakeTools({"crm.get_customer": {"found": False},
                       "catalog.search": {"items": [
                           {"sku": "SKU-AP-X", "name": "AirPure X"},
                           {"sku": "SKU-AP-Y", "name": "AirPure Y"}], "total": 2},
                       ("pricing.get_quote", "SKU-AP-X"): {
                           "sku": "SKU-AP-X", "final_price_vnd": 4390000},
                       ("pricing.get_quote", "SKU-AP-Y"): {
                           "sku": "SKU-AP-Y", "final_price_vnd": 5200000}})
    response = asyncio.run(harness(model, tools).run(turn(
        on="2026-09-15", text="xem giúp hai mẫu này")))
    assert "2/2 mẫu" in response.agent_text
    assert [args["on"] for name, args in tools.calls if name == "pricing.get_quote"] \
        == ["2026-09-15", "2026-09-15"]


def test_quote_failure_uses_neutral_answer_and_handoff():
    model = FakeModel({"action": "tool", "tool_name": "pricing.get_quote",
                       "tool_args": {"sku": "SKU-AP-X"}})
    tools = FakeTools({"crm.get_customer": {"found": False},
                       "pricing.get_quote": {"error": "tool_unavailable"}})
    response = asyncio.run(harness(model, tools).run(turn(
        text="AirPure X giá bao nhiêu?")))
    assert response.needs_handoff is True
    assert "4.890.000" not in response.agent_text
    assert "chưa kiểm tra được" in response.agent_text


def test_sweep_quote_failure_never_uses_catalog_list_price():
    model = FakeModel({"action": "tool", "tool_name": "catalog.search",
                       "needs_price": True, "tool_args": {"query": "máy lọc"}})
    tools = FakeTools({"crm.get_customer": {"found": False},
                       "catalog.search": {"items": [
                           {"sku": "SKU-AP-X", "name": "AirPure X",
                            "list_price_vnd": 4890000},
                           {"sku": "SKU-AP-Y", "name": "AirPure Y",
                            "list_price_vnd": 5200000}], "total": 2},
                       "pricing.get_quote": {"error": "tool_unavailable"}})
    response = asyncio.run(harness(model, tools).run(turn(
        text="giá các mẫu máy lọc bao nhiêu?")))
    assert response.needs_handoff is True
    assert "4.890.000" not in response.agent_text
    assert "5.200.000" not in response.agent_text
    assert "chưa kiểm tra được báo giá" in response.agent_text
