
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
    "Dạ, ngân sách của chị là 6 triệu đúng không ạ?",
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
    "Điều gì phù hợp nhất với chị? Mẫu này tốt nhất ạ.",
])
def test_clarification_does_not_exempt_other_claims(answer):
    assert check_grounding(answer, []) or check_answer(
        answer, [], "Ngân sách của tôi 5 triệu.")[1]


@pytest.mark.parametrize("answer", [
    "Ngân sách của chị là 5 triệu đúng không ạ?",
    "Chị muốn giữ ngân sách 5 triệu ạ?",
])
def test_budget_confirmation_needs_customer_evidence(answer):
    assert check_answer(answer, [], "Tôi cần máy lọc.")[1] == "price_without_quote"


@pytest.mark.parametrize("amount", ["4.9 triệu", "4,9 triệu", "4.900.000đ", "4,900,000đ"])
def test_price_formats_match_the_same_quote(amount):
    calls = [{"name": "pricing.get_quote", "args": {"sku": "SKU-TEST"},
              "result": {"sku": "SKU-TEST", "list_price_vnd": 4_900_000,
                         "final_price_vnd": 4_900_000, "applied_promos": []}}]
    answer = f"Mẫu này giá {amount} ạ."
    assert _money_claims(answer) == [(4_900_000, "price", False)]
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
