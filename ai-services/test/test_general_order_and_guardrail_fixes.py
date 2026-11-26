import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent.guardrails.checks import check_answer, check_grounding
from app.agent.guardrails.policy_grounding import policy_clarification_or_refusal
from app.agent.harness.context import _bounded_context
from app.agent.harness.policy import prepare_tool_call
from app.agent.harness.state import Decision
from app.agent.implementations.business_agent import BusinessTools
from app.mcp_servers.mcp_shared.basket import basket_money_evidenced
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
from app.schemas.agent import TextTurnRequest


def _request(text: str = "Ok em lên đơn giúp anh.", on: date = date(2026, 10, 20)) -> TextTurnRequest:
    return TextTurnRequest(
        session_id=uuid4(),
        client_msg_id=uuid4(),
        channel="hotline",
        channel_identity="0900000001",
        input_mode="clean",
        text=text,
        on=on,
    )


def _base_state(text: str = "Ok em lên đơn giúp anh.", on: date = date(2026, 10, 20)) -> dict:
    req = _request(text, on=on)
    return {
        "request": req,
        "safe_text": text,
        "identity_status": "known",
        "customer_id": "C001",
        "customer_phone": "0900000001",
        "tool_calls": [],
        "session_tool_calls": [
            {
                "name": "catalog.get_details",
                "args": {"sku": "SKU-ITEM-1"},
                "result": {
                    "items": [
                        {
                            "sku": "SKU-ITEM-1",
                            "name": "Sản phẩm Mẫu A",
                            "list_price_vnd": 2000000,
                            "attributes": {"warranty_months": 24},
                            "variants": [],
                        }
                    ]
                },
            },
            {
                "name": "inventory.check",
                "args": {"sku": "SKU-ITEM-1", "on": on.isoformat()},
                "result": {"sku": "SKU-ITEM-1", "in_stock": True, "qty": 10},
            },
            {
                "name": "pricing.get_quote",
                "args": {"sku": "SKU-ITEM-1", "on": on.isoformat(), "customer_phone": "0900000001"},
                "result": {
                    "sku": "SKU-ITEM-1",
                    "list_price_vnd": 2000000,
                    "final_price_vnd": 1800000,
                    "applied_promos": [],
                },
            },
        ],
    }


@pytest.mark.parametrize(
    ("raw_payment", "expected"),
    [
        ("chuyển khoản", "bank"),
        ("Chuyển khoản ngân hàng", "bank"),
        ("CK", "bank"),
        ("tiền mặt", "COD"),
        ("thanh toán khi nhận hàng", "COD"),
        ("ví MoMo", "momo"),
        ("ví ZaloPay", "zalopay"),
    ],
)
def test_order_create_normalizes_vietnamese_payment_aliases(raw_payment, expected):
    state = _base_state()
    state["decision"] = Decision(
        action="tool",
        tool_name="order.create",
        tool_args={"sku": "SKU-ITEM-1", "qty": 1, "price_vnd": 1800000, "payment": raw_payment},
    )
    prepared = prepare_tool_call(state, lambda: datetime.now(timezone.utc))
    assert prepared is not None
    _, args = prepared
    assert args["payment"] == expected


def test_order_create_reports_specific_precondition_reasons():
    gateway = AsyncMock()
    clock = lambda: datetime.now(timezone.utc)

    state_missing_price = _base_state()
    business = BusinessTools(gateway, state_missing_price, 5, clock)
    res_missing = asyncio.run(
        business.invoke("order.create", {"sku": "SKU-ITEM-1", "qty": 1, "payment": "COD"})
    )
    assert res_missing["error"] == "purchase_evidence_required"
    assert res_missing["reason"] == "missing_price_vnd"
    assert "price_vnd" in res_missing["next_action"]

    state_bad_pay = _base_state()
    business_pay = BusinessTools(gateway, state_bad_pay, 5, clock)
    res_pay = asyncio.run(
        business_pay.invoke("order.create", {"sku": "SKU-ITEM-1", "qty": 1, "price_vnd": 1800000, "payment": "bitcoin"})
    )
    assert res_pay["reason"] == "invalid_payment_method"

    state_conflict = _base_state()
    business_conflict = BusinessTools(gateway, state_conflict, 5, clock)
    res_conflict = asyncio.run(
        business_conflict.invoke(
            "order.create",
            {
                "sku": "SKU-ITEM-1",
                "price_vnd": 1800000,
                "lines": [{"sku": "SKU-ITEM-1", "qty": 1, "price_vnd": 1800000}],
                "payment": "COD",
            },
        )
    )
    assert res_conflict["reason"] == "conflicting_sku_and_lines"


def test_commerce_evidence_preserves_address_and_non_address_quotes_and_same_day_policy():
    state = _base_state()
    state["session_tool_calls"].extend(
        [
            {
                "name": "pricing.get_quote",
                "args": {
                    "sku": "SKU-ITEM-1",
                    "address": "Hà Nội",
                    "on": "2026-10-20",
                    "customer_phone": "0900000001",
                },
                "result": {
                    "sku": "SKU-ITEM-1",
                    "list_price_vnd": 2000000,
                    "final_price_vnd": 1800000,
                    "estimated_delivery": "2026-10-22",
                    "applied_promos": [],
                },
            },
            {
                "name": "policy.search",
                "args": {"query": "hoàn tiền COD", "on": "2026-10-20"},
                "result": {
                    "evidence": [
                        {"content": "Đơn COD hoàn tiền trong 5 ngày làm việc qua biểu mẫu hoàn tiền."}
                    ]
                },
            },
            {
                "name": "policy.search",
                "args": {"query": "chính sách cũ", "on": "2026-10-10"},
                "result": {"evidence": [{"content": "Chính sách cũ không còn hiệu lực."}]},
            },
        ]
    )
    calls = build_commerce_evidence(state)
    quotes = [c for c in calls if c["name"] == "pricing.get_quote"]
    assert len(quotes) == 2
    assert {q["args"].get("address") for q in quotes} == {None, "Hà Nội"}

    policies = [c for c in calls if c["name"] == "policy.search"]
    assert len(policies) == 1
    assert policies[0]["args"]["on"] == "2026-10-20"

    state["decision"] = Decision(
        action="tool",
        tool_name="order.create",
        tool_args={"sku": "SKU-ITEM-1", "qty": 1, "price_vnd": 1800000, "payment": "COD"},
    )
    assert prepare_tool_call(state, lambda: datetime.now(timezone.utc)) is not None

    _, delivery_err = check_answer(
        "Sản phẩm Mẫu A có giá 1.800.000đ, dự kiến giao ngày 22/10/2026.",
        calls,
        "Giao Hà Nội khi nào nhận được?",
    )
    assert delivery_err is None


def test_mixed_policy_threshold_and_product_quote_passes_while_unverified_fails():
    calls = [
        {
            "name": "catalog.get_details",
            "args": {"sku": "SKU-A"},
            "result": {"items": [{"sku": "SKU-A", "name": "Máy Mẫu A", "list_price_vnd": 2990000}]},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-A", "on": "2026-10-21"},
            "result": {"sku": "SKU-A", "list_price_vnd": 2990000, "final_price_vnd": 2990000, "applied_promos": []},
        },
        {
            "name": "policy.search",
            "args": {"query": "gói bảo hành mở rộng", "on": "2026-10-21"},
            "result": {
                "evidence": [
                    {"content": "Gói bảo hành mở rộng áp dụng cho máy có giá từ 3.000.000đ trở lên."}
                ]
            },
        },
    ]
    _, err_ok = check_answer(
        "Máy Mẫu A có giá 2.990.000đ; chính sách bảo hành mở rộng chỉ áp dụng cho máy từ 3.000.000đ trở lên.",
        calls,
        "Máy Mẫu A có mua thêm gói bảo hành mở rộng được không?",
    )
    assert err_ok is None

    _, err_bad = check_answer(
        "Máy Mẫu A có giá 2.990.000đ; chính sách bảo hành mở rộng chỉ áp dụng cho máy từ 4.500.000đ trở lên.",
        calls,
        "Máy Mẫu A có mua thêm gói bảo hành mở rộng được không?",
    )
    assert err_bad == "price_without_quote"


def test_customer_budget_echo_passes_and_unverified_amount_fails():
    calls = [
        {
            "name": "catalog.search",
            "args": {"query": "Quạt Mẫu B"},
            "result": {"items": [{"sku": "SKU-B", "name": "Quạt Mẫu B", "list_price_vnd": 2450000}]},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-B", "qty": 2, "on": "2026-10-20"},
            "result": {"sku": "SKU-B", "list_price_vnd": 2450000, "final_price_vnd": 2450000, "applied_promos": []},
        },
    ]
    customer_text = "Chị muốn hai quạt Quạt Mẫu B, tối đa 2.500.000đ cho cả hai chiếc."
    _, err_ok = check_answer(
        "Quạt Mẫu B giá 2.450.000đ mỗi chiếc, tổng 2 chiếc là 4.900.000đ, vượt ngân sách tối đa 2.500.000đ của chị.",
        calls,
        customer_text,
    )
    assert err_ok is None

    _, err_bad = check_answer(
        "Quạt Mẫu B giá 2.450.000đ mỗi chiếc, vượt ngân sách tối đa 3.200.000đ của chị.",
        calls,
        customer_text,
    )
    assert err_bad == "price_without_quote"


def test_basket_money_evidenced_handles_total_with_unit_breakdown_and_list_price():
    calls = [
        {
            "name": "catalog.search",
            "args": {"query": "Máy Mini"},
            "result": {"items": [{"sku": "SKU-MINI", "name": "Máy Mini", "list_price_vnd": 2190000}]},
        },
        {
            "name": "pricing.quote_order",
            "args": {"lines": [{"sku": "SKU-MINI", "qty": 2}], "on": "2026-10-29"},
            "result": {
                "units": [
                    {"unit": 1, "line": 0, "sku": "SKU-MINI", "list_price_vnd": 2190000, "final_price_vnd": 2190000, "applied_promos": []},
                    {
                        "unit": 2,
                        "line": 0,
                        "sku": "SKU-MINI",
                        "list_price_vnd": 2190000,
                        "final_price_vnd": 1095000,
                        "applied_promos": [{"promo_code": "SECOND-50", "type": "percent", "discount_vnd": 1095000}],
                    },
                ],
                "total_vnd": 3285000,
                "freeship": False,
            },
        },
    ]
    assert basket_money_evidenced(
        "Tổng 2 máy Máy Mini là 3.285.000đ (máy 1 giá 2.190.000đ, máy 2 giảm 1.095.000đ còn 1.095.000đ).",
        calls,
    )
    assert basket_money_evidenced(
        "Máy Mini có giá niêm yết 2.190.000đ; tổng cả đơn là 3.285.000đ.",
        calls,
    )
    assert not basket_money_evidenced(
        "Tổng 2 máy Máy Mini là 3.000.000đ.",
        calls,
    )


def test_catalog_warranty_and_pii_refusal_do_not_false_positive_policy():
    calls = [
        {
            "name": "catalog.get_details",
            "args": {"sku": "SKU-W"},
            "result": {
                "items": [
                    {
                        "sku": "SKU-W",
                        "name": "Máy Lọc W",
                        "list_price_vnd": 3000000,
                        "attributes": {"warranty_months": 24},
                    }
                ]
            },
        }
    ]
    assert check_grounding("Máy Lọc W có thời gian bảo hành 24 tháng.", calls) is None
    assert check_grounding("Máy Lọc W có thời gian bảo hành 36 tháng.", calls) == "unsupported_policy_or_internal_claim"
    assert check_grounding("Máy Lọc W được đổi trả trong 7 ngày.", calls) == "unsupported_policy_or_internal_claim"

    assert policy_clarification_or_refusal(
        "Dạ em không được phép lưu hay nhắc lại thông tin tài khoản ngân hàng và CCCD qua cuộc gọi; "
        "chị vui lòng nhập trực tiếp vào biểu mẫu hoàn tiền của hệ thống ạ."
    )
    assert not policy_clarification_or_refusal(
        "Em không được phép lưu số tài khoản và đơn của chị được hoàn tiền trong 5 ngày."
    )


def test_attribute_feature_binds_per_clause_and_ignores_requirement_echo():
    calls = [
        {
            "name": "catalog.search",
            "args": {"query": "máy lọc không khí"},
            "result": {
                "items": [
                    {"sku": "SKU-X", "name": "Máy Lọc X", "attributes": {"features": "HEPA H13"}},
                    {"sku": "SKU-Y", "name": "Máy Lọc Y", "attributes": {"child_safe_lock": True}},
                ]
            },
        }
    ]
    assert check_grounding(
        "Với nhu cầu có khóa trẻ em của anh, Máy Lọc X chưa rõ khóa trẻ em, còn Máy Lọc Y có khóa trẻ em.",
        calls,
    ) is None
    assert check_grounding(
        "Máy Lọc X có khóa trẻ em.",
        calls,
    ) == "unsupported_product_spec"


def test_bounded_context_keeps_complete_for_large_tool_observations():
    context = {
        "source_context_complete": True,
        "customer_facts": {},
        "sales_history": {},
        "customer_statements": [],
        "session_history": [],
        "previous_episodes": [],
        "current_episode": {},
        "call_brief": {},
        "tool_observations": [{"name": "catalog.get_details", "result": {"data": "x" * 20000}}],
        "delivery_context": None,
    }
    bounded = _bounded_context(context)
    assert bounded["context_completeness"]["complete"] is True


def test_progressive_stream_waits_for_verified_complete_answer():
    from langchain_core.messages import AIMessageChunk
    from app.agent.harness.streaming import GuardedStream

    async def run():
        emitted = []

        async def sink(text):
            emitted.append(text)
            return True

        stream = GuardedStream(sink, progressive=True)
        st = _base_state("Sản phẩm Mẫu A giá bao nhiêu và còn hàng không?")
        await stream.feed(AIMessageChunk(content="Sản phẩm Mẫu A có giá 1.800.000đ. ", id="m1"), st)
        assert emitted == []
        await stream.feed(AIMessageChunk(content="Hiện sản phẩm vẫn còn hàng.", id="m1"), st)
        st["verified_answer"] = "Sản phẩm Mẫu A có giá 1.800.000đ. Hiện sản phẩm vẫn còn hàng."
        final = await stream.finish(st["verified_answer"], st)
        assert final == st["verified_answer"]
        assert emitted == [st["verified_answer"]]

        held_emitted = []

        async def held_sink(text):
            held_emitted.append(text)
            return True

        held_stream = GuardedStream(held_sink, progressive=True)
        await held_stream.feed(AIMessageChunk(content="Sản phẩm Mẫu A có giá 9.999.000đ. ", id="m2"), st)
        assert held_emitted == []

        pii_stream = GuardedStream(held_sink, progressive=True)
        await pii_stream.feed(AIMessageChunk(content="Số điện thoại của anh là 0912345678. ", id="m3"), st)
        assert held_emitted == []

        preamble_stream = GuardedStream(held_sink, progressive=True)
        await preamble_stream.feed(AIMessageChunk(content="Để em kiểm tra tồn kho giúp anh nhé. ", id="m4"), st)
        assert held_emitted == []

    asyncio.run(run())


def test_agent_nodes_skips_semantic_review_when_disabled():
    from unittest.mock import patch
    from app.agent.harness.agent_nodes import AgentNodes

    nodes = AgentNodes(
        llm=AsyncMock(),
        tools=None,
        memory=AsyncMock(),
        max_tool_calls=4,
        prompt_history_turns=6,
        semantic_review_enabled=False,
    )
    st = _base_state("Sản phẩm Mẫu A giá bao nhiêu?")
    st["agent_draft"] = "Sản phẩm Mẫu A có giá 1.800.000đ."
    with patch("app.agent.harness.agent_nodes.review_answer", new_callable=AsyncMock) as mock_review:
        out = asyncio.run(nodes.verify_agent(st))
    assert out["reply_error"] is None
    assert out["verified_answer"] == "Sản phẩm Mẫu A có giá 1.800.000đ."
    assert mock_review.await_count == 0


def test_comma_separated_multi_sku_prices_and_same_clause_policy_fee():
    calls = [
        {
            "name": "catalog.search",
            "args": {"query": "Ghế A"},
            "result": {"items": [{"sku": "SKU-CHAIR", "name": "Ghế Mẫu A", "list_price_vnd": 4990000}]},
        },
        {
            "name": "catalog.search",
            "args": {"query": "Xe B"},
            "result": {"items": [{"sku": "SKU-STROLLER", "name": "Xe Đẩy Mẫu B", "list_price_vnd": 3490000}]},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-CHAIR", "on": "2026-10-23"},
            "result": {"sku": "SKU-CHAIR", "list_price_vnd": 4990000, "final_price_vnd": 4990000, "applied_promos": []},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-STROLLER", "on": "2026-10-23"},
            "result": {"sku": "SKU-STROLLER", "list_price_vnd": 3490000, "final_price_vnd": 3490000, "applied_promos": []},
        },
    ]
    _, err_ok = check_answer(
        "Ghế Mẫu A có giá 4.990.000đ, xe đẩy Mẫu B có giá 3.490.000đ.",
        calls,
        "Hai mẫu này giá từng món bao nhiêu?",
    )
    assert err_ok is None

    _, err_swapped = check_answer(
        "Ghế Mẫu A có giá 3.490.000đ, xe đẩy Mẫu B có giá 4.990.000đ.",
        calls,
        "Hai mẫu này giá từng món bao nhiêu?",
    )
    assert err_swapped == "price_without_quote"

    policy_calls = [
        {
            "name": "catalog.get_details",
            "args": {"sku": "SKU-COAT"},
            "result": {"items": [{"sku": "SKU-COAT", "name": "Áo Khoác Mẫu C", "list_price_vnd": 690000}]},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-COAT", "address": "Hà Nội", "on": "2026-10-15"},
            "result": {"sku": "SKU-COAT", "list_price_vnd": 690000, "final_price_vnd": 690000, "applied_promos": []},
        },
        {
            "name": "policy.search",
            "args": {"query": "phí ship Hà Nội", "on": "2026-10-15"},
            "result": {
                "evidence": [
                    {"content": "Phí vận chuyển nội thành Hà Nội là 30.000đ, miễn phí vận chuyển cho đơn từ 1.000.000đ."}
                ]
            },
        },
    ]
    _, err_mixed = check_answer(
        "Áo Khoác Mẫu C giá 690.000đ nên chưa đạt ngưỡng miễn phí vận chuyển từ 1.000.000đ, phí vận chuyển là 30.000đ.",
        policy_calls,
        "Phí vận chuyển Hà Nội thế nào?",
    )
    assert err_mixed is None

    _, err_mixed_bad = check_answer(
        "Áo Khoác Mẫu C giá 690.000đ, phí vận chuyển là 55.000đ.",
        policy_calls,
        "Phí vận chuyển Hà Nội thế nào?",
    )
    assert err_mixed_bad == "price_without_quote"


def test_promotion_grounding_accepts_address_and_non_address_quotes_and_same_sku_basket():
    from app.agent.guardrails.promotion_grounding import check_promotion_grounding

    dual_quote_calls = [
        {
            "name": "catalog.get_details",
            "args": {"sku": "SKU-ITEM-1"},
            "result": {"items": [{"sku": "SKU-ITEM-1", "name": "Sản phẩm Mẫu A"}]},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-ITEM-1", "on": "2026-10-20"},
            "result": {
                "sku": "SKU-ITEM-1",
                "list_price_vnd": 1000000,
                "final_price_vnd": 1000000,
                "applied_promos": [{"promo_code": "COD-0", "type": "freecod", "discount_vnd": 0}],
                "freeship": False,
            },
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-ITEM-1", "address": "Hà Nội", "on": "2026-10-20"},
            "result": {
                "sku": "SKU-ITEM-1",
                "list_price_vnd": 1000000,
                "final_price_vnd": 1000000,
                "applied_promos": [{"promo_code": "COD-0", "type": "freecod", "discount_vnd": 0}],
                "freeship": True,
            },
        },
    ]
    assert check_promotion_grounding(
        "Sản phẩm Mẫu A được miễn phí COD và miễn phí vận chuyển.",
        dual_quote_calls,
    ) is None

    basket_calls = [
        {
            "name": "catalog.search",
            "args": {"query": "Máy Mini"},
            "result": {"items": [{"sku": "SKU-MINI", "name": "Máy Mini"}]},
        },
        {
            "name": "pricing.quote_order",
            "args": {"lines": [{"sku": "SKU-MINI", "qty": 2}], "on": "2026-10-29"},
            "result": {
                "units": [
                    {"unit": 1, "line": 0, "sku": "SKU-MINI", "list_price_vnd": 2190000, "final_price_vnd": 2190000, "applied_promos": []},
                    {
                        "unit": 2,
                        "line": 0,
                        "sku": "SKU-MINI",
                        "list_price_vnd": 2190000,
                        "final_price_vnd": 1095000,
                        "applied_promos": [{"promo_code": "SECOND-50", "type": "percent", "discount_vnd": 1095000}],
                    },
                ],
                "total_vnd": 3285000,
                "order_promos": [{"promo_code": "COD-0", "type": "freecod", "discount_vnd": 0}],
                "freeship": True,
            },
        },
    ]
    assert check_promotion_grounding(
        "Đơn 2 máy Máy Mini được giảm 50% theo mã SECOND-50 và miễn phí COD.",
        basket_calls,
    ) is None


def test_progressive_stream_finish_publishes_repaired_answer_after_greeting_prefix():
    from langchain_core.messages import AIMessageChunk
    from app.agent.harness.streaming import GuardedStream

    async def run():
        emitted = []

        async def sink(text):
            emitted.append(text)
            return True

        stream = GuardedStream(sink, progressive=True)
        st = _base_state("Giá sản phẩm Mẫu A hôm nay thế nào?")
        await stream.feed(AIMessageChunk(content="Dạ em chào anh. ", id="m1"), st)
        assert emitted == []
        await stream.feed(AIMessageChunk(content="Giá là 9.999.000đ. ", id="m1"), st)
        st["verified_answer"] = "Sản phẩm Mẫu A hiện có giá 1.800.000đ."
        final = await stream.finish(st["verified_answer"], st)
        assert "1.800.000đ" in final
        assert emitted == [st["verified_answer"]]

    asyncio.run(run())


def test_expired_customer_mentioned_discount_is_allowed_while_fabricated_rejected():
    calls = [
        {
            "name": "catalog.get_details",
            "args": {"sku": "SKU-X"},
            "result": {"items": [{"sku": "SKU-X", "name": "Máy Mẫu X", "list_price_vnd": 4890000}]},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-X", "on": "2026-10-15"},
            "result": {
                "sku": "SKU-X",
                "list_price_vnd": 4890000,
                "final_price_vnd": 4890000,
                "applied_promos": [],
                "expired_promos": ["AP-SEP"],
            },
        },
    ]
    _, err_ok = check_answer(
        "Lần trước giá sau giảm 500.000đ (mã AP-SEP) là 4.390.000đ nhưng đã hết hạn rồi ạ; giá hiện tại của Máy Mẫu X là 4.890.000đ.",
        calls,
        "Chị gọi lại lấy Máy Mẫu X giảm 500k hôm trước nhé.",
    )
    assert err_ok is None

    _, err_current_wrong = check_answer(
        "Giá hiện tại của Máy Mẫu X là 4.390.000đ.",
        calls,
        "Chị gọi lại lấy Máy Mẫu X giảm 500k hôm trước nhé.",
    )
    assert err_current_wrong == "price_without_quote"

    _, err_fabricated = check_answer(
        "Chương trình giảm 800.000đ (mã AP-SEP) đã hết hạn rồi ạ; giá hiện tại của Máy Mẫu X là 4.890.000đ.",
        calls,
        "Chị gọi lại lấy Máy Mẫu X giảm 500k hôm trước nhé.",
    )
    assert err_fabricated == "price_without_quote"


def test_numeric_zalo_identity_does_not_authenticate_as_a_phone():
    from app.agent.harness.session_identity import initialize_identity

    async def run():
        tools = AsyncMock()
        tools.invoke.side_effect = [
            {"found": False},
            {"found": True, "customer_id": "C030", "phone": "0991280845", "honorific": "anh", "orders": [], "sessions": []},
        ]
        req = TextTurnRequest(
            session_id=uuid4(),
            client_msg_id=uuid4(),
            channel="zalo_oa",
            channel_identity="0991280845",
            input_mode="clean",
            text="Anh hỏi lại mẫu hôm trước",
            on=date(2026, 10, 20),
        )
        identity, calls = await initialize_identity(req, tools)
        assert identity["identity_status"] == "unknown"
        assert identity["customer_id"] is None
        assert [call["args"] for call in calls] == [{"zalo_id": "0991280845"}]
        tools.invoke.assert_awaited_once()

    asyncio.run(run())


def test_facts_used_credits_variant_size_color_from_catalog_get_details():
    from eval_harness.reference_adapter import facts_used

    details_call = {
        "name": "catalog.get_details",
        "args": {"sku": "SKU-SHOE-41-XAM"},
        "result": {
            "items": [
                {
                    "sku": "SKU-SHOE",
                    "name": "Giày Trekking Mẫu Z",
                    "variants": [
                        {"variant_sku": "SKU-SHOE-41-XAM", "size": "41", "color": "xám"},
                    ],
                }
            ]
        },
    }
    quote_call = {
        "name": "pricing.get_quote",
        "args": {"sku": "SKU-SHOE-41-XAM", "on": "2026-10-21"},
        "result": {"sku": "SKU-SHOE-41-XAM", "final_price_vnd": 1990000},
    }
    scoped = {
        "product": {
            "SKU-SHOE": {
                "product_advised": {"value": "SKU-SHOE", "source": "langmem:prev-session:turn-1", "status": "active"},
                "size": {"value": "41", "source": "langmem:prev-session:turn-1", "status": "active"},
                "color": {"value": "xám", "source": "langmem:prev-session:turn-1", "status": "active"},
            }
        },
        "room": {},
    }
    used = facts_used(
        "Mẫu Giày Trekking Mẫu Z màu xám size 41 hiện còn hàng.",
        [details_call, quote_call],
        {},
        scoped,
        current_session_id="curr-session",
        customer_text="Kiểm tra lại mẫu hôm trước giúp anh.",
    )
    assert set(used) >= {"product_advised", "size", "color"}


def test_order_update_reports_actionable_precondition_error():
    gateway = AsyncMock()
    clock = lambda: datetime.now(timezone.utc)
    st = _base_state("Đổi sang size L giúp anh.")
    st["owned_order_ids"] = ["OD123"]
    business = BusinessTools(gateway, st, 5, clock)
    res = asyncio.run(
        business.invoke(
            "order.update",
            {"order_id": "OD123", "action": "exchange_size", "new_variant_sku": "SKU-ITEM-1", "address": "Hà Nội"},
        )
    )
    assert res["error"] == "address_only_for_update_address"
    assert "address" in res["next_action"]


def test_self_declared_phone_parsing_does_not_authenticate_an_unlinked_channel():
    from app.agent.harness.session_identity import extract_self_declared_phone, initialize_identity

    assert extract_self_declared_phone("sdt minh 0994893949 de minh goi hotline sau nhe") == "0994893949"
    assert extract_self_declared_phone("Số điện thoại của chị là 0912345678.") == "0912345678"
    assert extract_self_declared_phone("Số của bạn chị là 0912345678.") is None
    assert extract_self_declared_phone("Chị gọi hộ em gái số 0912345678.") is None
    assert extract_self_declared_phone("Số chồng mình 0912345678.") is None
    assert extract_self_declared_phone("Số của mình 0912345678 hoặc 0987654321.") is None

    async def run():
        tools = AsyncMock()
        tools.invoke.side_effect = [
            {"found": False},
            {"found": True, "customer_id": "C017", "phone": "0994893949", "honorific": "chị", "orders": [], "sessions": []},
        ]
        req = TextTurnRequest(
            session_id=uuid4(),
            client_msg_id=uuid4(),
            channel="chat_fanpage",
            channel_identity="fb.khach.123",
            input_mode="clean",
            text="sdt minh 0994893949 de minh goi hotline sau nhe",
            on=date(2026, 10, 20),
        )
        identity, calls = await initialize_identity(req, tools)
        assert identity["identity_status"] == "unknown"
        assert identity["customer_id"] is None
        assert [call["args"] for call in calls] == [{"fb_id": "fb.khach.123"}]
        tools.invoke.assert_awaited_once()

    asyncio.run(run())
