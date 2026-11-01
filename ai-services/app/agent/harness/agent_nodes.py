"""Outer graph nodes shared by the supported agent implementations."""

import logging
import json
import re
import asyncio
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.harness.context import prompt_context, prompt_messages
from app.agent.implementations import AgentKind, build_agent
from app.agent.implementations.business_agent import BusinessTools
from app.agent.prompts import SALES_PROMPT, text_prompt
from app.agent.implementations.business_agent import _SYSTEM_PROMPT
from app.agent.memory.episode_candidates import outcome_from_tool_calls
from app.agent.memory.store import memory_error_code
from app.agent.guardrails.checks import (FALLBACK, check_answer, check_grounding,
                                         customer_erasure_requested, mask_pii)
from app.agent.guardrails.diagnostics import rejected_draft
from app.agent.harness.session_nodes import (SessionNodes, safe_catalog_reply,
                                             safe_promotion_reply)
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


class AgentNodes(SessionNodes):
    guardrails_enabled = True

    def __init__(self, *args, agent_kind: AgentKind = "deep", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.agent_kind = agent_kind

    @trace_node("run_agent")
    async def run_agent(self, state: TurnState) -> dict[str, Any]:
        if state.get("memory_blocked") and customer_erasure_requested(state["safe_text"]):
            state["tool_calls"] = list(state.get("tool_calls", []))
            return await self._route_customer_erasure(state)
        if state.get("tool_failed"):
            return {"agent_draft": MEMORY_UNAVAILABLE}
        state["tool_calls"] = list(state.get("tool_calls", []))
        if customer_erasure_requested(state["safe_text"]):
            return await self._route_customer_erasure(state)
        business = BusinessTools(self.tools, state, self.max_tool_calls, self.clock)
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
        system_prompt = await asyncio.to_thread(text_prompt, SALES_PROMPT, _SYSTEM_PROMPT)
        agent = build_agent(self.agent_kind, self.llm, business, system_prompt)
        context = prompt_context(state, self.prompt_history_turns)
        input_messages = prompt_messages(context)
        messages = []
        try:
            result = await agent.ainvoke(
                {"messages": input_messages},
                config={"recursion_limit": max(12, self.max_tool_calls * 4 + 4)},
            )
            calls = state.get("tool_calls", [])
            purchase = re.search(r"\b(lên đơn|chốt đơn|đặt hàng|đặt mua)\b", state["safe_text"], re.I)
            negated = re.search(r"\b(không|chưa|đừng|hủy)\b", state["safe_text"], re.I)
            ready = {call.get("args", {}).get("sku") for call in calls
                     if call.get("name") == "inventory.check"
                     and call.get("result", {}).get("in_stock") is True} & {
                         call.get("args", {}).get("sku") for call in calls
                         if call.get("name") == "pricing.get_quote"
                         and type(call.get("result", {}).get("final_price_vnd")) is int
                         and "error" not in call.get("result", {})}
            if (purchase and not negated and len(ready) == 1
                    and state.get("identity_status") == "known"
                    and state.get("tool_count", 0) < self.max_tool_calls
                    and not any(call.get("name") == "order.create" for call in calls)):
                result = await agent.ainvoke(
                    {"messages": [*result.get("messages", input_messages), HumanMessage(content=(
                        "Khách đã yêu cầu tạo đơn; công cụ vừa xác minh tồn kho và giá. "
                        "Tiếp tục gọi order.create nếu đã đủ lựa chọn và điều kiện; "
                        "không hỏi địa chỉ/phương thức thanh toán khi có mặc định. "
                        "Nếu thiếu điều kiện khác, nêu rõ điều kiện còn thiếu."))]},
                    config={"recursion_limit": max(12, self.max_tool_calls * 4 + 4)})
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
            # A previous turn's offer is not evidence of today's promotion.
            # Refresh once when the product is unambiguous, then let the agent
            # rewrite its answer using the current tool result before verification.
            if (self.guardrails_enabled
                    and check_answer(draft, state.get("tool_calls", []), state["safe_text"])[1]
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
                        result = await agent.ainvoke(
                            {"messages": [*messages, HumanMessage(content=(
                                "Bản nháp nói về ưu đãi nhưng chưa có bằng chứng trong lượt này. "
                                "Báo giá công cụ vừa xác minh theo ngày hiện tại: "
                                + json.dumps(quote, ensure_ascii=False)
                                + ". Hãy viết lại câu trả lời chỉ theo báo giá này; "
                                "không dùng ưu đãi cũ hoặc hứa quà không có trong applied_promos."))]},
                            config={"recursion_limit": max(12, self.max_tool_calls * 4 + 4)})
                        refreshed = result.get("messages", [])
                        last_human = max((i for i, item in enumerate(refreshed)
                                          if isinstance(item, HumanMessage)), default=-1)
                        finals = [item for item in refreshed[last_human + 1:]
                                  if isinstance(item, AIMessage) and not item.tool_calls
                                  and isinstance(item.content, str) and item.content.strip()]
                        draft = mask_pii(finals[-1].content) if finals else FALLBACK
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
        return {"agent_draft": draft, "tool_calls": state["tool_calls"],
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
    async def verify_agent(self, state: TurnState) -> dict[str, Any]:
        draft = state.get("agent_draft", FALLBACK)
        grounding_reason = check_grounding(draft, state.get("tool_calls", []))
        log_event(state, "verify", "grounding_checked", accepted=grounding_reason is None,
                  **({"reason": grounding_reason} if grounding_reason else {}))
        if grounding_reason:
            rejected = [rejected_draft(state, grounding_reason, draft)]
            structured_search = any(
                call.get("name") == "catalog.search"
                and any(type(call.get("args", {}).get(key)) is int
                        for key in ("min_room_area_m2", "max_price_vnd"))
                for call in state.get("tool_calls", [])
            )
            if grounding_reason == "unsupported_product_spec" and structured_search:
                safe = safe_promotion_reply(state) or safe_catalog_reply(state)
                if safe and check_grounding(safe, state.get("tool_calls", [])) is None:
                    checked, safe_reason = check_answer(
                        safe, state.get("tool_calls", []), state["safe_text"])
                    if safe_reason is None:
                        return {"agent_text": checked, "verifier_events": rejected}
                    rejected.append(rejected_draft(state, safe_reason, safe))
            return {"agent_text": FALLBACK, "verifier_events": rejected}
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
        safe = safe_promotion_reply(state) or safe_catalog_reply(state)
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
        try:
            result = await self.memory.commit_turn(
                str(request.session_id), state.get("customer_id"),
                state["safe_text"], state["agent_text"], request.on.isoformat(),
                request.channel, str(request.client_msg_id),
                tool_observations=tool_calls,
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
        log_event(state, "persist", "memory_recorded", turn_no=result["turn_no"],
                  accepted_facts=0)
        return {"memory_writes": result["memory_writes"]}
