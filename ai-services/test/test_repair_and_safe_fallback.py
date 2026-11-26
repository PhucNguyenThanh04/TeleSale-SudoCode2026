import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from app.agent.guardrails.checks import check_answer, check_grounding
from app.agent.harness.agent_nodes import AgentNodes, SAFE_VERIFICATION_FALLBACK
from app.agent.harness.runtime import AgentHarnessRuntime
from app.schemas.agent import TextTurnRequest
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel
from test_semantic_grounding import ReviewModel, verdict


def make_state(draft: str, *, text: str = "Giá mẫu này bao nhiêu?", reply_context: dict | None = None):
    request = TextTurnRequest(
        client_msg_id=uuid4(),
        session_id=uuid4(),
        channel="hotline",
        channel_identity="0900000011",
        on=date(2032, 4, 10),
        text=text,
        input_mode="clean",
    )
    return {
        "request": request,
        "safe_text": text,
        "identity_status": "unknown",
        "agent_draft": draft,
        "reply_context": reply_context or {},
        "tool_calls": [],
        "session_tool_calls": [],
    }


def test_safe_verification_fallback_passes_all_deterministic_guardrails():
    assert check_grounding(SAFE_VERIFICATION_FALLBACK, []) is None
    assert check_answer(SAFE_VERIFICATION_FALLBACK, [], "Bảo hành thế nào?") == (SAFE_VERIFICATION_FALLBACK, None)
    assert check_answer(SAFE_VERIFICATION_FALLBACK, [], "Giá bao nhiêu?") == (SAFE_VERIFICATION_FALLBACK, None)


def test_second_repair_attempt_succeeds_after_first_repair_rejected():
    replies = [
        AIMessage(content="Mẫu này giá 9.000.000đ ạ."),
        AIMessage(content="Dạ, em chưa có báo giá hiện tại, anh cho em xin tên mẫu để em kiểm tra ạ."),
    ]
    model = ReviewModel([verdict()])
    model.ainvoke = AsyncMock(side_effect=replies)
    nodes = AgentNodes(model, None, None, 6, 6, max_repair_attempts=2, safe_fallback_on_rejection=True)
    result = asyncio.run(nodes.verify_agent(make_state("Mẫu này giá 5.000.000đ ạ.")))
    assert result["reply_error"] is None
    assert result["agent_text"] == replies[1].content
    assert result["verified_answer"] == replies[1].content
    assert model.ainvoke.await_count == 2
    assert [e["reason"] for e in result["verifier_events"]] == ["price_without_quote", "price_without_quote"]


def test_safe_fallback_returned_when_both_repairs_rejected_by_guardrails():
    replies = [
        AIMessage(content="Mẫu này giá 8.000.000đ ạ."),
        AIMessage(content="Mẫu này giá 9.000.000đ ạ."),
    ]
    model = ReviewModel([])
    model.ainvoke = AsyncMock(side_effect=replies)
    nodes = AgentNodes(model, None, None, 6, 6, max_repair_attempts=2, safe_fallback_on_rejection=True)
    result = asyncio.run(nodes.verify_agent(make_state("Mẫu này giá 5.000.000đ ạ.")))
    assert result["reply_error"] is None
    assert result["agent_text"] == SAFE_VERIFICATION_FALLBACK
    assert result["verified_answer"] == SAFE_VERIFICATION_FALLBACK
    assert model.ainvoke.await_count == 2
    assert len(result["verifier_events"]) == 3


@pytest.mark.parametrize("bad_repair", [None, '{"tool_calls":[]}'])
def test_infra_or_empty_or_internal_repair_never_uses_safe_fallback(bad_repair):
    model = ReviewModel([])
    if bad_repair is None:
        model.ainvoke = AsyncMock(side_effect=RuntimeError("provider_down"))
    else:
        model.ainvoke = AsyncMock(return_value=AIMessage(content=bad_repair))
    nodes = AgentNodes(model, None, None, 6, 6, max_repair_attempts=2, safe_fallback_on_rejection=True)
    result = asyncio.run(nodes.verify_agent(make_state("Mẫu này giá 5.000.000đ ạ.")))
    assert result["agent_text"] == ""
    assert result["reply_error"] == "agent_reply_unavailable"
    assert model.ainvoke.await_count == 1


def test_empty_first_repair_retries_second_attempt_and_falls_back_if_still_empty():
    model = ReviewModel([])
    model.ainvoke = AsyncMock(side_effect=[AIMessage(content=""), AIMessage(content="")])
    nodes = AgentNodes(model, None, None, 6, 6, max_repair_attempts=2, safe_fallback_on_rejection=True)
    result = asyncio.run(nodes.verify_agent(make_state("Mẫu này giá 5.000.000đ ạ.")))
    assert result["reply_error"] is None
    assert result["agent_text"] == SAFE_VERIFICATION_FALLBACK
    assert model.ainvoke.await_count == 2


def test_runtime_run_and_stream_survive_double_guardrail_rejection_with_safe_fallback():
    async def run(delivery: str):
        model = FakeToolModel(replies=[
            AIMessage(content="Mẫu này giá 5.000.000đ ạ."),
            AIMessage(content="Mẫu này giá 8.000.000đ ạ."),
            AIMessage(content="Mẫu này giá 9.000.000đ ạ."),
        ])
        runtime = AgentHarnessRuntime(
            model, FakeGateway(), FakeMemory(),
            max_repair_attempts=2, safe_fallback_on_rejection=True,
        )
        req = make_state("")["request"]
        try:
            if delivery == "stream":
                events = [e async for e in runtime.stream(req)]
                assert events[-1]["event"] == "done"
                spoken = "".join(e["text"] for e in events if e["event"] == "delta")
                assert spoken == SAFE_VERIFICATION_FALLBACK
            else:
                resp = await runtime.run(req)
                assert resp.agent_text == SAFE_VERIFICATION_FALLBACK
        finally:
            await runtime.close()

    asyncio.run(run("run"))
    asyncio.run(run("stream"))


def test_build_runtime_enables_two_repairs_and_safe_fallback():
    from app.agent.factory import build_runtime
    from app.configs import Settings

    settings = Settings.model_construct(
        log_level="INFO",
        mcp_catalog_url="http://localhost:8011",
        mcp_order_url="http://localhost:8012",
        mcp_memory_url="http://localhost:8013",
        mcp_knowledge_url="http://localhost:8014",
        mcp_internal_token=SimpleNamespace(get_secret_value=lambda: "tok"),
        memory_max_episodes=5,
        agent_max_tool_calls=6,
        agent_prompt_history_turns=6,
        agent_guardrails_enabled=True,
        agent_turn_timeout_seconds=90,
        langfuse_enabled=False,
    )
    with patch("app.agent.factory.build_llm", return_value=FakeToolModel(replies=[])):
        runtime = build_runtime(settings, gateway=FakeGateway())
    assert runtime.nodes.max_repair_attempts == 1
    assert runtime.nodes.safe_fallback_on_rejection is True
    assert runtime.nodes.semantic_review_enabled is True
    assert runtime.progressive_streaming is False


def test_grounding_review_unavailable_fails_fast_without_safe_fallback():
    model = ReviewModel([RuntimeError("reviewer_timeout"), RuntimeError("reviewer_timeout")],
                        "Dạ, em nghe ạ.")
    nodes = AgentNodes(model, None, None, 6, 6, max_repair_attempts=2, safe_fallback_on_rejection=True)
    result = asyncio.run(nodes.verify_agent(make_state("Dạ, em nghe ạ.")))
    assert result["agent_text"] == ""
    assert result["reply_error"] == "agent_reply_unavailable"
    assert model.ainvoke.await_count == 1


def test_turn_diagnostics_records_recovery_fallback_event_and_status():
    from app.agent.harness.observability import capture_diagnostic_events
    from eval_harness.turn_diagnostics import _classify

    model = ReviewModel([])
    model.ainvoke = AsyncMock(side_effect=[
        AIMessage(content="Mẫu này giá 8.000.000đ ạ."),
        AIMessage(content="Mẫu này giá 9.000.000đ ạ."),
    ])
    nodes = AgentNodes(model, None, None, 6, 6, max_repair_attempts=2, safe_fallback_on_rejection=True)
    with capture_diagnostic_events() as events:
        result = asyncio.run(nodes.verify_agent(make_state("Mẫu này giá 5.000.000đ ạ.")))
    assert result["agent_text"] == SAFE_VERIFICATION_FALLBACK
    assert any(e["step"] == "verify" and e["event"] == "recovery_fallback" for e in events)
    summary = _classify(events, result["verifier_events"])
    assert summary["recovery"] == {"status": "fallback", "attempts": 2}
