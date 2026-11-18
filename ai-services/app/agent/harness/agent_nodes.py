"""Outer graph nodes shared by the supported agent implementations."""

from app.mcp_servers.mcp_shared.decision_diagnostics import emit as diagnostic_emit


import logging
import time
import re
import asyncio
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.harness.context import prompt_context, prompt_messages
from app.agent.implementations import build_agent
from app.agent.implementations.business_agent import BusinessTools
from app.agent.prompts import SALES_PROMPT, text_prompt
from app.agent.implementations.business_agent import _SYSTEM_PROMPT
from app.agent.memory.episode_candidates import outcome_from_tool_calls
from app.agent.memory.store import memory_error_code
from app.agent.guardrails.checks import (FALLBACK, check_answer, check_grounding,
                                         customer_erasure_requested, mask_pii)
from app.agent.guardrails.diagnostics import rejected_draft
from app.agent.harness.session_nodes import (SessionNodes, safe_transaction_reply,
                                            transaction_selection_mismatch)
from app.agent.harness.observability import log_event, trace_node
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
from app.agent.harness.state import TurnState
from app.agent.harness.policy import prepare_tool_call
from app.agent.harness.observability import log_tool_input, log_tool_output
from app.agent.harness.state import Decision
from app.schemas.brief import HandoffBrief
from app.agent.harness.streaming import active_stream, invoke_agent


MEMORY_UNAVAILABLE = (
    "Dạ, hệ thống đang gián đoạn nên em chưa thể xử lý yêu cầu lúc này. "
    "Anh/chị vui lòng thử lại sau ạ."
)


def _answer_text(message) -> str:
    if not isinstance(message, AIMessage) or message.tool_calls:
        return ""
    if isinstance(message.content, str):
        return message.content.strip()
    return "".join(block.get("text", "") for block in message.content
                   if isinstance(block, dict) and block.get("type") == "text").strip()


def _claim_focus(state):
    from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
    named = resolve_claim_skus(state.get('safe_text', ''), build_commerce_evidence(state))
    return next(iter(named)) if len(named) == 1 else None


def _task_answer_complete(draft, state):
    """Publication eligibility from evidence, not a scripted conversation state."""
    calls = build_commerce_evidence(state)
    return bool(draft.strip() and draft != FALLBACK
        and check_grounding(draft, calls) is None
        and check_answer(draft, calls, state['safe_text'], focus_sku=_claim_focus(state))[1] is None)


from app.agent.harness.execution_diagnostics import (
    execution_node, set_execution_phase, execution_result,
)


class AgentNodes(SessionNodes):
    guardrails_enabled = True

    @trace_node("run_agent")
    @execution_node("preparation")
    async def run_agent(self, state: TurnState) -> dict[str, Any]:
        stream = active_stream.get()
        if stream is not None:
            stream.state = state
        if state.get("memory_blocked") and customer_erasure_requested(state["safe_text"]):
            state["tool_calls"] = list(state.get("tool_calls", []))
            return await self._route_customer_erasure(state)
        if state.get("tool_failed"):
            execution_result(state, exc=RuntimeError("preparation_failed"))
            return {"agent_draft": MEMORY_UNAVAILABLE}
        state["tool_calls"] = list(state.get("tool_calls", []))
        if customer_erasure_requested(state["safe_text"]):
            return await self._route_customer_erasure(state)
        from app.agent.harness.authorization import authorize_write

        async def current_authorization(name, args):
            return await authorize_write(self.llm, state, name, args, self.prompt_history_turns)

        business = BusinessTools(self.tools, state, self.max_tool_calls, self.clock,
                                 authorize_write=current_authorization)
        draft = FALLBACK
        try:
            set_execution_phase("build")
            system_prompt = await asyncio.to_thread(text_prompt, SALES_PROMPT, _SYSTEM_PROMPT)
            agent = build_agent("deep", self.llm, business, system_prompt)
            context = prompt_context(state, self.prompt_history_turns)
            set_execution_phase("model_invocation", "initial")
            result = await invoke_agent(agent, {"messages": prompt_messages(context)},
                config={"recursion_limit": max(12, self.max_tool_calls * 4 + 4)}, state=state)
            execution_result(state)
            messages = result.get("messages", [])
            last_customer = max((i for i, message in enumerate(messages)
                                 if isinstance(message, HumanMessage)), default=-1)
            finals = [message for message in messages[last_customer + 1:]
                      if isinstance(message, AIMessage) and not message.tool_calls]
            if finals:
                draft = _answer_text(finals[-1]) or FALLBACK
        except Exception as exc:
            execution_result(state, exc=exc)
            log_event(state, "run_agent", "model_failed", level=logging.WARNING,
                      error_type=type(exc).__name__)
        set_execution_phase("postprocess")
        return {"agent_draft": mask_pii(draft), "tool_calls": state["tool_calls"],
                "tool_count": state.get("tool_count", 0),
                "policy_order_bindings": state.get("policy_order_bindings", {}),
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
            return {"agent_draft": draft,
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
        return {"agent_draft": draft,
                "tool_calls": state["tool_calls"], "tool_count": state["tool_count"],
                "needs_handoff": queued, "handoff_ticket_id": ticket if queued else None}

    @trace_node("verify")
    @execution_node("verification")
    async def verify_agent(self, state: TurnState) -> dict[str, Any]:
        draft = state.get("agent_draft", FALLBACK)
        calls = build_commerce_evidence(state)

        def validate(answer):
            if (transaction_selection_mismatch(state)
                    and re.search(r'đã\s+(?:lên|tạo|đặt|chốt)\s+đơn', answer, re.I)):
                return FALLBACK, 'order_selection_mismatch'
            reason = check_grounding(answer, calls)
            if reason is None and self.guardrails_enabled:
                return check_answer(answer, calls, state["safe_text"], focus_sku=_claim_focus(state))
            return answer, reason

        if draft == FALLBACK:
            receipt = safe_transaction_reply(state)
            if receipt:
                checked, reason = validate(receipt)
                if reason is None:
                    return {'agent_text': mask_pii(checked)}
        answer, reason = validate(draft)
        if reason is None:
            return {"agent_text": mask_pii(answer.strip()) if answer.strip() else FALLBACK}
        rejected = [rejected_draft(state, reason, draft)]
        # A completed write must remain visible even if model generation failed.
        receipt = safe_transaction_reply(state)
        if receipt:
            checked, receipt_reason = validate(receipt)
            if receipt_reason is None:
                return {"agent_text": mask_pii(checked), "verifier_events": rejected}
        try:
            from langchain_core.messages import SystemMessage
            context = prompt_context(state, self.prompt_history_turns)
            repair = await self.llm.ainvoke([
                SystemMessage(content=_SYSTEM_PROMPT),
                *prompt_messages(context), AIMessage(content=mask_pii(draft)),
                HumanMessage(content=("Câu trả lời vừa rồi không qua kiểm tra bằng chứng: " + reason
                    + ". Viết lại câu trả lời cho đúng yêu cầu hiện tại, chỉ dùng bằng chứng đã có. "
                    "Không thực hiện hay tuyên bố thêm thao tác. Nếu thiếu dữ kiện, hỏi làm rõ hoặc "
                    "nói rõ phần chưa xác minh. Không thay bằng báo giá/sản phẩm của chủ đề khác.")),
            ])
            repaired = mask_pii(_answer_text(repair))
            checked, repair_reason = validate(repaired)
            if repair_reason is None:
                return {"agent_text": checked, "verifier_events": rejected}
            rejected.append(rejected_draft(state, repair_reason, repaired))
        except Exception as exc:
            log_event(state, "verify", "repair_failed", level=logging.WARNING,
                      error_type=type(exc).__name__)
        return {"agent_text": FALLBACK, "verifier_events": rejected}

    @trace_node("persist")
    async def persist_agent(self, state: TurnState) -> dict[str, Any]:
        if state.get("memory_blocked"):
            return {"memory_writes": []}
        request = state["request"]
        diagnostic_emit("final_verified", state=state, status="success")
        tool_calls = [*state.get('prepared_tool_calls', []), *state.get("tool_calls", [])]
        knowledge_kwargs = {}
        from app.knowledge.config import enabled
        if enabled() and getattr(self.memory, 'supports_knowledge_signals', False):
            from app.knowledge.events.evidence import safe_tools
            policy_calls = [c for c in tool_calls if c.get('name') == 'policy.search']
            signal = ('guardrail_rejection' if state.get('verifier_events') else
                      'fallback' if state.get('agent_text') == FALLBACK else None)
            for call in policy_calls:
                status = call.get('result', {}).get('retrieval_status')
                if status == 'no_evidence':
                    signal = status
                elif status in {'unavailable', 'timeout', 'overloaded'}:
                    signal = 'mcp_unavailable'
            knowledge_kwargs['knowledge_evidence'] = {
                'signal': signal, 'tool_calls': safe_tools(tool_calls),
                'retrieved_ids': [chunk['chunk_id'] for c in policy_calls
                    for chunk in c.get('result', {}).get('evidence', []) if 'chunk_id' in chunk]}
        commit_started = time.perf_counter()
        try:
            result = await self.memory.commit_turn(
                str(request.session_id), state.get("customer_id"),
                state["safe_text"], state["agent_text"], request.on.isoformat(),
                request.channel, str(request.client_msg_id),
                tool_observations=tool_calls,
                **knowledge_kwargs,
                outcome=outcome_from_tool_calls(tool_calls),
                orders=[call["result"]["order_id"] for call in tool_calls
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
        diagnostic_emit("final_commit", state=state, status="success", turn_count=result["turn_no"])
        log_event(state, "persist", "memory_recorded", turn_no=result["turn_no"],
                  accepted_facts=0)
        return {"memory_writes": result["memory_writes"],
                'memory_commit_ms': (time.perf_counter() - commit_started) * 1000}
