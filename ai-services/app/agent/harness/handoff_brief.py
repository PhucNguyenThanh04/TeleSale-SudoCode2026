"""Construct human handoff evidence from trusted turn state."""

import re
from datetime import datetime
from typing import Callable

from pydantic import ValidationError

from app.agent.guardrails.checks import customer_erasure_requested, mask_pii
from app.agent.harness.context import _open_episode_items
from app.agent.harness.state import TurnState
from app.agent.memory.episode_candidates import accepted_episode_delta
from app.constants import Slot
from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta
from app.schemas.brief import HandoffBrief


_PHONE = re.compile(r"^0[0-9]{9}$")
_REASONS = {"cau_hoi_y_te", "ngoai_pham_vi_tai_lieu", "khach_yeu_cau_gap_nguoi",
            "khieu_nai_nghiem_trong", "loi_he_thong", "khach_mat_kien_nhan", "khac"}
_NEXT = {
    "cau_hoi_y_te": "Nhân viên có chuyên môn trả lời câu hỏi y tế của khách.",
    "ngoai_pham_vi_tai_lieu": "Nhân viên xác minh thông tin ngoài tài liệu rồi phản hồi khách.",
    "khach_yeu_cau_gap_nguoi": "Nhân viên tiếp nhận và tiếp tục tư vấn theo yêu cầu của khách.",
    "khieu_nai_nghiem_trong": "Nhân viên tiếp nhận khiếu nại và xác minh hướng xử lý.",
    "loi_he_thong": "Nhân viên kiểm tra lỗi hệ thống và phản hồi khách.",
    "khach_mat_kien_nhan": "Nhân viên ưu tiên tiếp nhận và giải quyết vướng mắc của khách.",
    "khac": "Nhân viên xem câu hỏi còn mở và tiếp tục xử lý cho khách.",
}


def _trusted_phone(state: TurnState) -> str | None:
    phone = state.get("customer_phone")
    if state.get("identity_status") == "known" and isinstance(phone, str) and _PHONE.fullmatch(phone):
        return phone
    request = state["request"]
    if request.channel == "hotline" and isinstance(request.channel_identity, str):
        phone = request.channel_identity
        if _PHONE.fullmatch(phone):
            return phone
    return None


def _fact_value(facts: dict, key: str):
    fact = facts.get(key)
    return fact.get("value") if isinstance(fact, dict) else None


def build_handoff_brief(state: TurnState, proposal: dict,
                        clock: Callable[[], datetime]) -> HandoffBrief | None:
    phone = _trusted_phone(state)
    if not phone:
        return None
    reason = proposal.get("escalation_reason")
    if reason not in _REASONS:
        reason = "khac"
    text = mask_pii(state.get("safe_text") or state["request"].text).strip()
    if not text:
        return None
    scoped = state.get("scoped_facts") or {}
    products = scoped.get("product", {}) if isinstance(scoped, dict) else {}
    products = products if isinstance(products, dict) else {}
    current_quotes = {}
    for call in state.get("tool_calls", []):
        if call.get("name") != "pricing.get_quote":
            continue
        args, result = call.get("args", {}), call.get("result", {})
        sku = args.get("sku") if isinstance(args, dict) else None
        if (isinstance(sku, str) and isinstance(result, dict)
                and args.get("on") == state["request"].on.isoformat()
                and result.get("sku", sku) == sku
                and type(result.get("final_price_vnd")) is int
                and result["final_price_vnd"] >= 0 and "error" not in result):
            current_quotes[sku] = result["final_price_vnd"]
    candidates = list(dict.fromkeys([*products, *current_quotes]))
    mentioned = [sku for sku in candidates if isinstance(sku, str)
                 and sku.casefold() in text.casefold()]
    selected = (mentioned[0] if len(mentioned) == 1 else
                candidates[0] if not mentioned and len(candidates) == 1 else None)
    if not selected:
        advised = _fact_value(state.get("profile", {}), Slot.PRODUCT_ADVISED)
        if isinstance(advised, str) and not products:
            selected = advised
    price = current_quotes.get(selected)
    if selected:
        if price is None:
            value = _fact_value(products.get(selected, {}), Slot.PRICE_QUOTED_VND)
            if type(value) is int and value >= 0:
                price = value
    known_products = ", ".join(str(sku) for sku in candidates[:4])
    summary = f"Khách hỏi: {text[:430]}. Chuyển nhân viên để tiếp tục xử lý."
    if known_products:
        summary += f" Sản phẩm đã trao đổi trước đây: {known_products}."
    if selected and price is not None:
        summary += (f" Giá công cụ báo ngày {state['request'].on.isoformat()} cho {selected}: {price} VND."
                    if selected in current_quotes else
                    f" Giá từng báo cho {selected}: {price} VND; cần kiểm lại giá hiện tại.")
    summary = summary[:800]
    question = text[:300] if ("?" in text or reason in {
        "cau_hoi_y_te", "ngoai_pham_vi_tai_lieu", "khac"}) else None
    open_questions = [question] if question else []
    current_episode = state.get("current_episode") or {}
    prior_episodes = state.get("episodes", [])
    provisional = accepted_episode_delta(text, "", proposal.get("episode_delta"),
        current_episode, state.get("tool_calls", []), prior_episodes=prior_episodes)
    if provisional:
        prior_open = {item["item_id"]: (topic.get("scope_type"), topic.get("scope_id"))
            for episode in prior_episodes for topic in episode.get("topics", [])
            for item in topic.get("items", [])
            if isinstance(item, dict) and item.get("status") == "open"
            and isinstance(item.get("item_id"), str)}
        try:
            current_episode = apply_episode_delta(current_episode, provisional,
                source_turn_id=str(state["request"].client_msg_id),
                customer_text=text, agent_text="", prior_open_items=prior_open)
            state["handoff_episode_delta"] = provisional
        except ValueError:
            pass
    for item in _open_episode_items([current_episode, *prior_episodes], "question"):
        if item not in open_questions:
            open_questions.append(item)
    next_action = _NEXT[reason]
    if customer_erasure_requested(text):
        summary = ("Khách yêu cầu xử lý dữ liệu cá nhân đã lưu. "
                   "Chưa có thao tác xóa; cần xác minh chủ thể và phạm vi.")
        open_questions = ["Xác minh chủ thể và phạm vi dữ liệu cần xử lý."]
        next_action = "Xác minh chủ thể và chuyển yêu cầu cho bộ phận có thẩm quyền."
    profile = state.get("profile") or {}
    confirmed = {key: fact["value"] for key, fact in profile.items()
                 if isinstance(fact, dict) and "value" in fact
                 and isinstance(fact["value"], (str, int, float, bool))
                 and mask_pii(str(fact["value"])) == str(fact["value"])}
    confirmed = dict(list(confirmed.items())[:10])
    rooms = scoped.get("room", {}) if isinstance(scoped, dict) else {}
    if isinstance(rooms, dict):
        safe_rooms = {room: {key: fact["value"] for key, fact in facts.items()
            if isinstance(fact, dict) and type(fact.get("value")) in {str, int, float, bool}
            and mask_pii(str(fact["value"])) == str(fact["value"])}
            for room, facts in list(rooms.items())[:4]
            if isinstance(room, str) and mask_pii(room) == room and isinstance(facts, dict)}
        if safe_rooms:
            confirmed["rooms"] = safe_rooms
    safe_products = {sku: {key: {field: fact[field] for field in ("value", "on", "source_kind")
            if field in fact and fact[field] is not None}
            for key, fact in facts.items() if isinstance(fact, dict)
            and type(fact.get("value")) in {str, int, float, bool}
            and mask_pii(str(fact["value"])) == str(fact["value"])}
            for sku, facts in list(products.items())[:4]
            if isinstance(sku, str) and mask_pii(sku) == sku and isinstance(facts, dict)}
    if safe_products:
        confirmed["products"] = safe_products
    try:
        return HandoffBrief.model_validate({
            "customer_phone": phone,
            "customer_name": state.get("customer_name") if state.get("identity_status") == "known" else None,
            "customer_id": state.get("customer_id") if state.get("identity_status") == "known" else None,
            "channel": state["request"].channel,
            "escalation_reason": reason,
            "escalation_reason_detail": text[:300],
            "conversation_summary": summary,
            "product_advised": selected,
            "price_quoted_vnd": price,
            "open_questions": open_questions[:10],
            "next_action": next_action,
            "generated_at": clock(),
            "facts_confirmed": confirmed,
            "history_refs": [str(item["session_id"]) for item in state.get("episodes", [])[:5]
                             if isinstance(item, dict) and item.get("session_id")],
        })
    except ValidationError:
        return None
