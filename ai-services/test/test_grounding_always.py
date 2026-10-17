"""Always-on grounding stays active when optional answer checks are disabled."""

import asyncio
import logging

import pytest

from app.agent.guardrails.checks import FALLBACK, attribute_feature_status, check_answer
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.harness.runtime import AgentHarnessRuntime


def _state(attributes, answer="Máy này có HEPA H13 ạ."):
    return {
        "agent_draft": answer,
        "safe_text": "Tư vấn máy này",
        "tool_calls": [{
            "name": "catalog.search", "args": {"query": "máy lọc"},
            "result": {"items": [{"sku": "SKU-TEST", "name": "Máy lọc Test",
                                  "attributes": attributes}], "total": 1},
        }],
    }


@pytest.mark.parametrize("enabled", [True, False])
def test_grounding_rejects_unsupported_feature_with_both_flag_values(enabled):
    nodes = AgentNodes(None, None, None, 3, 3)
    nodes.guardrails_enabled = enabled
    result = asyncio.run(nodes.verify_agent(_state({})))
    assert result["agent_text"] == FALLBACK


@pytest.mark.parametrize("enabled", [True, False])
def test_grounding_accepts_evidenced_feature_with_both_flag_values(enabled):
    nodes = AgentNodes(None, None, None, 3, 3)
    nodes.guardrails_enabled = enabled
    result = asyncio.run(nodes.verify_agent(_state({"features": "HEPA H13"})))
    assert result["agent_text"] == "Máy này có HEPA H13 ạ."


def test_disabled_flag_logs_reason_and_startup_warning(monkeypatch):
    startup_events = []
    verify_events = []
    monkeypatch.setattr("app.agent.harness.runtime.log_event",
                        lambda *args, **kwargs: startup_events.append((args, kwargs)))
    monkeypatch.setattr("app.agent.harness.agent_nodes.log_event",
                        lambda *args, **kwargs: verify_events.append((args, kwargs)))
    AgentHarnessRuntime(None, None, None, guardrails_enabled=False)
    warnings = [(args, kwargs) for args, kwargs in startup_events
                if args[2] == "answer_check_disabled"]
    assert len(warnings) == 1
    assert warnings[0][1]["level"] == logging.WARNING
    assert "kiểm tra bằng chứng vẫn chạy" in warnings[0][1]["reason"]

    nodes = AgentNodes(None, None, None, 3, 3)
    nodes.guardrails_enabled = False
    asyncio.run(nodes.verify_agent(_state({"features": "HEPA H13"})))
    asyncio.run(nodes.verify_agent(_state({"features": "HEPA H13"})))
    assert len(startup_events) == 1
    assert any(args[2] == "grounding_checked" for args, _ in verify_events)
    assert sum(args[2] == "answer_check_disabled" and bool(kwargs.get("reason"))
               for args, kwargs in verify_events) == 2


@pytest.mark.parametrize("value,expected", [
    (True, "có"), (False, "không có"), (None, "chưa biết"),
])
def test_boolean_feature_status_distinguishes_false_from_missing(value, expected):
    attributes = {} if value is None else {"child_safe_lock": value}
    assert attribute_feature_status({"attributes": attributes}, "child_safe_lock") == expected


def test_explicit_false_overrides_free_text_feature_and_silence_is_unknown():
    item = {"attributes": {"child_safe_lock": False, "features": "khóa trẻ em"}}
    assert attribute_feature_status(item, "child_safe_lock") == "không có"
    assert attribute_feature_status({"attributes": {"features": "HEPA H13"}},
                                    "child_safe_lock") == "chưa biết"


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("attributes,answer,accepted", [
    ({"child_safe_lock": False}, "Máy lọc Test không có khóa trẻ em ạ.", True),
    ({"child_safe_lock": False}, "Máy lọc Test có khóa trẻ em ạ.", False),
    ({"child_safe_lock": True}, "Máy lọc Test có khóa trẻ em ạ.", True),
    ({"child_safe_lock": True}, "Máy lọc Test không có khóa trẻ em ạ.", False),
    ({}, "Máy lọc Test chưa có thông tin về khóa trẻ em ạ.", True),
    ({}, "Máy lọc Test có khóa trẻ em ạ.", False),
    ({}, "Máy lọc Test không có khóa trẻ em ạ.", False),
])
def test_feature_claim_matches_attributes_even_with_answer_checks_disabled(
        enabled, attributes, answer, accepted):
    nodes = AgentNodes(None, None, None, 3, 3)
    nodes.guardrails_enabled = enabled
    result = asyncio.run(nodes.verify_agent(_state(attributes, answer)))
    assert (result["agent_text"] == answer) is accepted


def test_feature_claim_is_checked_for_each_named_product_and_other_category():
    nodes = AgentNodes(None, None, None, 3, 3)
    nodes.guardrails_enabled = False
    state = _state({"child_safe_lock": False}, "Giày chạy Test có khóa trẻ em ạ.")
    state["tool_calls"][0]["result"]["items"] = [
        {"sku": "SKU-SHOE", "name": "Giày chạy Test", "attributes": {"child_safe_lock": False}},
        {"sku": "SKU-AIR", "name": "Máy lọc Air", "attributes": {"child_safe_lock": True}},
    ]
    assert asyncio.run(nodes.verify_agent(state))["agent_text"] == FALLBACK
    state["agent_draft"] = "Máy lọc Air có khóa trẻ em ạ. Giày chạy Test không có khóa trẻ em ạ."
    assert asyncio.run(nodes.verify_agent(state))["agent_text"] == state["agent_draft"]


@pytest.mark.parametrize("answer,accepted", [
    ("Máy lọc Test có HEPA H13 ạ.", True),
    ("Máy lọc Test không có HEPA H13 ạ.", False),
    ("Máy lọc Test chưa có thông tin về PM2.5 ạ.", True),
    ("Máy lọc Test không có PM2.5 ạ.", False),
])
def test_text_feature_claim_polarity_uses_catalog_evidence(answer, accepted):
    nodes = AgentNodes(None, None, None, 3, 3)
    nodes.guardrails_enabled = False
    result = asyncio.run(nodes.verify_agent(_state({"features": "HEPA H13"}, answer)))
    assert (result["agent_text"] == answer) is accepted


def test_empty_catalog_can_repeat_verified_customer_budget_without_inventing_price():
    calls = [{"name": "catalog.search", "args": {"query": "máy lọc không khí",
              "max_price_vnd": 1_000_000, "min_room_area_m2": 25},
              "result": {"items": [], "total": 0}}]
    customer = "Tư vấn máy lọc không khí cho phòng 25m2, ngân sách tối đa 1 triệu."
    answer = "Dạ, chưa có mẫu phù hợp phòng 25m2 trong ngân sách 1 triệu ạ."
    assert check_answer(answer, calls, customer) == (answer, None)
    invented = "Dạ, chưa có mẫu phù hợp trong ngân sách 2 triệu ạ."
    assert check_answer(invented, calls, customer)[1] == "price_without_quote"
