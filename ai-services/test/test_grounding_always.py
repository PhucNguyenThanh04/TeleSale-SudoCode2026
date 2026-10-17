"""Always-on grounding stays active when optional answer checks are disabled."""

import asyncio
import logging

import pytest

from app.agent.guardrails.checks import FALLBACK
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
