
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
from app.agent.guardrails.checks import (check_answer, check_grounding,
                                         mask_pii)
from app.agent.guardrails.diagnostics import rejected_draft
from app.agent.guardrails.semantic_grounding import review_answer
from app.agent.harness.session_nodes import SessionNodes
from app.agent.harness.observability import log_event, trace_node
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
from app.agent.harness.state import TurnState
from app.agent.harness.policy import transaction_selection_mismatch
from app.agent.harness.streaming import active_stream, active_turn_progress, invoke_agent, internal_output


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


from app.agent.harness.execution_diagnostics import (
    execution_node, set_execution_phase, execution_result,
)


class AgentNodes(SessionNodes):
    guardrails_enabled = True

    @trace_node("run_agent")
    @execution_node("preparation")
    async def run_agent(self, state: TurnState) -> dict[str, Any]:
        progress = active_turn_progress.get()
        if progress is not None:
            progress['state'] = state
        stream = active_stream.get()
        if stream is not None:
            stream.state = state
        if state.get("tool_failed") and not state.get('memory_blocked'):
            execution_result(state, exc=RuntimeError("preparation_failed"))
            return {"agent_draft": "", "reply_context": {"reason": "memory_unavailable"}}
        state["tool_calls"] = list(state.get("tool_calls", []))
        from app.agent.harness.authorization import authorize_write

        async def current_authorization(name, args):
            return await authorize_write(self.llm, state, name, args, self.prompt_history_turns)

        business = BusinessTools(self.tools, state, self.max_tool_calls, self.clock,
                                 authorize_write=current_authorization)
        draft = ""
        reply_context = {}
        try:
            set_execution_phase("build")
            system_prompt = await asyncio.to_thread(text_prompt, SALES_PROMPT, _SYSTEM_PROMPT)
            state['selected_system_prompt'] = system_prompt
            agent = build_agent("deep", self.llm, business, system_prompt)
            context = prompt_context(state, self.prompt_history_turns)
            set_execution_phase("model_invocation", "initial")
            result = await invoke_agent(agent, {"messages": prompt_messages(context)},
                config={"recursion_limit": max(12, self.max_tool_calls * 4 + 4)}, state=state)
            execution_result(state)
            set_execution_phase("postprocess")
            messages = result.get("messages", [])
            last_customer = max((i for i, message in enumerate(messages)
                                 if isinstance(message, HumanMessage)), default=-1)
            finals = [message for message in messages[last_customer + 1:]
                      if isinstance(message, AIMessage) and not message.tool_calls]
            if finals:
                draft = _answer_text(finals[-1])
            if not draft:
                reply_context = {"reason": "model_reply_missing"}
        except Exception as exc:
            reply_context = {"reason": "model_unavailable"}
            execution_result(state, exc=exc)
            log_event(state, "run_agent", "model_failed", level=logging.WARNING,
                      error_type=type(exc).__name__)
            set_execution_phase("postprocess")
        return {"agent_draft": mask_pii(draft), "reply_context": reply_context,
                'selected_system_prompt': state.get('selected_system_prompt', _SYSTEM_PROMPT),
                "tool_calls": state["tool_calls"],
                "tool_count": state.get("tool_count", 0),
                'tool_attempts': state.get('tool_attempts', 0),
                "policy_order_bindings": state.get("policy_order_bindings", {}),
                "needs_handoff": state.get("needs_handoff", False),
                "handoff_ticket_id": state.get("handoff_ticket_id")}

    @trace_node("verify")
    @execution_node("verification")
    async def verify_agent(self, state: TurnState) -> dict[str, Any]:
        progress = active_turn_progress.get()
        if progress is not None:
            progress['state'] = state
        draft = state.get("agent_draft", "")
        model_state = state
        if state.get('tool_failed'):
            model_state = {**state, 'history': [], 'customer_statements': [], 'profile': {},
                'scoped_facts': {'product': {}, 'room': {}}, 'episodes': [],
                'current_episode': None, 'call_brief': None, 'session_tool_calls': []}
        calls = build_commerce_evidence(model_state)

        async def validate(answer):
            answer = mask_pii(answer.strip())
            if not answer.strip():
                return '', 'empty_answer'
            if internal_output(answer):
                return '', 'internal_output'
            if (transaction_selection_mismatch(model_state)
                    and re.search(r'đã\s+(?:lên|tạo|đặt|chốt)\s+đơn', answer, re.I)):
                return '', 'order_selection_mismatch'
            reason = check_grounding(answer, calls)
            if not self.guardrails_enabled:
                log_event(state, 'verify', 'answer_check_disabled', reason='configured_disabled')
            if reason is None and self.guardrails_enabled:
                answer, reason = check_answer(answer, calls, state["safe_text"], focus_sku=_claim_focus(model_state))
            if reason is None:
                reason = await review_answer(self.llm, answer,
                    prompt_context(model_state, self.prompt_history_turns))
            log_event(state, 'verify', 'grounding_checked', accepted=reason is None, reason=reason)
            return answer, reason

        answer, reason = await validate(draft)
        if reason is None:
            return {"agent_text": answer, 'verified_answer': answer, 'reply_error': None}
        rejected = [rejected_draft(state, reason, draft)] if draft else []
        try:
            import json
            from langchain_core.messages import SystemMessage
            context = prompt_context(model_state, self.prompt_history_turns)
            messages = [SystemMessage(content=state.get('selected_system_prompt', _SYSTEM_PROMPT)),
                        *prompt_messages(context)]
            if draft:
                messages.append(AIMessage(content=mask_pii(draft)))
            price_instruction = (' Đối chiếu từng số tiền với báo giá của đúng sản phẩm hoặc giỏ hàng. '
                'Với pricing.get_quote, báo giá bán theo final_price_vnd, viết đủ số tiền bằng chữ số '
                'kèm đơn vị đồng, không làm tròn. Bỏ số tiền của các khoản phí, mức giảm hoặc giá trị '
                'quà tặng chưa được xác minh.') if reason == 'price_without_quote' else ''
            messages.append(HumanMessage(content=json.dumps({
                'task': ('Viết câu trả lời cho yêu cầu hiện tại, chỉ dùng bằng chứng đã có. '
                    'Ưu tiên thông báo đúng trạng thái thao tác đã được công cụ xác nhận. '
                    'Không thực hiện thêm thao tác. Khi memory không khả dụng, không suy đoán '
                    'lịch sử riêng của khách. Yêu cầu xóa toàn bộ dữ liệu cần xác minh/chuyển '
                    'bộ phận phụ trách, chưa được coi là đã xóa. Không đọc mã lỗi nội bộ cho khách. '
                    'Nếu thiếu dữ kiện, hỏi làm rõ hoặc nói rõ phần chưa xác minh. '
                    'Không thay bằng báo giá/sản phẩm của chủ đề khác.' + price_instruction),
                'validation_error': reason,
                'runtime_status': state.get('reply_context', {}),
            }, ensure_ascii=False)))
            log_event(state, 'verify', 'recovery_attempted', level=logging.DEBUG, reason=reason)
            set_execution_phase('model_invocation', 'repair')
            repair = await self.llm.ainvoke(messages)
            execution_result(state)
            set_execution_phase('verification')
            repaired = mask_pii(_answer_text(repair))
            checked, repair_reason = await validate(repaired)
            if repair_reason is None:
                log_event(state, 'verify', 'recovery_succeeded', level=logging.DEBUG)
                return {"agent_text": checked, 'verified_answer': checked,
                        'reply_error': None, "verifier_events": rejected}
            log_event(state, 'verify', 'recovery_rejected', level=logging.DEBUG, reason=repair_reason)
            rejected.append(rejected_draft(state, repair_reason, repaired))
        except Exception as exc:
            execution_result(state, exc=exc)
            log_event(state, "verify", "repair_failed", level=logging.WARNING,
                      error_type=type(exc).__name__)
        log_event(state, 'verify', 'recovery_exhausted', level=logging.DEBUG)
        return {"agent_text": '', 'verified_answer': '', 'reply_error': 'agent_reply_unavailable',
                "verifier_events": rejected}

    @trace_node("persist")
    async def persist_agent(self, state: TurnState) -> dict[str, Any]:
        if state.get("memory_blocked"):
            return {"memory_writes": []}
        request = state["request"]
        if not state.get('reply_error'):
            diagnostic_emit("final_verified", state=state, status="success")
        tool_calls = [*state.get('prepared_tool_calls', []), *state.get("tool_calls", [])]
        knowledge_kwargs = {}
        if getattr(self.memory, 'supports_durable_replay', False) is True:
            from app.agent.harness.session_identity import turn_fingerprint
            knowledge_kwargs['request_hash'] = turn_fingerprint(request, getattr(self.memory, 'include_prior', True))
        if (getattr(self.memory, 'supports_private_delivery', False) is True
                and state.get('private_delivery')
                and state['private_delivery'].get('source_turn_id') == str(request.client_msg_id)):
            knowledge_kwargs['private_delivery'] = state['private_delivery']
        from app.knowledge.config import enabled
        if enabled() and getattr(self.memory, 'supports_knowledge_signals', False):
            from app.knowledge.events.evidence import safe_tools
            policy_calls = [c for c in tool_calls if c.get('name') == 'policy.search']
            signal = ('guardrail_rejection' if state.get('verifier_events') else
                      'fallback' if state.get('reply_error') else None)
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
