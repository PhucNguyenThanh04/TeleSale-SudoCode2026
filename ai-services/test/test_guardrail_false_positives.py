
import asyncio
import socket
from datetime import date
from types import SimpleNamespace

import pytest

from app.agent.guardrails.checks import _money_claims, check_answer, check_grounding
from app.agent.harness.agent_nodes import AgentNodes
from test_deep_memory import FakeToolModel


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("guardrail regression tests must stay offline")
    monkeypatch.setattr(socket.socket, "connect", denied)


@pytest.mark.parametrize("answer,customer", [
    ("Dạ, ngân sách của chị là 5 triệu đúng không ạ?", "Ngân sách của tôi 5 triệu."),
    ("Dạ, em sẽ kiểm tra ưu đãi hiện tại cho chị ạ.", "Có ưu đãi gì?"),
    ("Em kiểm tra xem còn hàng cho chị nhé.", "Tôi muốn hỏi về sản phẩm."),
    ("Chị muốn em kiểm tra còn hàng không ạ?", "Tôi muốn hỏi về sản phẩm."),
    ("Dạ, em sẽ tra cứu chính sách bảo hành cho chị ạ.", "Bảo hành thế nào?"),
    ("Dạ, chị cho em xin tên sản phẩm ạ.", "Sản phẩm này bảo hành thế nào?"),
    ("Em chưa xác nhận đã tạo đơn ạ.", "Đơn đã tạo chưa?"),
    ("Em không cung cấp giá nhập ạ.", "Giá nhập bao nhiêu?"),
    ("Điều gì phù hợp nhất với nhu cầu của chị ạ?", "Tôi cần tư vấn."),
])
def test_verifier_preserves_non_assertions(answer, customer):
    nodes = AgentNodes(FakeToolModel(replies=[]), None, None, 3, 3)
    result = asyncio.run(nodes.verify_agent({
        "agent_draft": answer, "safe_text": customer, "tool_calls": [],
        'request': SimpleNamespace(on=date(2031, 3, 12), input_mode='clean'),
        'identity_status': 'unknown',
    }))
    assert result["agent_text"] == answer
    assert not result.get("verifier_events")


@pytest.mark.parametrize("answer", [
    "Máy này giúp giảm bụi trong phòng ạ.",
    "Chị mua máy để tặng người thân ạ?",
    "Máy giúp tăng chất lượng không khí.",
])
def test_non_commercial_words_do_not_claim_a_promotion(answer):
    assert check_answer(answer, [])[1] is None


@pytest.mark.parametrize("answer", [
    "Mẫu này giá 5 triệu ạ.",
    "Ngân sách của chị là 5 triệu, mẫu này giá 5 triệu ạ.",
    "Mẫu này có giá bằng ngân sách của chị là 5 triệu.",
    "Không có mẫu phù hợp với ngân sách của chị là 5 triệu.",
    "Ngân sách của chị là 5 triệu; mẫu này còn hàng ạ.",
    "Em sẽ kiểm tra ưu đãi. Hiện được tặng màng lọc.",
    "Em sẽ kiểm tra ưu đãi và tặng chị một màng lọc.",
    "Em sẽ kiểm tra ưu đãi, hiện được tặng màng lọc.",
    "Chị muốn em kiểm tra còn hàng không ạ? Mẫu này còn hàng.",
    "Mẫu này còn hàng, chị muốn mua không ạ?",
    "Em sẽ tra cứu bảo hành. Sản phẩm bảo hành 2 năm.",
    "Em sẽ tra cứu bảo hành và cam kết hoàn tiền cho chị.",
    "Dạ, chị cho em xin tên sản phẩm, đơn này đủ điều kiện đổi trả ạ.",
    "Em chưa xác nhận đã tạo đơn; em đã tạo đơn rồi ạ.",
    "Em không cung cấp giá nhập; giá nhập là 2 triệu.",
])
def test_clarification_does_not_exempt_other_claims(answer):
    assert check_grounding(answer, []) or check_answer(
        answer, [], "Ngân sách của tôi 5 triệu.")[1]


@pytest.mark.parametrize("answer", [
    "Ngân sách của chị là 5 triệu đúng không ạ?",
    "Chị muốn giữ ngân sách 5 triệu ạ?",
])
def test_budget_confirmation_is_not_a_shop_price_claim(answer):
    assert check_answer(answer, [], "Tôi cần máy lọc.") == (answer, None)


@pytest.mark.parametrize("amount", ["4.9 triệu", "4,9 triệu", "4.900.000đ", "4,900,000đ"])
def test_price_formats_match_the_same_quote(amount):
    calls = [{"name": "pricing.get_quote", "args": {"sku": "SKU-TEST"},
              "result": {"sku": "SKU-TEST", "list_price_vnd": 4_900_000,
                         "final_price_vnd": 4_900_000, "applied_promos": []}}]
    answer = f"Mẫu này giá {amount} ạ."
    assert _money_claims(answer) == [(4_900_000, "price", False)]
    assert check_answer(answer, calls) == (answer, None)


def test_stock_count_before_trong_kho_is_not_read_as_millions():
    calls = [
        {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-XM-4P'},
         'result': {'sku': 'SKU-XM-4P', 'list_price_vnd': 5_490_000,
                    'final_price_vnd': 5_490_000, 'applied_promos': []}},
        {'name': 'inventory.check', 'args': {'sku': 'SKU-XM-4P'},
         'result': {'sku': 'SKU-XM-4P', 'in_stock': True, 'qty': 20}},
    ]
    answer = 'Giá 5.490.000đ. Hiện mẫu này còn hàng (20 trong kho) ạ.'
    assert check_answer(answer, calls) == (answer, None)
    assert check_answer(answer.replace('20 trong', '20 tr trong'), calls)[1] == 'price_without_quote'


@pytest.mark.parametrize('amount', ['2,03 triệu', '2.03 triệu'])
def test_decimal_millions_match_the_exact_quote(amount):
    calls = [{'name': 'pricing.get_quote', 'args': {'sku': 'SKU-TEST'},
              'result': {'sku': 'SKU-TEST', 'final_price_vnd': 2_030_000}}]
    answer = f'Mẫu này giá {amount}.'
    assert check_answer(answer, calls) == (answer, None)


@pytest.mark.parametrize("source,answer,accepted", [
    ("Bảo hành 12 tháng.", "Sản phẩm bảo hành 1 năm ạ.", True),
    ("Bảo hành 1 năm.", "Sản phẩm bảo hành 12 tháng ạ.", True),
    ("Bảo hành 12 tháng.", "Sản phẩm bảo hành 2 năm ạ.", False),
    ("Đổi trả 30 ngày.", "Chính sách đổi trả 1 tháng.", False),
])
def test_policy_durations_normalize_years_and_months_only(source, answer, accepted):
    calls = [{"name": "policy.search", "result": {"evidence": [{"content": source}]}}]
    assert (check_grounding(answer, calls) is None) is accepted
    assert (check_answer(answer, calls)[1] is None) is accepted


def test_mixed_budget_and_valid_price_remain_usable():
    calls = [{"name": "pricing.get_quote", "args": {"sku": "SKU-TEST"},
              "result": {"sku": "SKU-TEST", "list_price_vnd": 4_900_000,
                         "final_price_vnd": 4_900_000, "applied_promos": []}}]
    answer = "Ngân sách của chị là 5 triệu. Mẫu này giá 4,9 triệu ạ."
    assert check_answer(answer, calls, "Ngân sách của tôi 5 triệu.") == (answer, None)


@pytest.mark.parametrize('stock_sentence,reason', [
    ('SKU-XM-4P còn hàng.', None),
    ('Máy lọc không khí Xiaomi Smart 4 Pro còn hàng.', None),
    ('SKU-XM-FLT còn hàng.', 'stock_sku_mismatch'),
    ('SKU-XM-4P còn hàng. SKU-XM-FLT còn hàng.', 'stock_sku_mismatch'),
    ('SKU-XM-4P hết hàng.', 'stock_result_mismatch'),
])
def test_stock_claim_is_not_bound_to_a_gift_in_another_sentence(stock_sentence, reason):
    calls = [
        {'name': 'catalog.search', 'args': {}, 'result': {'items': [
            {'sku': 'SKU-XM-4P', 'name': 'Máy lọc không khí Xiaomi Smart 4 Pro', 'variants': []}]}},
        {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-XM-4P', 'on': '2026-10-20'},
         'result': {'sku': 'SKU-XM-4P', 'final_price_vnd': 5490000, 'applied_promos': [
             {'promo_code': 'XM-COMBO', 'type': 'gift', 'gift_sku': 'SKU-XM-FLT'}]}},
        {'name': 'inventory.check', 'args': {'sku': 'SKU-XM-4P', 'on': '2026-10-20'},
         'result': {'in_stock': True, 'qty': 20}},
    ]
    answer = stock_sentence + ' Được tặng quà SKU-XM-FLT.'
    assert check_grounding(answer, calls) is None
    assert check_answer(answer, calls)[1] == reason


_CREATED_ORDER = {"name": "order.create",
                  "args": {"sku": "SKU-AP-FLT-P", "qty": 1, "price_vnd": 990000, "payment": "COD"},
                  "result": {"order_id": "OD600025", "status": "created", "total_vnd": 990000,
                             "needs_confirmation_call": False, "estimated_delivery": "2026-10-28"}}


def test_created_order_total_evidences_repeated_price():
    answer = ("Dạ, em đã lên đơn một màng lọc thay thế cho máy AirPure Pro của chị với giá 990.000đ rồi ạ. "
              "Mã đơn hàng của chị là OD600025, dự kiến chị sẽ nhận được hàng vào ngày 28/10.")
    assert check_answer(answer, [_CREATED_ORDER])[1] is None


def test_created_order_does_not_evidence_other_price():
    answer = "Dạ, em đã lên đơn OD600025 với giá 890.000đ rồi ạ."
    assert check_answer(answer, [_CREATED_ORDER])[1] == "price_without_quote"
    failed = {**_CREATED_ORDER, "result": {"error": "price_mismatch"}}
    assert check_answer("Dạ, em đã lên đơn với giá 990.000đ rồi ạ.", [failed])[1] is not None


_STATUS_LOOKUP = {"name": "order.status", "args": {"order_id": "OD600004"},
                  "result": {"orders": [{"order_id": "OD600004", "sku": "SKU-AF-6L", "qty": 1,
                                         "total_vnd": 3990000, "created_on": "2026-10-28",
                                         "status": "created", "payment": "COD"}]}}


@pytest.mark.parametrize("answer", [
    "Dạ chị, hiện tại đơn hàng nồi chiên không dầu của chị vẫn đang ở trạng thái **đã tạo** ạ.",
    "Dạ, đơn hàng chị đã đặt hôm 28/10 hiện đang chờ xử lý ạ.",
    "Dạ, đơn OD600004 đã được tạo và đang chờ bàn giao vận chuyển ạ.",
])
def test_order_status_lookup_evidences_existing_order(answer):
    assert check_grounding(answer, [_STATUS_LOOKUP]) is None


@pytest.mark.parametrize("answer,calls", [
    ("Dạ, em đã lên đơn mới cho chị rồi ạ.", [_STATUS_LOOKUP]),
    ("Dạ, em vừa tạo đơn cho chị ạ.", [_STATUS_LOOKUP]),
    ("Dạ, đơn hàng chị đã đặt hôm 28/10 hiện đang chờ xử lý ạ.", []),
])
def test_new_order_claim_still_requires_order_create(answer, calls):
    assert check_grounding(answer, calls) == "order_creation_unverified"
