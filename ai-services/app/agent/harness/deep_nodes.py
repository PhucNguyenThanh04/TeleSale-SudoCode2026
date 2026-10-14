"""Outer graph nodes around the prebuilt Deep Agent loop."""

import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.harness.context import prompt_context
from app.agent.implementations.deep_agent import BusinessTools, build_deep_agent
from app.agent.memory.fact_candidates import (
    accepted_candidates, extract_customer_candidates, model_candidates,
    parse_json_object,
)
from app.agent.guardrails.checks import FALLBACK, check_answer, mask_pii
from app.agent.harness.session_nodes import SessionNodes, safe_catalog_reply
from app.agent.harness.observability import log_event, trace_node
from app.agent.harness.state import TurnState


class DeepAgentNodes(SessionNodes):
    guardrails_enabled = True

    @trace_node("run_deep_agent")
    async def run_deep_agent(self, state: TurnState) -> dict[str, Any]:
        if state.get("tool_failed"):
            return {"agent_draft": FALLBACK, "fact_candidates": []}
        state["tool_calls"] = list(state.get("tool_calls", []))
        business = BusinessTools(self.tools, state, self.max_tool_calls, self.clock)
        agent = build_deep_agent(self.llm, business)
        context = prompt_context(state, self.prompt_history_turns)
        messages = []
        extraction_task = (asyncio.create_task(
            extract_customer_candidates(self.llm, state["safe_text"]))
            if state.get("identity_status") == "known" else None)
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
            log_event(state, "run_deep_agent", "model_failed", level=logging.WARNING,
                      error_type=type(exc).__name__)
            draft = FALLBACK
        proposals = state.get("model_fact_candidates", []) + model_candidates(messages)
        if extraction_task:
            try:
                proposals.extend(await extraction_task)
            except Exception as exc:
                log_event(state, "run_deep_agent", "fact_extraction_failed",
                          level=logging.WARNING, error_type=type(exc).__name__)
        return {"agent_draft": draft, "fact_candidates": proposals,
                "plan_envelopes": state.get("plan_envelopes", []),
                "tool_calls": state["tool_calls"],
                "tool_count": state.get("tool_count", 0),
                "needs_handoff": state.get("needs_handoff", False),
                "handoff_ticket_id": state.get("handoff_ticket_id")}

    @trace_node("verify")
    async def verify_deep(self, state: TurnState) -> dict[str, Any]:
        draft = state.get("agent_draft", FALLBACK)
        if not self.guardrails_enabled:
            log_event(state, "verify", "answer_check_disabled")
            return {"agent_text": mask_pii(draft.strip()) if draft.strip() else FALLBACK}
        answer, reason = check_answer(draft, state.get("tool_calls", []), state["safe_text"])
        log_event(state, "verify", "answer_checked", accepted=reason is None,
                  **({"reason": reason} if reason else {}))
        if reason is None:
            return {"agent_text": answer}
        safe = safe_catalog_reply(state)
        if safe:
            checked, safe_reason = check_answer(safe, state.get("tool_calls", []),
                                                state["safe_text"])
            if safe_reason is None:
                return {"agent_text": checked}
        return {"agent_text": FALLBACK}

    @trace_node("persist")
    async def persist_deep(self, state: TurnState) -> dict[str, Any]:
        request = state["request"]
        facts = (accepted_candidates(state["safe_text"], state.get("tool_calls", []),
                                     state.get("fact_candidates", []))
                 if state.get("identity_status") == "known" and state.get("customer_id") else [])
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
                      error_type=type(exc).__name__)
            raise RuntimeError("memory_turn_write_failed") from exc
        if (not isinstance(result, dict) or type(result.get("turn_no")) is not int
                or result["turn_no"] < 1
                or not isinstance(result.get("memory_writes"), list)):
            raise RuntimeError("memory_turn_write_failed")
        log_event(state, "persist", "memory_recorded", turn_no=result["turn_no"],
                  accepted_facts=len(result["memory_writes"]))
        return {"memory_writes": result["memory_writes"]}
