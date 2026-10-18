"""Outer graph nodes shared by the supported agent implementations."""

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.harness.context import prompt_context
from app.agent.implementations import AgentKind, build_agent
from app.agent.implementations.business_agent import BusinessTools
from app.agent.memory.fact_candidates import (
    accepted_candidates, customer_slot_cues, extract_customer_candidates, model_candidates,
    resolved_blockers,
    parse_json_object,
)
from app.agent.memory.reported_facts import reported_tool_candidates
from app.agent.memory.store import memory_error_code
from app.agent.guardrails.checks import FALLBACK, check_answer, check_grounding, mask_pii
from app.agent.guardrails.diagnostics import rejected_draft
from app.agent.harness.session_nodes import SessionNodes, safe_catalog_reply
from app.agent.harness.observability import log_event, trace_node
from app.agent.harness.state import TurnState


MEMORY_UNAVAILABLE = (
    "Dạ, hệ thống đang gián đoạn nên em chưa thể xử lý yêu cầu lúc này. "
    "Anh/chị vui lòng thử lại sau ạ."
)


class AgentNodes(SessionNodes):
    guardrails_enabled = True

    def __init__(self, *args, agent_kind: AgentKind = "deep",
                 fact_extraction_mode: str = "fallback", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.agent_kind = agent_kind
        self.fact_extraction_mode = fact_extraction_mode

    @trace_node("run_agent")
    async def run_agent(self, state: TurnState) -> dict[str, Any]:
        if state.get("tool_failed"):
            return {"agent_draft": MEMORY_UNAVAILABLE, "fact_candidates": []}
        state["tool_calls"] = list(state.get("tool_calls", []))
        business = BusinessTools(self.tools, state, self.max_tool_calls, self.clock)
        agent = build_agent(self.agent_kind, self.llm, business)
        context = prompt_context(state, self.prompt_history_turns)
        messages = []
        try:
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=json.dumps(context, ensure_ascii=False,
                                                               default=str))]},
                config={"recursion_limit": max(12, self.max_tool_calls * 4 + 4)},
            )
            messages = result.get("messages", [])
            finals = [item for item in messages
                      if isinstance(item, AIMessage) and not item.tool_calls
                      and isinstance(item.content, str) and item.content.strip()]
            draft = finals[-1].content if finals else FALLBACK
            if finals:
                final_payload = parse_json_object(draft)
                if final_payload and isinstance(final_payload.get("answer"), str):
                    draft = final_payload["answer"]
            draft = mask_pii(draft)
        except Exception as exc:
            log_event(state, "run_agent", "model_failed", level=logging.WARNING,
                      error_type=type(exc).__name__)
            draft = FALLBACK
        proposals = state.get("model_fact_candidates", []) + model_candidates(messages)
        evidenced = accepted_candidates(state["safe_text"], state.get("tool_calls", []),
                                       proposals)
        covered = {item["key"] for item in evidenced if item["source_kind"] == "customer"}
        needs_extraction = (self.fact_extraction_mode == "always" or
            self.fact_extraction_mode == "fallback" and bool(
                customer_slot_cues(state["safe_text"]) - covered))
        if needs_extraction:
            try:
                proposals.extend(await extract_customer_candidates(self.llm, state["safe_text"]))
            except Exception as exc:
                log_event(state, "run_agent", "fact_extraction_failed",
                          level=logging.WARNING, error_type=type(exc).__name__)
        return {"agent_draft": draft, "fact_candidates": proposals,
                "plan_envelopes": state.get("plan_envelopes", []),
                "tool_calls": state["tool_calls"],
                "tool_count": state.get("tool_count", 0),
                "needs_handoff": state.get("needs_handoff", False),
                "handoff_ticket_id": state.get("handoff_ticket_id")}

    @trace_node("verify")
    async def verify_agent(self, state: TurnState) -> dict[str, Any]:
        draft = state.get("agent_draft", FALLBACK)
        grounding_reason = check_grounding(draft, state.get("tool_calls", []))
        log_event(state, "verify", "grounding_checked", accepted=grounding_reason is None,
                  **({"reason": grounding_reason} if grounding_reason else {}))
        if grounding_reason:
            return {"agent_text": FALLBACK,
                    "verifier_events": [rejected_draft(state, grounding_reason, draft)]}
        if not self.guardrails_enabled:
            log_event(state, "verify", "answer_check_disabled",
                      reason="AGENT_GUARDRAILS_ENABLED=false; kiểm tra bằng chứng vẫn chạy")
            return {"agent_text": mask_pii(draft.strip()) if draft.strip() else FALLBACK}
        answer, reason = check_answer(draft, state.get("tool_calls", []), state["safe_text"])
        log_event(state, "verify", "answer_checked", accepted=reason is None,
                  **({"reason": reason} if reason else {}))
        if reason is None:
            return {"agent_text": answer}
        rejected = [rejected_draft(state, reason, draft)]
        safe = safe_catalog_reply(state)
        if safe:
            checked, safe_reason = check_answer(safe, state.get("tool_calls", []),
                                                state["safe_text"])
            if safe_reason is None:
                return {"agent_text": checked, "verifier_events": rejected}
            rejected.append(rejected_draft(state, safe_reason, safe))
        return {"agent_text": FALLBACK, "verifier_events": rejected}

    @trace_node("persist")
    async def persist_agent(self, state: TurnState) -> dict[str, Any]:
        request = state["request"]
        tool_calls = state.get("tool_calls", [])
        proposals = [*state.get("fact_candidates", []),
                     *reported_tool_candidates(state["agent_text"], tool_calls)]
        facts = accepted_candidates(state["safe_text"], tool_calls,
                                    proposals, state["agent_text"])
        facts = [*resolved_blockers(state["safe_text"], state.get("profile", {}), facts),
                 *facts]
        try:
            result = await self.memory.commit_turn(
                str(request.session_id), state.get("customer_id"), state["safe_text"],
                state["agent_text"], request.on.isoformat(), request.channel,
                str(request.client_msg_id), facts,
                orders=[call["result"]["order_id"] for call in state.get("tool_calls", [])
                        if call.get("name") == "order.create"
                        and call.get("result", {}).get("status") == "created"
                        and isinstance(call.get("result", {}).get("order_id"), str)])
        except Exception as exc:
            log_event(state, "persist", "failed", level=logging.ERROR,
                      operation="commit_turn", error_type=type(exc).__name__)
            raise RuntimeError("memory_turn_write_failed") from exc
        if (not isinstance(result, dict) or type(result.get("turn_no")) is not int
                or result["turn_no"] < 1
                or not isinstance(result.get("memory_writes"), list)):
            log_event(state, "persist", "failed", level=logging.ERROR,
                      operation="commit_turn", reason=memory_error_code(result))
            raise RuntimeError("memory_turn_write_failed")
        log_event(state, "persist", "memory_recorded", turn_no=result["turn_no"],
                  accepted_facts=len(result["memory_writes"]))
        return {"memory_writes": [*state.get("claimed_memory_writes", []),
                                  *result["memory_writes"]]}
