import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.agent.factory import build_runtime
from app.agent.harness.agent_nodes import AgentNodes
from app.configs import Settings
from app.schemas.agent import TextTurnRequest


def _turn_state(draft: str) -> dict:
    req = TextTurnRequest(
        session_id=uuid4(),
        client_msg_id=uuid4(),
        channel="hotline",
        channel_identity="0900000001",
        input_mode="clean",
        text="Giá AirPure X bao nhiêu?",
        on=date(2026, 10, 20),
    )
    return {
        "request": req,
        "safe_text": req.text,
        "identity_status": "known",
        "customer_id": "C001",
        "customer_phone": "0900000001",
        "agent_draft": draft,
        "tool_calls": [],
        "session_tool_calls": [],
        "history": [],
        "profile": {},
        "scoped_facts": {"product": {}, "room": {}},
        "episodes": [],
    }


def test_p3_settings_defaults_and_build_runtime_propagation():
    settings = Settings(
        llm_api_key="test-key",
        llm_model="gpt-4o-mini",
        agent_authorizer_enabled=False,
        agent_verify_enabled=False,
        agent_progressive_streaming=False,
        agent_semantic_review_enabled=True,
    )
    assert settings.agent_authorizer_enabled is False
    assert settings.agent_verify_enabled is False
    assert settings.agent_progressive_streaming is False
    assert settings.agent_semantic_review_enabled is True
    with patch("app.agent.factory.build_llm", return_value=SimpleNamespace()):
        runtime = build_runtime(settings, gateway=SimpleNamespace())
    assert runtime.progressive_streaming is False
    assert runtime.nodes.authorizer_enabled is False
    assert runtime.nodes.verify_enabled is False
    assert runtime.nodes.semantic_review_enabled is True


def test_p3_verify_disabled_bypasses_grounding_and_masks_pii():
    nodes = AgentNodes(None, None, None, 6, 6, verify_enabled=False)
    st = _turn_state("Giá AirPure X là 9.999.000đ, gọi 0912345678 nhé.")
    res = asyncio.run(nodes.verify_agent(st))
    assert "9.999.000" in res["agent_text"]
    assert "0912345678" not in res["agent_text"]
    assert res["reply_error"] is None


def test_p3_authorizer_disabled_skips_authorize_write():
    captured = {}

    def fake_build_agent(_kind, _llm, business, _prompt):
        captured["business"] = business
        return SimpleNamespace(ainvoke=AsyncMock(return_value={"messages": []}))

    nodes = AgentNodes(None, SimpleNamespace(), None, 6, 6, authorizer_enabled=False)
    st = _turn_state("")
    with patch("app.agent.harness.agent_nodes.build_agent", side_effect=fake_build_agent), \
         patch("app.agent.harness.agent_nodes.text_prompt", return_value="prompt"), \
         patch("app.agent.harness.authorization.authorize_write", side_effect=AssertionError("should skip")):
        asyncio.run(nodes.run_agent(st))
        allowed = asyncio.run(captured["business"].authorize_write("order.create", {"sku": "SKU-1"}))
    assert allowed is True
