"""Outer graph nodes shared by the supported agent implementations."""

import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.harness.context import prompt_context
from app.agent.implementations import AgentKind, build_agent
from app.agent.implementations.business_agent import BusinessTools
from app.agent.memory.fact_candidates import (
    accepted_candidates, customer_slot_cues, extract_customer_candidates, model_candidates,
    literal_blocker_candidates, resolved_blockers,
    parse_json_object,
)
from app.agent.memory.reported_facts import reported_tool_candidates
from app.agent.memory.episode_candidates import (
    accepted_episode_delta, blocker_episode_delta, outcome_from_tool_calls,
)
from app.agent.memory.store import memory_error_code
from app.agent.guardrails.checks import (FALLBACK, check_answer, check_grounding,
                                         customer_erasure_requested, mask_pii)
from app.agent.guardrails.diagnostics import rejected_draft
from app.agent.harness.session_nodes import SessionNodes, safe_catalog_reply
from app.agent.harness.observability import log_event, trace_node
from app.agent.harness.state import TurnState
from app.agent.harness.policy import prepare_tool_call
from app.agent.harness.observability import log_tool_input, log_tool_output
from app.agent.harness.state import Decision
from app.schemas.brief import HandoffBrief


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
        if state.get("memory_blocked") and customer_erasure_requested(state["safe_text"]):
            state["tool_calls"] = list(state.get("tool_calls", []))
            return await self._route_customer_erasure(state)
        if state.get("tool_failed"):
            return {"agent_draft": MEMORY_UNAVAILABLE, "fact_candidates": []}
        state["tool_calls"] = list(state.get("tool_calls", []))
        if customer_erasure_requested(state["safe_text"]):
            return await self._route_customer_erasure(state)
        business = BusinessTools(self.tools, state, self.max_tool_calls, self.clock)
        agent = build_agent(self.agent_kind, self.llm, business)
        context = prompt_context(state, self.prompt_history_turns)
        messages = []
        episode_proposal = None
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
                    episode_proposal = final_payload.get("episode_delta")
            draft = mask_pii(draft)
        except Exception as exc:
            log_event(state, "run_agent", "model_failed", level=logging.WARNING,
                      error_type=type(exc).__name__)
            draft = FALLBACK
        handoffs = [call for call in state.get("tool_calls", [])
                    if call.get("name") == "handoff.transfer"]
        if handoffs and not any(
                isinstance(call.get("result"), dict)
                and call["result"].get("status") == "queued"
                and isinstance(call["result"].get("ticket_id"), str)
                and bool(call["result"]["ticket_id"]) for call in handoffs):
            draft = ("Dạ, hiện em chưa chuyển được yêu cầu. Anh/chị vui lòng "
                     "liên hệ tổng đài để được hỗ trợ ạ.")
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
                "episode_proposal": episode_proposal,
                "handoff_episode_delta": state.get("handoff_episode_delta"),
                "plan_envelopes": state.get("plan_envelopes", []),
                "tool_calls": state["tool_calls"],
                "tool_count": state.get("tool_count", 0),
                "needs_handoff": state.get("needs_handoff", False),
                "handoff_ticket_id": state.get("handoff_ticket_id")}

    async def _route_customer_erasure(self, state: TurnState) -> dict[str, Any]:
        """Escalate a whole-record request without presenting it as a completed purge."""
        request = state["request"]
        phone = state.get("customer_phone") or (
            request.channel_identity if request.channel == "hotline" else None)
        if not isinstance(phone, str) or not re.fullmatch(r"0[0-9]{9}", phone):
            draft = ("Dạ, để xử lý yêu cầu về dữ liệu cá nhân, anh/chị vui lòng "
                     "liên hệ tổng đài để xác minh chủ thể. Em chưa xóa dữ liệu ạ.")
            return {"agent_draft": draft, "fact_candidates": [],
                    "tool_calls": state["tool_calls"], "tool_count": state.get("tool_count", 0)}
        brief = HandoffBrief(
            customer_phone=phone, customer_name=state.get("customer_name"),
            customer_id=state.get("customer_id"), channel=request.channel,
            escalation_reason="khac",
            escalation_reason_detail="Khách yêu cầu xử lý dữ liệu cá nhân.",
            conversation_summary=("Khách yêu cầu xử lý dữ liệu cá nhân đã lưu. "
                                  "Chưa có thao tác xóa; cần xác minh chủ thể và phạm vi."),
            product_advised=None, price_quoted_vnd=None,
            open_questions=["Xác minh chủ thể và phạm vi dữ liệu cần xử lý."],
            next_action="Xác minh chủ thể và chuyển yêu cầu cho bộ phận có thẩm quyền.",
            generated_at=self.clock(),
        ).model_dump(mode="json")
        state["decision"] = Decision(action="tool", tool_name="handoff.transfer",
                                     tool_args={"brief": brief})
        prepared = prepare_tool_call(state, self.clock)
        if prepared is None:
            result = {"error": "precondition_or_arguments"}
            args = {"brief": brief}
        else:
            _, args = prepared
            log_tool_input("run_agent", "handoff.transfer", args)
            operation_key = (f"{request.session_id}:{request.client_msg_id}:"
                             "handoff.transfer:1")
            try:
                if hasattr(self.tools, "invoke_trusted"):
                    result = await self.tools.invoke_trusted(
                        "handoff.transfer", args, state.get("customer_id"),
                        request.channel, request.channel_identity, operation_key)
                else:
                    result = await self.tools.invoke("handoff.transfer", args)
            except Exception:
                result = {"error": "tool_error"}
            if not isinstance(result, dict):
                result = {"error": "invalid_tool_result"}
            log_tool_output(state, "run_agent", "handoff.transfer", result)
        state["tool_calls"].append({"name": "handoff.transfer", "args": args,
                                    "result": result})
        state["tool_count"] = state.get("tool_count", 0) + 1
        ticket = result.get("ticket_id") if "error" not in result else None
        queued = (isinstance(ticket, str) and bool(ticket)
                  and result.get("status") == "queued")
        draft = (("Dạ, em đã chuyển yêu cầu đến bộ phận phụ trách để xác minh "
                  "và xử lý. Dữ liệu chưa được xóa ở bước này ạ.") if queued else
                 ("Dạ, hiện em chưa chuyển được yêu cầu. Anh/chị vui lòng "
                  "liên hệ tổng đài để xác minh và xử lý dữ liệu ạ."))
        return {"agent_draft": draft, "fact_candidates": [],
                "tool_calls": state["tool_calls"], "tool_count": state["tool_count"],
                "needs_handoff": queued, "handoff_ticket_id": ticket if queued else None}

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
        if state.get("memory_blocked"):
            return {"memory_writes": []}
        request = state["request"]
        tool_calls = state.get("tool_calls", [])
        proposals = [*state.get("fact_candidates", []),
                     *reported_tool_candidates(state["agent_text"], tool_calls)]
        literal_blockers = literal_blocker_candidates(state["safe_text"])
        if literal_blockers:
            proposals = [item for item in proposals if item.get("key") != "blocker"]
            proposals.extend(literal_blockers)
        facts = accepted_candidates(state["safe_text"], tool_calls,
                                    proposals, state["agent_text"])
        facts = [*resolved_blockers(state["safe_text"], state.get("profile", {}), facts),
                 *facts]
        episode_delta = accepted_episode_delta(
            state["safe_text"], state["agent_text"], state.get("episode_proposal"),
            state.get("current_episode") or {}, tool_calls,
            prior_episodes=state.get("episodes", []))
        fact_episode_delta = blocker_episode_delta(
            state["safe_text"], facts, state.get("current_episode") or {}, episode_delta)
        if fact_episode_delta:
            episode_delta = {"topic_updates": [
                *episode_delta.get("topic_updates", []),
                *fact_episode_delta["topic_updates"]][:8]}
        handoff_delta = state.get("handoff_episode_delta") or {}
        if handoff_delta.get("topic_updates"):
            updates = [*handoff_delta["topic_updates"],
                       *episode_delta.get("topic_updates", [])]
            episode_delta = {"topic_updates": updates[:8]}
        other_objections = sum(fact["key"] == "objection" and fact.get("value") == "khac"
                               for fact in facts)
        if other_objections:
            log_event(state, "persist", "open_objection_other", count=other_objections)
        outcome = outcome_from_tool_calls(tool_calls)
        try:
            result = await self.memory.commit_turn(
                str(request.session_id), state.get("customer_id"), state["safe_text"],
                state["agent_text"], request.on.isoformat(), request.channel,
                str(request.client_msg_id), facts,
                **({"tool_observations": tool_calls}
                   if getattr(self.memory, "supports_tool_observations", False) else {}),
                orders=[call["result"]["order_id"] for call in state.get("tool_calls", [])
                        if call.get("name") == "order.create"
                        and call.get("result", {}).get("status") == "created"
                        and isinstance(call.get("result", {}).get("order_id"), str)],
                **({"episode_delta": episode_delta} if episode_delta else {}),
                **({"outcome": outcome} if outcome != "khac" else {}))
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
                  accepted_facts=len(result["memory_writes"]),
                  **({"episode_warning": result["episode_warning"]}
                     if result.get("episode_warning") else {}))
        return {"memory_writes": result["memory_writes"]}
