"""Outer graph nodes shared by the supported agent implementations."""

from app.mcp_servers.mcp_shared.decision_diagnostics import emit as diagnostic_emit, active as diagnostic_active


import logging
import time
import json
import re
from app.mcp_servers.mcp_shared.commerce_rules import _search_text
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
from app.agent.harness.session_nodes import (SessionNodes, safe_catalog_reply, safe_consultation_reply, safe_product_reply, product_question_fields, safe_order_status_reply,
                                             safe_promotion_reply, safe_transaction_reply, safe_quote_reply, safe_followup_reply,
                                             transaction_selection_mismatch)
from app.agent.harness.observability import log_event, trace_node
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
from app.agent.harness.state import TurnState
from app.mcp_servers.mcp_shared.consultation_followup import followup_task, followup_answer_complete
from app.agent.harness.policy import prepare_tool_call
from app.agent.harness.observability import log_tool_input, log_tool_output
from app.agent.harness.state import Decision
from app.schemas.brief import HandoffBrief
from app.agent.harness.streaming import active_stream, invoke_agent


POLICY_UNAVAILABLE = "Tạm thời chưa tra cứu được thông tin, vui lòng thử lại sau."


MEMORY_UNAVAILABLE = (
    "Dạ, hệ thống đang gián đoạn nên em chưa thể xử lý yêu cầu lúc này. "
    "Anh/chị vui lòng thử lại sau ạ."
)


def _parse_json_object(content: str) -> dict[str, Any] | None:
    body = content.strip()
    if body.startswith("```") and body.endswith("```"):
        lines = body.splitlines()
        if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"}:
            body = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _claim_focus(state):
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    from app.agent.harness.policy import resolve_product_selection
    focus = derive_consultation(state).focus_sku
    selection = resolve_product_selection(state, {'sku': focus}) if focus else None
    return selection.sku if selection and selection.status == 'resolved' else focus


def _task_answer_complete(draft, state):
    from app.agent.guardrails.checks import _money_claims
    calls = build_commerce_evidence(state)
    if (draft == FALLBACK or check_grounding(draft, calls) is not None
            or check_answer(draft, calls, state['safe_text'], focus_sku=_claim_focus(state))[1] is not None):
        return False
    task = followup_task(state)
    if task.kind != 'none' and not followup_answer_complete(state, task, draft):
        return False
    from app.mcp_servers.mcp_shared.consultation_followup import product_price_requested
    requested = _search_text(state['safe_text'])
    if re.search(r'ma van don|tracking', requested) and not re.search(r'ma van don|tracking', _search_text(draft)):
        return False
    if re.search(r'don vi (?:giao hang|van chuyen)', requested) and not re.search(
            r'don vi (?:giao hang|van chuyen)', _search_text(draft)):
        return False
    if (task.kind == 'policy' and not product_price_requested(state['safe_text'])
            and not product_question_fields(state['safe_text'])):
        return True  # Policy fees/durations are not product-price advice.
    folded = _search_text(state['safe_text'])
    from app.mcp_servers.mcp_shared.basket import current_basket_quote, basket_money_evidenced
    if (current_basket_quote(state) is not None and re.search(r'tong (?:gia|tien)|gio hang', folded)
            and (not re.search(r'\btong\b', _search_text(draft)) or not basket_money_evidenced(draft, calls))):
        return False
    from app.mcp_servers.mcp_shared.consultation_followup import order_status_requested
    if order_status_requested(state['safe_text']) and not re.search(
            r'trang thai|dang giao|van chuyen|da giao|da tao|da huy|huy don|chua (?:tim )?thay', _search_text(draft)):
        return False
    requested_fields = product_question_fields(state['safe_text'])
    if any(not re.search(pattern, _search_text(draft)) for pattern in requested_fields.values()):
        return False
    from app.mcp_servers.mcp_shared.consultation import _mentions, catalog_items
    requested_products = _mentions(state['safe_text'], catalog_items(state))
    if (len(requested_products) > 1 and (product_price_requested(state['safe_text']) or 'stock' in requested_fields)
            and not requested_products <= _mentions(draft, catalog_items(state))):
        return False
    if 'tds' in requested_fields and 'chưa có thông tin' not in draft.lower():
        sourced_reply = safe_product_reply(state)
        if sourced_reply and 'chưa có thông tin' in sourced_reply.lower():
            return False
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    decision = derive_consultation(state)
    budget = decision.snapshot.budget.limit_vnd
    from app.mcp_servers.mcp_shared.consultation_shortlist import (
        build_shortlist, consultation_active, consultation_scope, prefers_child_safety,
    )
    if (not decision.purchase_intent and consultation_active(state)
            and any(kind == 'price' for _, kind, _ in _money_claims(draft))):
        from app.mcp_servers.mcp_shared.consultation import _mentions, catalog_items
        scope = consultation_scope(state)
        if scope.get('known'):
            shortlist = build_shortlist(state, scope=scope, quoted_only=True)
            if ('budget_basis' in shortlist.missing_fields and not re.search(
                    r'moi.{0,50}tong|tong.{0,50}moi', _search_text(draft))):
                return False
            named = _mentions(draft, catalog_items(state))
            allowed = {item['sku'] for item in shortlist.items}
            allowed.update(_mentions(state['safe_text'], catalog_items(state)))
            if named and not named <= allowed:
                return False
            child_safe = {item['sku'] for item in shortlist.items
                          if item.get('attributes', {}).get('child_safe_lock') is True}
            if named and prefers_child_safety(state) and child_safe and not named & child_safe:
                return False
    needs_price = bool(product_price_requested(state['safe_text']) or 'bao nhieu' in folded and not requested_fields
                       or budget is not None and re.search(r'tu van|goi y|phu hop|ngan sach', folded))
    needs_promo = bool(re.search(r'khuyen mai|uu dai|giam|tang|qua', folded))
    return ((not needs_price or any(kind == 'price' for _, kind, _ in _money_claims(draft)))
            and (not needs_promo or bool(re.search(r'khuyen mai|uu dai|giam|tang|qua|cod', _search_text(draft)))))


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
        business = BusinessTools(self.tools, state, self.max_tool_calls, self.clock)
        from app.agent.harness.callback_request import callback_request
        callback_at = callback_request(state['safe_text'], state['request'].on)
        if callback_at and state.get('identity_status') == 'known':
            receipt = await business.invoke('schedule.callback', {'callback_at': callback_at})
            scheduled = receipt.get('callback_id') and receipt.get('callback_at')
            answer = (f"Em đã đặt lịch gọi lại cho mình vào {receipt['callback_at']}."
                      if scheduled else 'Em chưa đặt được lịch gọi lại. Mình vui lòng thử lại sau ạ.')
            return {'agent_draft': answer, 'tool_calls': state['tool_calls'],
                    'tool_count': state.get('tool_count', 0)}
        if (re.search(r"(?:chuyển(?: máy)?|gặp|nói chuyện với).{0,35}(?:nhân viên|chuyên viên|quản lý|người thật)",
                      state["safe_text"], re.I)
                and not re.search(r"(?:không|chưa|đừng).{0,12}(?:chuyển|gặp)", state["safe_text"], re.I)):
            result = await business.invoke("handoff.transfer", {"brief": {
                "escalation_reason": "khach_yeu_cau_gap_nguoi"}})
            queued = state.get("needs_handoff", False)
            return {"agent_draft": ("Dạ, yêu cầu của mình đã được chuyển để nhân viên tiếp nhận ạ."
                                     if queued else "Dạ, hiện em chưa chuyển được yêu cầu. Anh/chị vui lòng liên hệ tổng đài để được hỗ trợ ạ."),
                    "tool_calls": state["tool_calls"], "tool_count": state.get("tool_count", 0),
                    "needs_handoff": queued, "handoff_ticket_id": state.get("handoff_ticket_id")}
        task = followup_task(state)
        state['followup_kind'] = task.kind
        await business.prepare_order_status()
        if (task.kind == 'none' and state.get('identity_status') == 'known' and state.get('tool_calls')
                and state['tool_calls'][-1].get('name') == 'order.status'
                and 'error' not in state['tool_calls'][-1].get('result', {})
                and state['tool_calls'][-1]['result'].get('ok') is not False
                and state['tool_calls'][-1]['result'].get('success') is not False
                and state['tool_calls'][-1]['result'].get('orders') == []):
            status_reply = safe_order_status_reply(state)
            if status_reply:
                return {'agent_draft': status_reply, 'tool_calls': state['tool_calls'],
                        'tool_count': state.get('tool_count', 0)}
        from app.mcp_servers.mcp_shared.basket import current_basket_quote
        from app.agent.harness.catalog_query import explicit_product_queries
        basket_confirmation = _search_text(state['safe_text'])
        if (task.kind == 'none' and current_basket_quote(state) is not None
                and re.search(r'dong y|xac nhan', basket_confirmation)
                and re.search(r'tong gia do|bao gia|ca (?:hai|2)', basket_confirmation)
                and not re.search(r'\bdoi\b|chuyen sang', basket_confirmation)
                and not explicit_product_queries(state['safe_text'])):
            completed = await business.complete_purchase_if_ready()
            if completed and completed.get('status') == 'created':
                return {'agent_draft': safe_transaction_reply(state),
                        'tool_calls': state['tool_calls'], 'tool_count': state.get('tool_count', 0)}
        # Both operations are reads; prompt fetching need not wait for MCP reads.
        try:
            async with asyncio.TaskGroup() as preparation:
                prompt_read = preparation.create_task(asyncio.to_thread(text_prompt, SALES_PROMPT, _SYSTEM_PROMPT))
                preparation.create_task(business.prepare_consultation() if task.kind == 'none'
                                        else business.prepare_followup(task))
        except ExceptionGroup as exc:
            if len(exc.exceptions) == 1:
                raise exc.exceptions[0] from exc
            raise
        if task.kind == 'none':
            completed = await business.complete_purchase_if_ready()
            if completed and completed.get('status') == 'created':
                return {'agent_draft': safe_transaction_reply(state),
                        'tool_calls': state['tool_calls'], 'tool_count': state.get('tool_count', 0)}
            # These replies use only prepared evidence and still pass the normal verifier.
            from app.mcp_servers.mcp_shared.consultation import derive_consultation
            from app.mcp_servers.mcp_shared.consultation_followup import product_price_requested
            prepared_reply = None
            if not derive_consultation(state).purchase_intent:
                prepared_reply = safe_product_reply(state)
                if not prepared_reply and product_price_requested(state['safe_text']) and not product_question_fields(state['safe_text']):
                    prepared_reply = safe_quote_reply(state)
            if prepared_reply and _task_answer_complete(prepared_reply, state):
                return {'agent_draft': prepared_reply, 'tool_calls': state['tool_calls'],
                        'tool_count': state.get('tool_count', 0)}
        elif task.kind in {'price_objection', 'returning_objection'}:
            prepared_reply = safe_followup_reply(state, task)
            if prepared_reply and _task_answer_complete(prepared_reply, state):
                return {'agent_draft': prepared_reply, 'tool_calls': state['tool_calls'],
                        'tool_count': state.get('tool_count', 0), 'followup_kind': task.kind,
                        'policy_order_bindings': state.get('policy_order_bindings', {})}
        elif task.kind == 'policy':
            prepared_reply = safe_followup_reply(state, task)
            product_reply = safe_product_reply(state)
            price_reply = safe_quote_reply(state)
            if prepared_reply and product_reply:
                if price_reply and prepared_reply.startswith(price_reply):
                    prepared_reply = prepared_reply[len(price_reply):].lstrip()
                prepared_reply = product_reply + ' ' + prepared_reply
            if (prepared_reply
                    and 'Theo thông tin chính sách đã kiểm tra:' in prepared_reply
                    and _task_answer_complete(prepared_reply, state)):
                return {'agent_draft': prepared_reply, 'tool_calls': state['tool_calls'],
                        'tool_count': state.get('tool_count', 0), 'followup_kind': task.kind,
                        'policy_order_bindings': state.get('policy_order_bindings', {})}
        set_execution_phase("build")
        system_prompt = prompt_read.result()
        agent = build_agent("deep", self.llm, business, system_prompt)
        context = prompt_context(state, self.prompt_history_turns)
        input_messages = prompt_messages(context)
        messages = []
        try:
            set_execution_phase("model_invocation", "initial")
            result = await invoke_agent(agent,
                {"messages": input_messages},
                config={"recursion_limit": max(12, self.max_tool_calls * 4 + 4)},
                state=state,
            )
            execution_result(state)
            set_execution_phase("postprocess")
            refreshed_task = followup_task(state)
            if task.kind != 'policy':
                task = refreshed_task
            state['followup_kind'] = task.kind
            if task.kind == 'none':
                await business.prepare_consultation()
            else:
                await business.prepare_followup(task)
            from app.mcp_servers.mcp_shared.consultation import derive_consultation
            consultation = derive_consultation(state)
            state['consultation'] = consultation.model_dump(mode='json')
            diagnostic_emit('consultation_after', state=state, snapshot=state['consultation'], decision=consultation.model_dump(mode='json'))
            messages = result.get("messages", [])
            last_customer_message = max((index for index, item in enumerate(messages)
                                         if isinstance(item, HumanMessage)), default=-1)
            finals = [item for item in messages[last_customer_message + 1:]
                      if isinstance(item, AIMessage) and not item.tool_calls
                      and isinstance(item.content, str) and item.content.strip()]
            draft = finals[-1].content if finals else FALLBACK
            if finals:
                final_payload = _parse_json_object(draft)
                if final_payload and isinstance(final_payload.get("answer"), str):
                    draft = final_payload["answer"]
            draft = mask_pii(draft)
            if (self.guardrails_enabled and not consultation.purchase_intent
                    and not _task_answer_complete(draft, state)):
                # Leave ungrounded prices to the verifier so rejection evidence is retained.
                from app.agent.guardrails.checks import _money_claims
                unknown_price = (_money_claims(draft)
                                 and not state.get('consultation_scope', {}).get('known'))
                factual = (check_grounding(draft, build_commerce_evidence(state)) is None
                           and check_answer(draft, build_commerce_evidence(state), state['safe_text'], focus_sku=_claim_focus(state))[1] is None)
                if task.kind != 'none':
                    useful = safe_followup_reply(state, task) if factual else None
                else:
                    useful = None if unknown_price else (safe_order_status_reply(state) or safe_product_reply(state) or safe_catalog_reply(state) or safe_quote_reply(state))
                if useful:
                    draft = useful
            # A previous turn's offer is not evidence of today's promotion.
            # Refresh once when the product is unambiguous, then let the agent
            # rewrite its answer using the current tool result before verification.
            if (self.guardrails_enabled and task.kind == 'none'
                    and check_answer(draft, build_commerce_evidence(state), state["safe_text"])[1]
                    == "promotion_quote_missing"
                    and state.get("tool_count", 0) < self.max_tool_calls
                    and not any(call.get("name") == "pricing.get_quote"
                                for call in state.get("tool_calls", []))):
                observations = [*state.get("session_tool_calls", []), *state.get("tool_calls", [])]
                skus = {call.get("args", {}).get("sku") for call in observations
                        if call.get("name") == "pricing.get_quote"
                        and isinstance(call.get("result"), dict)
                        and "error" not in call["result"]}
                skus.update(item.get("sku") for call in observations
                            if call.get("name") == "catalog.search"
                            for item in call.get("result", {}).get("items", [])
                            if isinstance(item, dict))
                if not skus:
                    skus.update(state.get("scoped_facts", {}).get("product", {}))
                    remembered = state.get("profile", {}).get("product_advised", {}).get("value")
                    if isinstance(remembered, str) and remembered.startswith("SKU-"):
                        skus.add(remembered)
                skus.discard(None)
                if len(skus) == 1:
                    sku = next(iter(skus))
                    quote = await business.invoke("pricing.get_quote", {"sku": sku})
                    if ("error" not in quote and quote.get("sku") == sku
                            and type(quote.get("final_price_vnd")) is int):
                        set_execution_phase("model_invocation", "refresh")
                        result = await invoke_agent(agent,
                            {"messages": [*messages, HumanMessage(content=(
                                "Bản nháp nói về ưu đãi nhưng chưa có bằng chứng trong lượt này. "
                                "Báo giá công cụ vừa xác minh theo ngày hiện tại: "
                                + json.dumps(quote, ensure_ascii=False)
                                + ". Hãy viết lại câu trả lời chỉ theo báo giá này; "
                                "không dùng ưu đãi cũ hoặc hứa quà không có trong applied_promos."))]},
                            config={"recursion_limit": max(12, self.max_tool_calls * 4 + 4)}, state=state)
                        execution_result(state)
                        set_execution_phase("postprocess")
                        refreshed = result.get("messages", [])
                        last_human = max((i for i, item in enumerate(refreshed)
                                          if isinstance(item, HumanMessage)), default=-1)
                        finals = [item for item in refreshed[last_human + 1:]
                                  if isinstance(item, AIMessage) and not item.tool_calls
                                  and isinstance(item.content, str) and item.content.strip()]
                        draft = mask_pii(finals[-1].content) if finals else FALLBACK
        except Exception as exc:
            execution_result(state, exc=exc)
            log_event(state, "run_agent", "model_failed", level=logging.WARNING,
                      error_type=type(exc).__name__)
            draft = FALLBACK
        set_execution_phase("postprocess")
        completed = await business.complete_purchase_if_ready()
        exchange_attempted = any(c.get('name') == 'order.update'
            and c.get('args', {}).get('action') in {'exchange_size', 'exchange_product'}
            for c in state.get('tool_calls', []))
        if completed and completed.get('status') == 'created' or exchange_attempted:
            draft = safe_transaction_reply(state) or draft
            if task.kind == 'policy':
                policy_reply = safe_followup_reply(state, task)
                if policy_reply:
                    draft += ' ' + policy_reply
        else:
            useful = safe_followup_reply(state, task) if task.kind != 'none' else safe_consultation_reply(state)
            from app.mcp_servers.mcp_shared.consultation import derive_consultation
            calls = build_commerce_evidence(state)
            complete_draft = _task_answer_complete(draft, state)
            if (useful and (derive_consultation(state).purchase_intent or not complete_draft)
                    and (task.kind == 'none' or (self.guardrails_enabled
                        and check_grounding(draft, calls) is None
                        and check_answer(draft, calls, state['safe_text'], focus_sku=_claim_focus(state))[1] is None))):
                # Keep independently verified draft clauses when recovery only fills a gap.
                kept = []
                if not derive_consultation(state).purchase_intent and task.kind == 'none':
                    for clause in re.split(r'(?<!\d)[.!;](?!\d)|\n', draft):
                        if clause.strip() and clause.strip() not in useful and clause.strip() != FALLBACK.rstrip('.'):
                            if (check_grounding(clause, calls) is None
                                    and check_answer(clause, calls, state['safe_text'],
                                                     focus_sku=_claim_focus(state))[1] is None):
                                kept.append(clause.strip())
                draft = '. '.join([*kept, useful])
        handoffs = [call for call in state.get("tool_calls", [])
                    if call.get("name") == "handoff.transfer"]
        if handoffs and not any(
                isinstance(call.get("result"), dict)
                and call["result"].get("status") == "queued"
                and isinstance(call["result"].get("ticket_id"), str)
                and bool(call["result"]["ticket_id"]) for call in handoffs):
            draft = ("Dạ, hiện em chưa chuyển được yêu cầu. Anh/chị vui lòng "
                     "liên hệ tổng đài để được hỗ trợ ạ.")
        return {"agent_draft": draft, "tool_calls": state["tool_calls"],
                "tool_count": state.get("tool_count", 0),
                "consultation_scope": state.get("consultation_scope", {}),
                "followup_kind": state.get("followup_kind", "none"),
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
        from app.mcp_servers.mcp_shared.consultation import derive_consultation
        calls = build_commerce_evidence(state)
        policy_calls = [c for c in calls if c.get('name') == 'policy.search']
        policy_failed = bool(policy_calls and policy_calls[-1].get('result', {}).get('retrieval_status')
                             in {'unavailable', 'timeout', 'overloaded'})
        other_success = any(c.get('name') != 'policy.search' and 'error' not in c.get('result', {})
                            for c in calls)
        if policy_failed and not other_success:
            return {'agent_text': POLICY_UNAVAILABLE}

        def customer_reply(text):
            if policy_failed and POLICY_UNAVAILABLE not in text:
                return text + ' ' + POLICY_UNAVAILABLE
            return text

        reason = ("order_selection_mismatch" if transaction_selection_mismatch(state)
                  else check_grounding(draft, calls))
        log_event(state, "verify", "grounding_checked", accepted=reason is None,
                  **({"reason": reason} if reason else {}))
        answer = draft
        policy_task = followup_task(state)
        if reason is None and self.guardrails_enabled:
            answer, reason = check_answer(draft, calls, state["safe_text"], focus_sku=_claim_focus(state))
            if (reason is None and policy_task.kind == 'policy'
                    and not followup_answer_complete(state, policy_task, answer)):
                reason = 'policy_question_unanswered'
            log_event(state, "verify", "answer_checked", accepted=reason is None,
                      **({"reason": reason} if reason else {}))
        if not self.guardrails_enabled:
            log_event(state, "verify", "answer_check_disabled",
                      reason="AGENT_GUARDRAILS_ENABLED=false; kiểm tra bằng chứng vẫn chạy")
        if reason is None:
            return {"agent_text": customer_reply(mask_pii(answer.strip()) if answer.strip() else FALLBACK)}
        rejected = [rejected_draft(state, reason, draft)]
        recoveries = [safe_transaction_reply]
        if state.get('followup_kind') not in {None, 'none'}:
            recoveries.append(safe_followup_reply)
        recoveries.extend([safe_order_status_reply, safe_product_reply, safe_consultation_reply, safe_promotion_reply, safe_quote_reply])
        structured_search = any(c.get("name") == "catalog.search" and any(
            type(c.get("args", {}).get(k)) is int for k in ("min_room_area_m2", "max_price_vnd"))
            for c in calls)
        if reason != "unsupported_product_spec" or structured_search:
            recoveries.append(safe_catalog_reply)
        for recover in recoveries:
            log_event(state, "verify", "recovery_attempted", recovery=getattr(recover, "__name__", "other_recovery"))
            safe = recover(state)
            if not safe:
                log_event(state, "verify", "recovery_unavailable", recovery=getattr(recover, "__name__", "other_recovery"))
                continue
            safe_reason = check_grounding(safe, calls)
            checked = safe
            if safe_reason is None:
                checked, safe_reason = check_answer(safe, calls, state["safe_text"], focus_sku=_claim_focus(state))
            if (safe_reason is None and policy_task.kind == 'policy'
                    and not followup_answer_complete(state, policy_task, checked)):
                safe_reason = 'policy_question_unanswered'
            if safe_reason is None:
                log_event(state, "verify", "recovery_succeeded", recovery=getattr(recover, "__name__", "other_recovery"))
                return {"agent_text": customer_reply(checked), "verifier_events": rejected}
            log_event(state, "verify", "recovery_rejected", recovery=getattr(recover, "__name__", "other_recovery"), reason=safe_reason)
            rejected.append(rejected_draft(state, safe_reason, safe))
        log_event(state, "verify", "recovery_exhausted")
        return {"agent_text": POLICY_UNAVAILABLE if policy_failed else FALLBACK, "verifier_events": rejected}

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
