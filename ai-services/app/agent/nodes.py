"""Dependency-bound LangGraph nodes for one text turn."""

import json
import logging
import re
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.context import load_context, prompt_context
from app.agent.guardrails import FALLBACK, check_answer, has_money_claim, mask_pii, valid_catalog_quote
from app.agent.memory import MemoryStore
from app.agent.observability import (
    log_event, log_invalid_model_output, log_model_output,
    log_tool_input, log_tool_output, trace_node,
)
from app.agent.policy import (
    ALLOWED_TOOLS, filter_owned_orders, prepare_tool_call, response_price_precondition,
)
from app.agent.price_intent import detect_price_intent
from app.agent.prompts import system_prompt
from app.agent.state import Decision, TurnState, parse_decision
from app.agent.tool_gateway import ToolGateway
from app.constants import CATALOG_RESULT_LIMIT


def _price_catalog_query(customer_text: str) -> str:
    text = re.sub(
        r"(?i)\b(?:có loại nào|có mẫu nào|những loại nào|loại nào|mẫu nào|máy nào|"
        r"sản phẩm nào|đang khuyến mãi|khuyến mãi|đang giảm giá|giảm giá|ưu đãi|sale|"
        r"giá bao nhiêu|bao nhiêu tiền|bao nhiêu|mấy tiền|giảm|giá|các|những|cho em hỏi|cho anh hỏi|"
        r"hiện tại|không em|em ơi|anh ơi|ạ|nhé)\b", " ", customer_text,
    )
    return " ".join(re.findall(r"[\w-]+", text, flags=re.UNICODE)).strip()


def _single_price_sku(items: list[dict[str, Any]], customer_text: str) -> str | None:
    if len(items) == 1 and isinstance(items[0], dict):
        return items[0].get("sku")
    if re.search(r"(?i)\b(?:màng lọc|phụ kiện|thay thế)\b", customer_text):
        return None
    products = [item for item in items if isinstance(item, dict)
                and isinstance(item.get("category"), str)
                and not item["category"].endswith("phu-kien")]
    return products[0].get("sku") if len(products) == 1 else None


def _catalog_for_quote_sweep(state: TurnState) -> dict[str, Any] | None:
    intent = detect_price_intent(state["safe_text"])
    if not (state["decision"].needs_price or intent.needs_price):
        return None
    calls = [call for call in state.get("tool_calls", []) if call.get("name") != "crm.get_customer"]
    if not calls or calls[-1].get("name") != "catalog.search":
        return None
    result = calls[-1].get("result", {})
    return (result if "error" not in result and isinstance(result.get("items"), list)
            and len(result["items"]) >= 2 else None)


def _vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + "đ"


def _quote_sweep_reply(state: TurnState) -> str:
    sweep = state["quote_sweep"]
    items = sweep["items"]
    quoted = {
        call["args"].get("sku"): call["result"]
        for call in state.get("tool_calls", [])
        if call.get("name") == "pricing.get_quote"
        and call.get("args", {}).get("on") == state["request"].on.isoformat()
        and "error" not in call.get("result", {})
    }
    promo_question = sweep["promo_question"]
    valid = []
    for item in items:
        sku = item.get("sku")
        quote = quoted.get(sku)
        if not isinstance(sku, str) or not valid_catalog_quote(
            sku, quote, promotions=promo_question
        ):
            continue
        valid.append((item["name"], quote))
    if not valid:
        return "Dạ, hiện em chưa kiểm tra được báo giá cho các mẫu này. Anh/chị cho em tên mẫu cần xem trước ạ?"

    total = sweep["total"]
    header = f"Dạ, em đã kiểm tra báo giá ngày {state['request'].on:%d/%m/%Y} cho {len(valid)}/{total} mẫu."
    details = []
    if promo_question:
        discounts = []
        gifts = []
        shipping = []
        for name, quote in valid:
            discount = quote["list_price_vnd"] - quote["final_price_vnd"]
            if discount > 0 and any(isinstance(promo, dict)
                                    and isinstance(promo.get("discount_vnd"), int)
                                    and promo["discount_vnd"] > 0
                                    for promo in quote["applied_promos"]):
                discounts.append(f"{name}: giảm {_vnd(discount)}, còn {_vnd(quote['final_price_vnd'])}")
            if any(isinstance(promo, dict) and promo.get("type") == "gift"
                   for promo in quote["applied_promos"]):
                gifts.append(name)
            if quote["freeship"]:
                shipping.append(name)
        if discounts:
            details.append("Đang giảm giá: " + "; ".join(discounts) + ".")
        else:
            details.append("Trong các mẫu đã kiểm tra, em chưa thấy giảm giá bằng tiền.")
        if gifts:
            details.append("Có quà tặng: " + ", ".join(gifts) + ".")
        if shipping:
            if len(shipping) == len(valid):
                details.append("Các mẫu đã kiểm tra đều được miễn phí vận chuyển.")
            else:
                details.append("Miễn phí vận chuyển: " + ", ".join(shipping) + ".")
    else:
        details.append("Giá hiện tại: " + "; ".join(
            f"{name}: {_vnd(quote['final_price_vnd'])}" for name, quote in valid) + ".")
    if len(valid) < total:
        details.append("Em chưa xác minh được các mẫu còn lại; anh/chị cho em tên mẫu cần kiểm tra tiếp ạ?")
    return mask_pii(" ".join([header, *details]))


def _safe_catalog_reply(state: TurnState) -> str | None:
    """Use only catalog names if a product-advice rewrite cannot be verified."""
    if not re.search(r"(?i)\b(?:tư vấn|gợi ý|phù hợp)\b", state["safe_text"]):
        return None
    calls = [call for call in state.get("tool_calls", []) if call.get("name") != "crm.get_customer"]
    if not calls or calls[-1].get("name") != "catalog.search":
        return None
    result = calls[-1].get("result", {})
    if "error" in result or not isinstance(result.get("items"), list):
        return None
    names = [item["name"] for item in result["items"] if isinstance(item, dict)
             and isinstance(item.get("name"), str) and item["name"].strip()][:3]
    if not names:
        return None
    question = ("Chị muốn tìm hiểu mẫu nào kỹ hơn ạ?"
                if re.search(r"(?i)\b\d+\s*(?:m2|m²|mét vuông)\b", state["safe_text"])
                else "Chị cho em biết diện tích phòng để em tư vấn mẫu phù hợp hơn ạ?")
    return mask_pii("Dạ, em tìm thấy " + ", ".join(names) + ". " + question)


class AgentNodes:
    def __init__(self, llm: BaseChatModel, tools: ToolGateway, memory: MemoryStore,
                 max_tool_calls: int, prompt_history_turns: int) -> None:
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.max_tool_calls = max_tool_calls
        self.prompt_history_turns = prompt_history_turns

    @trace_node("accept")
    async def accept(self, state: TurnState) -> dict[str, Any]:
        return {
            "safe_text": mask_pii(state["request"].text),
            "received_at_monotonic": time.perf_counter(),
            "tool_calls": [], "tool_count": 0, "tool_failed": False,
            "needs_handoff": False, "handoff_ticket_id": None,
        }

    @trace_node("resolve_identity")
    async def resolve_identity(self, state: TurnState) -> dict[str, Any]:
        request = state["request"]
        identity = request.channel_identity
        key = {
            "hotline": "phone", "chat_fanpage": "fb_id", "zalo_oa": "zalo_id",
        }.get(request.channel)
        if not key or not identity:
            log_event(state, "resolve_identity", "identity_resolved", status="unknown", lookup="skipped")
            return {"identity_status": "unknown", "customer_id": None,
                    "customer_phone": None, "customer_name": None,
                    "honorific": None, "crm_sessions": [], "owned_order_ids": []}
        args = {key: identity}
        log_tool_input("resolve_identity", "crm.get_customer", args)
        try:
            result = await self.tools.invoke("crm.get_customer", args)
        except Exception as exc:
            log_event(state, "resolve_identity", "tool_failed", level=logging.WARNING,
                      tool="crm.get_customer", error_type=type(exc).__name__)
            result = {"error": "tool_error"}
        log_event(state, "resolve_identity", "tool_result", tool="crm.get_customer",
                  success="error" not in result)
        log_tool_output(state, "resolve_identity", "crm.get_customer", result)
        calls = [{"name": "crm.get_customer", "args": args, "result": result}]
        if result.get("ambiguous"):
            log_event(state, "resolve_identity", "identity_resolved", status="ambiguous")
            return {"identity_status": "ambiguous", "customer_id": None,
                    "customer_phone": None, "customer_name": None,
                    "honorific": None, "crm_sessions": [], "owned_order_ids": [], "tool_calls": calls}
        if result.get("found") and result.get("customer_id"):
            owned_ids = [order["order_id"] for order in result.get("orders", [])
                         if isinstance(order, dict) and isinstance(order.get("order_id"), str)]
            log_event(state, "resolve_identity", "identity_resolved", status="known",
                      owned_orders=len(owned_ids))
            return {"identity_status": "known", "customer_id": result["customer_id"],
                    "customer_phone": result.get("phone"),
                    "customer_name": result.get("name"), "honorific": result.get("honorific"),
                    "crm_sessions": result.get("sessions", []),
                    "owned_order_ids": owned_ids, "tool_calls": calls}
        log_event(state, "resolve_identity", "identity_resolved", status="unknown")
        return {"identity_status": "unknown", "customer_id": None,
                "customer_phone": None, "customer_name": None,
                "honorific": None, "crm_sessions": [], "owned_order_ids": [], "tool_calls": calls}

    @trace_node("retrieve_context")
    async def retrieve_context(self, state: TurnState) -> dict[str, Any]:
        result = await load_context(state, self.memory, self.tools)
        log_event(state, "retrieve_context", "context_loaded",
                  history_turns=len(result.get("history", [])),
                  profile_facts=len(result.get("profile", {})),
                  episodes=len(result.get("episodes", [])),
                  call_brief=bool(result.get("call_brief")),
                  success=not result.get("tool_failed", False))
        return result

    @trace_node("plan")
    async def plan(self, state: TurnState) -> dict[str, Any]:
        if state.get("tool_failed"):
            log_event(state, "plan", "fallback", reason="tool_failed")
            return {"decision": Decision(action="respond", response=FALLBACK)}
        context = prompt_context(state, self.prompt_history_turns)
        prompt = system_prompt(ALLOWED_TOOLS)
        user_context = HumanMessage(content=json.dumps(context, ensure_ascii=False, default=str))
        decision = None
        for attempt in range(2):
            instruction = ("\n\nLần trước sai định dạng. Chỉ trả một JSON object hợp lệ "
                           "theo đúng schema đã nêu, không dùng markdown hoặc văn bản ngoài JSON."
                           if attempt else "")
            try:
                answer = await self.llm.ainvoke([
                    SystemMessage(content=prompt + instruction), user_context,
                ])
            except Exception as exc:
                log_event(state, "plan", "model_failed", level=logging.WARNING,
                          error_type=type(exc).__name__)
                break
            try:
                if not isinstance(answer.content, str):
                    raise ValueError("non-text model output")
                decision, ignored_writes, had_fence = parse_decision(answer.content)
            except ValueError as exc:
                log_invalid_model_output(state, answer.content, exc,
                                         getattr(answer, "response_metadata", None))
                log_event(state, "plan", "model_failed", level=logging.WARNING,
                          error_type=type(exc).__name__)
                if attempt == 0:
                    log_event(state, "plan", "model_retry")
                continue
            if had_fence:
                log_event(state, "plan", "model_fence_removed")
            log_model_output(state, decision)
            if ignored_writes:
                log_event(state, "plan", "memory_proposals_ignored",
                          ignored_facts=ignored_writes)
            break
        if decision is None:
            decision = Decision(action="respond", response=FALLBACK)
        intent = detect_price_intent(state["safe_text"])
        price_block = response_price_precondition({**state, "decision": decision})
        if price_block is not None:
            reason, sku = price_block
            log_event(state, "plan", "blocked", reason=reason)
            if sku and state["tool_count"] < self.max_tool_calls:
                decision = Decision(action="tool", tool_name="pricing.get_quote",
                                    tool_args={"sku": sku}, needs_price=True)
        if decision.action == "respond" and (decision.needs_price or intent.needs_price):
            searches = [call for call in state.get("tool_calls", [])
                        if call.get("name") == "catalog.search" and
                        "error" not in call.get("result", {})]
            items = searches[-1]["result"].get("items", []) if searches else []
            if (not searches and not intent.competitor
                    and state["tool_count"] < self.max_tool_calls):
                query = _price_catalog_query(state["safe_text"])
                if query or intent.broad:
                    log_event(state, "plan", "catalog_required")
                    decision = Decision(action="tool", tool_name="catalog.search",
                                        tool_args={"query": query} if query else {},
                                        needs_price=True)
            else:
                sku = _single_price_sku(items, state["safe_text"])
                quoted = any(call.get("name") == "pricing.get_quote"
                             and call.get("args", {}).get("sku") == sku
                             and call.get("args", {}).get("on") == state["request"].on.isoformat()
                             and "error" not in call.get("result", {})
                             for call in state.get("tool_calls", []))
                evidenced_draft = (has_money_claim(decision.response)
                                   and response_price_precondition({**state, "decision": decision}) is None)
                if (sku and not quoted and not evidenced_draft
                        and state["tool_count"] < self.max_tool_calls):
                    log_event(state, "plan", "quote_required", sku=sku)
                    decision = Decision(action="tool", tool_name="pricing.get_quote",
                                        tool_args={"sku": sku}, needs_price=True)
        if response_price_precondition({**state, "decision": decision}) is not None:
            decision = Decision(action="respond",
                                response="Dạ, anh/chị cho em biết mẫu cần kiểm tra giá ạ?")
        log_event(state, "plan", "decision", action=decision.action,
                  tool=decision.tool_name if decision.tool_name in ALLOWED_TOOLS else None,
                  proposed_memory_writes=len(decision.memory_writes))
        return {"decision": decision}

    async def route_plan(self, state: TurnState) -> str:
        decision = state["decision"]
        if decision.action == "tool" and state["tool_count"] < self.max_tool_calls:
            log_event(state, "route_plan", "routed", next="call_tool",
                      tool_count=state["tool_count"])
            return "call_tool"
        log_event(state, "route_plan", "routed", next="verify",
                  reason="tool_limit" if decision.action == "tool" else "respond",
                  tool_count=state["tool_count"])
        return "verify"

    @trace_node("call_tool")
    async def call_tool(self, state: TurnState) -> dict[str, Any]:
        request = state["request"]
        prepared = prepare_tool_call(state)
        if prepared is None:
            log_event(state, "call_tool", "blocked", reason="precondition_or_arguments")
            return {"tool_failed": True, "tool_count": state["tool_count"] + 1}
        name, args = prepared
        log_event(state, "call_tool", "invoking", tool=name, tool_count=state["tool_count"] + 1)
        log_tool_input("call_tool", name, args)
        try:
            if hasattr(self.tools, "invoke_trusted"):
                result = await self.tools.invoke_trusted(name, args, state.get("customer_id"),
                    request.channel, request.channel_identity,
                    f"{request.session_id}:{request.client_msg_id}:{name}:{state['tool_count']}")
            else:
                result = await self.tools.invoke(name, args)
        except Exception as exc:
            log_event(state, "call_tool", "tool_failed", level=logging.WARNING,
                      tool=name, error_type=type(exc).__name__)
            result = {"error": "tool_error"}
        if not isinstance(result, dict):
            result = {"error": "invalid_tool_result"}
        result = filter_owned_orders(name, args, result, state)
        log_event(state, "call_tool", "tool_result", tool=name,
                  success="error" not in result)
        log_tool_output(state, "call_tool", name, result)
        call = {"name": name, "args": args, "result": result}
        output: dict[str, Any] = {
            "tool_calls": [*state.get("tool_calls", []), call],
            "tool_count": state["tool_count"] + 1,
            "tool_failed": "error" in result,
        }
        if name == "pricing.get_quote" and "error" in result:
            output["needs_handoff"] = True
        if name == "handoff.transfer" and result.get("ticket_id"):
            output["needs_handoff"] = True
            output["handoff_ticket_id"] = str(result["ticket_id"])
        return output

    async def route_tool(self, state: TurnState) -> str:
        if state["tool_failed"]:
            next_step = "verify"
        elif _catalog_for_quote_sweep(state) is not None:
            next_step = "quote_catalog"
        else:
            next_step = "plan"
        log_event(state, "route_tool", "routed", next=next_step,
                  tool_failed=state["tool_failed"], tool_count=state["tool_count"])
        return next_step

    @trace_node("quote_catalog")
    async def quote_catalog(self, state: TurnState) -> dict[str, Any]:
        catalog = _catalog_for_quote_sweep(state)
        if catalog is None:
            return {"quote_sweep": {"items": [], "total": 0, "promo_question": False}}
        # This bounded sweep is separate from model tool steps.
        items = [item for item in catalog["items"][:CATALOG_RESULT_LIMIT]
                 if isinstance(item, dict) and isinstance(item.get("sku"), str)
                 and isinstance(item.get("name"), str)]
        calls = list(state.get("tool_calls", []))
        seen = set()
        quote_failed = False
        for item in items:
            sku = item["sku"]
            if sku in seen:
                continue
            seen.add(sku)
            prepared = prepare_tool_call({**state, "decision": Decision(
                action="tool", tool_name="pricing.get_quote", tool_args={"sku": sku})})
            if prepared is None:
                continue
            name, args = prepared
            log_tool_input("quote_catalog", name, args)
            try:
                if hasattr(self.tools, "invoke_trusted"):
                    result = await self.tools.invoke_trusted(
                        name, args, state.get("customer_id"),
                        state["request"].channel, state["request"].channel_identity,
                        f"{state['request'].session_id}:{state['request'].client_msg_id}:{name}:{sku}")
                else:
                    result = await self.tools.invoke(name, args)
            except Exception as exc:
                log_event(state, "quote_catalog", "tool_failed", level=logging.WARNING,
                          tool=name, error_type=type(exc).__name__)
                result = {"error": "tool_error"}
            if not isinstance(result, dict):
                result = {"error": "invalid_tool_result"}
            quote_failed = quote_failed or "error" in result
            log_event(state, "quote_catalog", "tool_result", tool=name,
                      success="error" not in result)
            log_tool_output(state, "quote_catalog", name, result)
            calls.append({"name": name, "args": args, "result": result})
        reported_total = catalog.get("total")
        total = max(reported_total, len(items)) if isinstance(reported_total, int) else len(items)
        return {"tool_calls": calls, "tool_count": state["tool_count"] + len(seen),
                "needs_handoff": quote_failed,
                "quote_sweep": {"items": items, "total": total,
                                "promo_question": detect_price_intent(state["safe_text"]).promotion}}

    @trace_node("verify")
    async def verify(self, state: TurnState) -> dict[str, Any]:
        if state.get("quote_sweep") is not None:
            answer = _quote_sweep_reply(state)
            log_event(state, "verify", "answer_checked", accepted=True, reason="quote_sweep")
            return {"agent_text": answer}
        decision = state["decision"]
        if state.get("tool_failed") or decision.action != "respond":
            log_event(state, "verify", "answer_checked", accepted=False,
                      reason="tool_failed_or_no_response")
            return {"agent_text": FALLBACK}
        answer, reason = check_answer(decision.response, state.get("tool_calls", []),
                                      state["safe_text"])
        log_event(state, "verify", "answer_checked", accepted=reason is None,
                  **({"reason": reason} if reason else {}))
        if reason is None or decision.response == FALLBACK:
            return {"agent_text": answer}

        log_event(state, "verify", "repair_attempt", reason=reason)
        repair_prompt = (
            system_prompt(ALLOWED_TOOLS)
            + "\n\nCâu trả lời vừa bị từ chối vì " + reason + ". "
            "Viết lại câu trả lời ngắn với action='respond'. Không lặp số tiền "
            "ngân sách hoặc giá đối thủ khi chưa có quote hỗ trợ đúng SKU. "
            "Không nêu giá bán nếu chưa có pricing.get_quote. "
            "Nếu nói về mức giảm, phân biệt mức giảm với giá bán và đối chiếu "
            "list_price_vnd, final_price_vnd cùng applied_promos trong báo giá. "
            "Chỉ nói khuyến mãi nào đang áp dụng theo báo giá của ngày nghiệp vụ. "
            "Chỉ nêu tên và thuộc tính được tool chứng minh; không thêm tính năng "
            "hay so sánh 'phù hợp nhất'. Giữ memory_writes=[]."
        )
        context = prompt_context(state, self.prompt_history_turns)
        model_reply = None
        try:
            model_reply = await self.llm.ainvoke([
                SystemMessage(content=repair_prompt),
                HumanMessage(content=json.dumps(context, ensure_ascii=False, default=str)),
            ])
            if not isinstance(model_reply.content, str):
                raise ValueError("non-text model output")
            repaired_decision, ignored_writes, had_fence = parse_decision(model_reply.content)
            if had_fence:
                log_event(state, "verify", "model_fence_removed")
            log_model_output(state, repaired_decision, step="verify")
            if ignored_writes:
                log_event(state, "verify", "memory_proposals_ignored",
                          ignored_facts=ignored_writes)
            if repaired_decision.action == "respond":
                repaired, repair_reason = check_answer(
                    repaired_decision.response, state.get("tool_calls", []), state["safe_text"])
                log_event(state, "verify", "repair_result", accepted=repair_reason is None,
                          **({"reason": repair_reason} if repair_reason else {}))
                if repair_reason is None:
                    return {"agent_text": repaired}
            else:
                log_event(state, "verify", "repair_result", accepted=False,
                          reason="repair_requested_tool")
        except ValueError as exc:
            log_invalid_model_output(state, model_reply.content if model_reply else None, exc,
                                     getattr(model_reply, "response_metadata", None), step="verify")
            log_event(state, "verify", "repair_failed", level=logging.WARNING,
                      error_type=type(exc).__name__)
        except Exception as exc:
            log_event(state, "verify", "repair_failed", level=logging.WARNING,
                      error_type=type(exc).__name__)
        safe_reply = _safe_catalog_reply(state)
        if safe_reply:
            checked, safe_reason = check_answer(safe_reply, state.get("tool_calls", []),
                                                state["safe_text"])
            if safe_reason is None:
                log_event(state, "verify", "safe_catalog_reply")
                return {"agent_text": checked}
        log_event(state, "verify", "fallback", reason="guardrail_rejected")
        return {"agent_text": FALLBACK}

    @trace_node("persist")
    async def persist(self, state: TurnState) -> dict[str, Any]:
        request = state["request"]
        try:
            result = await self.memory.record_turn(
                str(request.session_id), state.get("customer_id"),
                state["safe_text"], state["agent_text"], request.on.isoformat(),
                request.channel, client_msg_id=str(request.client_msg_id),
            )
        except Exception as exc:
            log_event(state, "persist", "failed", level=logging.ERROR,
                      error_type=type(exc).__name__)
            raise RuntimeError("memory_turn_write_failed") from exc
        if (not isinstance(result, dict) or type(result.get("turn_no")) is not int
                or result["turn_no"] < 1):
            log_event(state, "persist", "failed", level=logging.ERROR,
                      error_type="InvalidMemoryWriteResult")
            raise RuntimeError("memory_turn_write_failed")
        log_event(state, "persist", "memory_recorded", turn_no=result["turn_no"])
        return {"memory_writes": []}
