
from app.mcp_servers.mcp_shared.decision_diagnostics import emit as diagnostic_emit


import logging
import json
import time
import re
import asyncio
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.harness.context import prompt_context, prompt_messages
from app.agent.implementations import build_agent
from app.agent.implementations.business_agent import BusinessTools
from app.agent.implementations.business_agent import _write_receipt_valid
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
from app.mcp_servers.mcp_shared.commerce_evidence import CATALOG_TOOLS, build_commerce_evidence, successful
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


def _requested_write_missing(state):
    from app.mcp_servers.mcp_shared.commerce_rules import _search_text
    if state.get('identity_status') != 'known' or state.get('tool_failed'):
        return False
    text = _search_text(state.get('safe_text', ''))
    if re.search(r'\b(?:neu|gia su)\b', text):
        return False
    for clause in re.findall(r'[^.!?;,\n]+[.!?;,\n]?', text):
        if clause.rstrip().endswith('?') or re.search(r'\b(?:duoc khong|co duoc|the nao|bao nhieu)\b', clause):
            continue
        action = re.search(r'\b(?:(?P<create>len don|tao don|chot don|dat hang|dat\s+(?:giup|cho)'
                           r'|lay\s+(?:cai|mau|san pham|chiec|bo|doi))'
                           r'|(?P<update>(?:lam thu tuc|gui yeu cau|tao phieu)\s+(?:doi|tra)'
                           r'|doi\s+(?:sang|cho|giup)))\b', clause)
        if action is None or re.search(
                r'\b(?:chua|khong|dung|khoan|chi hoi|hoi ve|chinh sach|noi|bao|ke)\b',
                clause[:action.start()]):
            continue
        name = 'order.create' if action['create'] else 'order.update'
        if not any(
                call.get('name') == name and successful(call)
                and (name != 'order.update' or call.get('args', {}).get('order_id'))
                and _write_receipt_valid(name, call.get('args', {}), call['result'])
                for call in state.get('tool_calls', [])):
            return True
    return False


from app.agent.harness.execution_diagnostics import (
    execution_node, set_execution_phase, execution_result,
)


SAFE_VERIFICATION_FALLBACK = (
    "Dạ, em xin lỗi anh/chị vì hiện em chưa xác minh đủ thông tin để khẳng định chính xác. "
    "Em chưa thể xác nhận thông tin này ạ."
)


def _contextual_safe_fallback(state: TurnState, calls: list[dict[str, Any]], reason: str) -> str:
    honorific = state.get("honorific") if state.get("identity_status") == "known" else None
    address = honorific if isinstance(honorific, str) and honorific in {"anh", "chị", "cô", "chú", "bạn"} else "anh/chị"
    from app.agent.memory.reported_facts import _gift_only_skus
    gift_only = _gift_only_skus(calls)
    catalog_items = [
        item for call in calls if call.get("name") in {"catalog.search", "catalog.get_details"}
        for item in (call.get("result") or {}).get("items", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item.get("sku")
        and item["sku"] not in gift_only
    ]
    unique_items = {item["sku"]: item for item in catalog_items}
    target = None
    if unique_items:
        from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
        named = resolve_claim_skus(state.get('safe_text', ''), calls)
        matched = [unique_items[s] for s in named if s in unique_items]
        if len(matched) == 1:
            target = matched[0]
    if target is None:
        return SAFE_VERIFICATION_FALLBACK
    name = mask_pii(target["name"].strip())
    if not name:
        return SAFE_VERIFICATION_FALLBACK
    return (
        f"Dạ {address}, hiện em chưa xác minh đủ chi tiết về {name} để khẳng định chính xác. "
        "Em chưa thể xác nhận thông tin này ạ."
    )


class AgentNodes(SessionNodes):
    guardrails_enabled = True
    max_repair_attempts = 1
    safe_fallback_on_rejection = False
    semantic_review_enabled = True
    authorizer_enabled = True
    verify_enabled = True

    def __init__(self, llm, tools, memory, max_tool_calls: int, prompt_history_turns: int,
                 clock=None, *, max_repair_attempts: int = 1,
                 safe_fallback_on_rejection: bool = False,
                 semantic_review_enabled: bool = True,
                 authorizer_enabled: bool = True,
                 verify_enabled: bool = True) -> None:
        super().__init__(llm, tools, memory, max_tool_calls, prompt_history_turns, clock)
        self.max_repair_attempts = max(1, max_repair_attempts)
        self.safe_fallback_on_rejection = safe_fallback_on_rejection
        self.semantic_review_enabled = semantic_review_enabled
        self.authorizer_enabled = authorizer_enabled
        self.verify_enabled = verify_enabled

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
            if not self.authorizer_enabled:
                log_event(state, "run_agent", "authorizer_disabled", level=logging.WARNING, tool=name)
                return True
            return await authorize_write(self.llm, business.state, name, args, self.prompt_history_turns)

        business = BusinessTools(self.tools, state, self.max_tool_calls, self.clock,
                                 authorize_write=current_authorization)
        draft = ""
        reply_context = {}
        continuation = None
        try:
            set_execution_phase("build")
            system_prompt = await asyncio.to_thread(text_prompt, SALES_PROMPT, _SYSTEM_PROMPT)
            state['selected_system_prompt'] = system_prompt
            agent = build_agent("deep", self.llm, business, system_prompt)

            async def continue_agent(current, rejected_answer, reason):
                import json
                business.state = current
                messages = prompt_messages(prompt_context(current, self.prompt_history_turns))
                messages.extend([AIMessage(content=rejected_answer), HumanMessage(content=json.dumps({
                    'validation_error': reason,
                    'task': 'Hoàn tất đúng yêu cầu hiện tại bằng công cụ khi đủ dữ kiện và quyền. '
                            'Không hỏi xác nhận lại khi khách đã đồng ý rõ; không suy consent từ lời sửa này. '
                            'Giữ mọi điều kiện của khách. Chỉ báo thao tác thành công khi có biên nhận. '
                            'Nếu bị từ chối, thiếu dữ kiện hoặc công cụ lỗi, nói rõ giới hạn; không lặp thao tác.'
                }, ensure_ascii=False))])
                result = await invoke_agent(agent, {'messages': messages},
                    config={'recursion_limit': max(12, self.max_tool_calls * 4 + 4)}, state=current)
                finals = [message for message in result.get('messages', [])
                          if isinstance(message, AIMessage) and not message.tool_calls]
                return mask_pii(_answer_text(finals[-1])) if finals else ''

            continuation = continue_agent
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
                'agent_continuation': continuation,
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
        continuation = state.pop('agent_continuation', None)
        draft = state.get("agent_draft", "")
        if not self.verify_enabled:
            masked = mask_pii(draft.strip())
            log_event(state, "verify", "verify_disabled", level=logging.WARNING)
            return {'agent_continuation': None, "agent_text": masked, "verified_answer": masked, "reply_error": None}
        model_state = state
        if state.get('tool_failed'):
            model_state = {**state, 'history': [], 'customer_statements': [], 'profile': {},
                'scoped_facts': {'product': {}, 'room': {}}, 'episodes': [],
                'current_episode': None, 'call_brief': None, 'session_tool_calls': []}
        calls = build_commerce_evidence(model_state)
        semantic_reviews = {}

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
            if reason is None and self.semantic_review_enabled:
                context = prompt_context(model_state, self.prompt_history_turns)
                review_key = (answer, json.dumps(context, sort_keys=True, ensure_ascii=False, default=str))
                if review_key in semantic_reviews:
                    reason = semantic_reviews[review_key]
                else:
                    reason = await review_answer(self.llm, answer, context)
                    if reason != 'grounding_review_unavailable':
                        semantic_reviews[review_key] = reason
            log_event(state, 'verify', 'grounding_checked', accepted=reason is None, reason=reason)
            return answer, reason

        answer, reason = await validate(draft)
        if reason is None and callable(continuation) and _requested_write_missing(state):
            reason = 'unanswered_request'
        if reason is None:
            return {'agent_continuation': None, "agent_text": answer, 'verified_answer': answer, 'reply_error': None}
        rejected = [rejected_draft(state, reason, draft)] if draft else []
        tool_updates = {}
        try:
            from langchain_core.messages import SystemMessage
            if (callable(continuation) and not state.get('tool_failed')
                    and (reason in {'unanswered_request', 'unnecessary_clarification',
                                    'customer_constraint_violated', 'order_creation_unverified',
                                    'order_update_unverified'}
                         or reason in {'price_without_quote', 'promotion_quote_missing',
                                       'promotion_unverified', 'promotion_code_mismatch',
                                       'promotion_detail_unverified', 'stock_sku_mismatch',
                                       'stock_result_mismatch', 'stock_quantity_mismatch',
                                       'delivery_unverified'}
                         and (_requested_write_missing(state) or any(
                             call.get('name') in CATALOG_TOOLS and call['result'].get('items')
                             for call in calls)))
                    and state.get('tool_count', 0) < self.max_tool_calls
                    and state.get('tool_attempts', 0) < self.max_tool_calls * 2):
                log_event(state, 'verify', 'recovery_attempted', reason=reason)
                set_execution_phase('model_invocation', 'completion')
                draft = await continuation(state, draft, reason)
                calls = build_commerce_evidence(model_state)
                tool_updates = {key: state.get(key) for key in (
                    'tool_calls', 'tool_count', 'tool_attempts', 'policy_order_bindings',
                    'needs_handoff', 'handoff_ticket_id') if key in state}
                answer, reason = await validate(draft)
                if reason is None:
                    log_event(state, 'verify', 'recovery_succeeded')
                    return {'agent_continuation': None, 'agent_text': answer, 'verified_answer': answer, 'reply_error': None,
                            'verifier_events': rejected, **tool_updates}
                log_event(state, 'verify', 'recovery_rejected', reason=reason)
                rejected.append(rejected_draft(state, reason, draft))
            if self.tools is not None and not state.get('tool_failed'):
                known = set()
                for call in calls:
                    if call.get('name') in {'catalog.search', 'catalog.get_details'}:
                        for item in call['result'].get('items') or []:
                            if isinstance(item, dict) and item.get('name'):
                                if item.get('sku'):
                                    known.add(item['sku'])
                                for variant in item.get('variants') or []:
                                    if isinstance(variant, dict) and variant.get('variant_sku'):
                                        known.add(variant['variant_sku'])
                missing_skus = []
                for call in calls:
                    if call.get('name') in {'pricing.get_quote', 'pricing.quote_order'}:
                        for quote in [call['result'], *(call['result'].get('units') or [])]:
                            if not isinstance(quote, dict):
                                continue
                            q_sku = quote.get('sku') or (call.get('args', {}).get('sku') if call.get('name') == 'pricing.get_quote' else None)
                            if isinstance(q_sku, str) and q_sku and q_sku not in known:
                                missing_skus.append(q_sku)
                            for promo in quote.get('applied_promos') or []:
                                if (isinstance(promo, dict) and promo.get('type') == 'gift'
                                        and promo.get('gift_sku') and promo['gift_sku'] not in known
                                        and (not promo.get('valid_until')
                                             or promo['valid_until'] >= state['request'].on.isoformat())):
                                    missing_skus.append(promo['gift_sku'])
                    elif call.get('name') == 'inventory.check':
                        i_sku = call.get('args', {}).get('sku')
                        if isinstance(i_sku, str) and i_sku and i_sku not in known:
                            missing_skus.append(i_sku)
                missing = dict.fromkeys(missing_skus)
                business = BusinessTools(self.tools, state, self.max_tool_calls, self.clock)
                for sku in missing:
                    if (state.get('tool_count', 0) >= self.max_tool_calls
                            or state.get('tool_attempts', 0) >= self.max_tool_calls * 2):
                        break
                    await business.invoke('catalog.get_details', {'sku': sku})
                if reason in {'price_without_quote', 'promotion_quote_missing', 'promotion_unverified',
                              'stock_sku_mismatch', 'stock_result_mismatch', 'delivery_unverified'}:
                    from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
                    raw_calls = [*state.get('tool_calls', []), *state.get('session_tool_calls', [])]
                    quoted_today = {
                        c.get('args', {}).get('sku') for c in raw_calls
                        if c.get('name') == 'pricing.get_quote'
                    }
                    stocked_today = {
                        c.get('args', {}).get('sku') for c in raw_calls
                        if c.get('name') == 'inventory.check'
                    }
                    catalog_map = {}
                    for c in calls:
                        if c.get('name') in {'catalog.search', 'catalog.get_details'}:
                            for item in (c.get('result') or {}).get('items') or []:
                                if isinstance(item, dict) and item.get('sku'):
                                    catalog_map[item['sku']] = item
                                    for v in item.get('variants') or []:
                                        if isinstance(v, dict) and v.get('variant_sku'):
                                            catalog_map[v['variant_sku']] = {**v, 'variants': []}
                    mentioned_skus = resolve_claim_skus(f"{state.get('safe_text', '')} {draft}", calls)
                    candidate_skus = [
                        s for s in (mentioned_skus or list(catalog_map))
                        if s in catalog_map and not catalog_map[s].get('variants')
                    ][:3]
                    need_quote = reason in {'price_without_quote', 'promotion_quote_missing',
                                            'promotion_unverified', 'delivery_unverified'}
                    need_stock = reason in {'stock_sku_mismatch', 'stock_result_mismatch'} or bool(
                        re.search(r'(?i)\b(?:còn hàng|hết hàng|tồn kho|sẵn hàng)\b',
                                  f"{state.get('safe_text', '')} {draft}")
                    )
                    for sku in candidate_skus:
                        if (state.get('tool_count', 0) >= self.max_tool_calls
                                or state.get('tool_attempts', 0) >= self.max_tool_calls * 2):
                            break
                        if need_quote and sku not in quoted_today:
                            await business.invoke('pricing.get_quote', {'sku': sku})
                            quoted_today.add(sku)
                        if (need_stock and sku not in stocked_today
                                and state.get('tool_count', 0) < self.max_tool_calls):
                            await business.invoke('inventory.check', {'sku': sku})
                            stocked_today.add(sku)
                tool_updates.update({key: state.get(key, [] if key == 'tool_calls' else 0)
                                     for key in ('tool_calls', 'tool_count', 'tool_attempts')})
                calls = build_commerce_evidence(model_state)
            context = prompt_context(model_state, self.prompt_history_turns)
            base_messages = [SystemMessage(content=state.get('selected_system_prompt', _SYSTEM_PROMPT)),
                             *prompt_messages(context)]
            current_draft = draft
            current_reason = reason
            last_reason = reason
            had_infra_error = False
            for attempt in range(self.max_repair_attempts):
                messages = list(base_messages)
                if current_draft:
                    messages.append(AIMessage(content=mask_pii(current_draft)))
                price_instruction = (' Đối chiếu từng số tiền với báo giá của đúng sản phẩm hoặc giỏ hàng. '
                    'Với pricing.get_quote, báo giá bán theo final_price_vnd, viết đủ số tiền bằng chữ số '
                    'kèm đơn vị đồng, không làm tròn. Bỏ số tiền của các khoản phí, mức giảm hoặc giá trị '
                    'quà tặng chưa được xác minh.') if current_reason == 'price_without_quote' else ''
                promotion_instruction = (' Đối chiếu quà tặng với gift_sku trong applied_promos '
                    'của đúng sản phẩm mua và tên đã tra từ catalog. Khi đã có catalog, dùng đúng '
                    'tên ở trường name của quà, không tự rút gọn hay đổi tên. Không suy tên quà từ mã SKU; '
                    'không đổi sang quà khác hoặc tự thêm số lượng, giá trị, hạn ưu đãi. '
                    'Miễn phí COD và miễn phí vận chuyển là hai quyền lợi riêng. '
                    'Nếu chưa tra được tên quà, nói rõ phần chưa xác minh.') if current_reason.startswith('promotion_') else ''
                extra_instruction = (
                    ' Chỉ nêu ngày giao dự kiến khớp đúng estimated_delivery trong báo giá/đơn hàng hiện tại, '
                    'không cam kết chắc chắn.' if current_reason == 'delivery_unverified'
                    else ' Chỉ nêu trạng thái còn/hết hàng khớp đúng inventory.check hiện tại của đúng sản phẩm.'
                    if current_reason.startswith('stock_')
                    else ' Không dùng từ so sánh tuyệt đối như tốt nhất, phù hợp nhất, hiệu quả nhất cho sản phẩm.'
                    if current_reason == 'unsupported_comparison'
                    else ' Bỏ toàn bộ chi tiết quy trình, số ngày, điều kiện hoặc khẳng định không có trong tool_observations hiện tại; chỉ giữ phần có nguồn hoặc hỏi thông tin còn thiếu.'
                    if current_reason == 'unsupported_answer_claim'
                    else ' Bắt buộc trả lời bằng văn bản tiếng Việt rõ ràng, không gọi công cụ và không để trống.'
                    if current_reason == 'empty_answer' else ''
                )
                final_attempt_instruction = (
                    ' Đây là lần sửa cuối: trả lời ngắn gọn, lịch sự, chỉ giữ phần đã có bằng chứng rõ ràng '
                    'hoặc nói rõ phần chưa xác minh và hỏi làm rõ; tuyệt đối bỏ mọi con số, giá, khuyến mãi, '
                    'ngày giao, tồn kho hoặc so sánh chưa chắc chắn.'
                ) if self.max_repair_attempts > 1 and attempt == self.max_repair_attempts - 1 else ''
                messages.append(HumanMessage(content=json.dumps({
                    'task': ('Viết lại câu trả lời mới cho yêu cầu hiện tại, chỉ dùng bằng chứng đã có; '
                        'không lặp lại nguyên văn bản nháp vừa bị từ chối. '
                        'Ưu tiên thông báo đúng trạng thái thao tác đã được công cụ xác nhận. '
                        'Không thực hiện thêm thao tác. Khi memory không khả dụng, không suy đoán '
                        'lịch sử riêng của khách. Yêu cầu xóa toàn bộ dữ liệu cần xác minh/chuyển '
                        'bộ phận phụ trách, chưa được coi là đã xóa. Không đọc mã lỗi nội bộ cho khách. '
                        'Nếu thiếu dữ kiện, hỏi làm rõ hoặc nói rõ phần chưa xác minh. '
                        'Không thay bằng báo giá/sản phẩm của chủ đề khác.'
                        + price_instruction + promotion_instruction + extra_instruction + final_attempt_instruction),
                    'validation_error': current_reason,
                    'runtime_status': state.get('reply_context', {}),
                }, ensure_ascii=False)))
                log_event(state, 'verify', 'recovery_attempted', level=logging.DEBUG, reason=current_reason)
                set_execution_phase('model_invocation', 'repair')
                repair = await self.llm.ainvoke(messages)
                execution_result(state)
                set_execution_phase('verification')
                repaired = mask_pii(_answer_text(repair))
                checked, repair_reason = await validate(repaired)
                if repair_reason is None:
                    log_event(state, 'verify', 'recovery_succeeded', level=logging.DEBUG)
                    return {'agent_continuation': None, "agent_text": checked, 'verified_answer': checked,
                            'reply_error': None, "verifier_events": rejected, **tool_updates}
                log_event(state, 'verify', 'recovery_rejected', level=logging.DEBUG, reason=repair_reason)
                rejected.append(rejected_draft(state, repair_reason, repaired))
                last_reason = repair_reason
                if repair_reason in {'internal_output', 'grounding_review_unavailable'}:
                    had_infra_error = True
                    break
                if repair_reason == 'empty_answer' and not draft:
                    had_infra_error = True
                    break
                if repaired:
                    current_draft = repaired
                current_reason = repair_reason
            if (self.safe_fallback_on_rejection and not had_infra_error
                    and bool(draft)
                    and last_reason not in {'internal_output', 'grounding_review_unavailable'}
                    and state.get('reply_context', {}).get('reason') not in {'model_unavailable', 'memory_unavailable'}):
                candidate_fb = _contextual_safe_fallback(model_state, calls, last_reason)
                for fb_text in (candidate_fb, SAFE_VERIFICATION_FALLBACK):
                    fb_grounding = check_grounding(fb_text, calls)
                    fb_answer, fb_reason = (
                        check_answer(fb_text, calls, state["safe_text"], focus_sku=_claim_focus(model_state))
                        if fb_grounding is None and self.guardrails_enabled else (fb_text, fb_grounding)
                    )
                    if fb_reason is None and fb_answer:
                        log_event(state, 'verify', 'recovery_fallback', level=logging.WARNING, reason=last_reason)
                        return {'agent_continuation': None, "agent_text": fb_answer, 'verified_answer': fb_answer,
                                'reply_error': None, "verifier_events": rejected, **tool_updates}
        except Exception as exc:
            execution_result(state, exc=exc)
            log_event(state, "verify", "repair_failed", level=logging.WARNING,
                      error_type=type(exc).__name__)
        log_event(state, 'verify', 'recovery_exhausted', level=logging.DEBUG)
        return {'agent_continuation': None, "agent_text": '', 'verified_answer': '', 'reply_error': 'agent_reply_unavailable',
                "verifier_events": rejected, **tool_updates}

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
