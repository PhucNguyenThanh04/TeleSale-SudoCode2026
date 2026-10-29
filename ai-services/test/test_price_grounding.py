"""Price claims need quote evidence; a verified empty search may repeat a budget."""

import pytest

from app.agent.guardrails.checks import _money_claims, check_answer


def _empty_search(budget=2_000_000):
    return [{"name": "catalog.search",
             "args": {"query": "máy lọc", "max_price_vnd": budget,
                      "min_room_area_m2": 25},
             "result": {"items": [], "total": 0}}]


def _matched_search(budget=5_000_000):
    calls = _empty_search(budget)
    calls[0]["result"] = {"items": [{"sku": "SKU-TEST", "name": "Máy lọc Test"}], "total": 1}
    return calls


def _quote(price=4_890_000):
    return [{"name": "pricing.get_quote", "args": {"sku": "SKU-TEST"},
             "result": {"sku": "SKU-TEST", "list_price_vnd": price,
                        "final_price_vnd": price, "applied_promos": []}}]


def test_empty_search_may_repeat_exact_customer_budget_with_room_area():
    customer = "Tư vấn máy lọc, ngân sách 2 tr trong phòng 25m2."
    answer = "Dạ, chưa có mẫu phù hợp trong ngân sách 2 tr cho phòng 25m2 ạ."
    assert _money_claims(answer) == [(2_000_000, "price", False)]
    assert check_answer(answer, _empty_search(), customer) == (answer, None)


def test_empty_search_can_repeat_another_budget_wording():
    customer = "Tư vấn máy lọc cho phòng 25m2, ngân sách tối đa 1 triệu."
    answer = "Dạ, chưa có mẫu phù hợp trong tầm giá 1 triệu cho phòng 25m2 ạ."
    assert check_answer(answer, _empty_search(1_000_000), customer) == (answer, None)


@pytest.mark.parametrize("answer", [
    "Dạ, chưa có mẫu phù hợp trong ngân sách 3 tr ạ.",
    "Dạ, chưa có mẫu trong ngân sách 2 tr; mẫu khác giá 2 tr ạ.",
    "Dạ, mẫu này giá 2 tr ạ.",
])
def test_empty_search_budget_exception_does_not_authorize_product_prices(answer):
    customer = "Ngân sách 2 tr cho phòng 25m2."
    assert check_answer(answer, _empty_search(), customer)[1] == "price_without_quote"


def test_empty_search_budget_must_match_customer_and_actual_result():
    answer = "Dạ, chưa có mẫu phù hợp trong ngân sách 2 tr ạ."
    assert check_answer(answer, _empty_search(), "Máy cho phòng 25m2?")[1] == "price_without_quote"
    nonempty = _empty_search()
    nonempty[0]["result"] = {"items": [{"sku": "SKU-TEST"}], "total": 1}
    assert check_answer(answer, nonempty, "Ngân sách 2 tr.")[1] == "price_without_quote"
    inconsistent = _empty_search()
    inconsistent[0]["result"]["total"] = 1
    assert check_answer(answer, inconsistent, "Ngân sách 2 tr.")[1] == "price_without_quote"


@pytest.mark.parametrize("customer,answer", [
    ("Nhà có bé, ngân sách tầm 5 triệu.",
     "Dạ, với ngân sách 5 triệu, em đã tìm thấy một mẫu để chị cân nhắc ạ."),
    ("Phòng 25m2, em chỉ muốn chi tối đa 5 tr.",
     "Dạ, theo mức tối đa 5 tr chị nêu, em tìm thấy Máy lọc Test ạ."),
])
def test_nonempty_catalog_may_repeat_customer_budget_without_quoting_price(customer, answer):
    assert check_answer(answer, _matched_search(), customer) == (answer, None)


@pytest.mark.parametrize("answer", [
    "Dạ, Máy lọc Test giá 5 triệu ạ.",
    "Dạ, với ngân sách 5 triệu, Máy lọc Test giá 4,9 triệu ạ.",
    "Dạ, Máy lọc Test chỉ 5 triệu, vừa ngân sách ạ.",
    "Dạ, chưa có mẫu phù hợp trong ngân sách 5 triệu ạ.",
])
def test_nonempty_catalog_budget_does_not_authorize_unquoted_prices_or_false_empty(answer):
    assert check_answer(answer, _matched_search(), "Ngân sách tầm 5 triệu.")[1] == "price_without_quote"


@pytest.mark.parametrize("spoken", ["2tr", "2 triệu", "2.000.000đ", "2,99 triệu"])
def test_mismatched_product_price_is_blocked_for_common_formats(spoken):
    answer = f"Mẫu này giá {spoken} ạ."
    assert check_answer(answer, _quote())[1] == "price_without_quote"


def test_mismatched_price_next_to_area_and_customer_budget_is_blocked():
    answer = "Mẫu này 2,99 triệu, phù hợp phòng 25m2 ạ."
    assert _money_claims(answer) == [(2_990_000, "price", False)]
    assert check_answer(answer, _quote(), "Ngân sách 2 tr cho phòng 25m2.")[1] == "price_without_quote"
    assert check_answer(answer, _empty_search(), "Ngân sách 2 tr cho phòng 25m2.")[1] == "price_without_quote"


@pytest.mark.parametrize("spoken", ["2tr", "2 triệu", "2.000.000đ"])
def test_matching_quote_price_still_passes(spoken):
    answer = f"Mẫu này giá {spoken} ạ."
    assert check_answer(answer, _quote(2_000_000)) == (answer, None)


def test_other_price_checks_stay_active():
    assert check_answer("Mẫu này giá 2 tr ạ.", [])[1] == "price_without_quote"
    assert check_answer("Mẫu này giá 2 tr ạ.", _quote(2_990_000))[1] == "price_without_quote"
    assert check_answer("Mẫu này giá 2,99 triệu ạ.", _quote(2_990_000))[1] is None
