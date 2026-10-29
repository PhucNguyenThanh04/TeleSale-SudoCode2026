"""Acceptance and context nodes shared by the production one-turn graph."""

import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel

from app.agent.harness.context import load_context
from app.agent.guardrails.checks import mask_pii
from app.agent.memory.fact_candidates import customer_slot_cues
from app.agent.memory.store import MemoryStore
from app.agent.harness.observability import log_event, trace_node
from app.agent.harness.state import TurnState
from app.agent.mcp.gateway import ToolGateway


def safe_catalog_reply(state: TurnState) -> str | None:
    """Recover a restrained product reply from current-turn catalog and quotes."""
    calls = [call for call in state.get("tool_calls", []) if call["name"] != "crm.get_customer"]
    searches = [call for call in calls if call["name"] == "catalog.search"
                and "error" not in call.get("result", {})]
    if not searches:
        return None
    last = searches[-1]
    args = last.get("args", {})
    if (not re.search(r"(?i)\b(?:tư vấn|gợi ý|phù hợp)\b", state["safe_text"])
            and not any(type(args.get(key)) is int
                        for key in ("min_room_area_m2", "max_price_vnd"))):
        return None
    result = last.get("result", {})
    if "error" in result or not isinstance(result.get("items"), list):
        return None
    items = [item for item in result["items"]
             if isinstance(item, dict) and isinstance(item.get("sku"), str)
             and isinstance(item.get("name"), str) and item["name"].strip()]
    names = [item["name"] for item in items[:3]]
    if not names:
        return None
    quotes = {call.get("args", {}).get("sku"): call.get("result", {}) for call in calls
              if call.get("name") == "pricing.get_quote"
              and "error" not in call.get("result", {})}
    budget = args.get("max_price_vnd")
    eligible = [item for item in items
                if (quote := quotes.get(item["sku"]))
                and quote.get("sku", item["sku"]) == item["sku"]
                and type(quote.get("final_price_vnd")) is int
                and (type(budget) is not int or quote["final_price_vnd"] <= budget)]
    wants_child_safety = "has_children" in customer_slot_cues(state["safe_text"])
    if eligible:
        if wants_child_safety:
            eligible.sort(key=lambda item: item.get("attributes", {}).get("child_safe_lock") is not True)
        item = eligible[0]
        quote = quotes[item["sku"]]
        price = f"{quote['final_price_vnd']:,}".replace(",", ".")
        answer = f"Dạ, {item['name']} có giá cuối {price}đ theo ngày cuộc gọi"
        area = args.get("min_room_area_m2")
        if (type(area) is int and type(item.get("attributes", {}).get("room_area_m2")) in
                (int, float) and item["attributes"]["room_area_m2"] >= area):
            answer += f", đáp ứng phòng {area} m²"
        answer += "."
        lock = item.get("attributes", {}).get("child_safe_lock")
        if wants_child_safety and type(lock) is bool:
            answer += (f" {item['name']} có khóa trẻ em."
                       if lock else f" {item['name']} không có khóa trẻ em.")
        answer += (" Chị muốn em kiểm tra tồn kho mẫu này không ạ?"
                   if not wants_child_safety or lock is True else
                   " Nếu cần khóa trẻ em, chị có thể cân nhắc nâng ngân sách không ạ?")
        return mask_pii(answer)
    if type(args.get("min_room_area_m2")) is int:
        question = "Chị ưu tiên tính năng nào thêm để em chọn mẫu sát nhu cầu hơn ạ?"
    else:
        question = "Chị cho em biết diện tích phòng để em tư vấn mẫu phù hợp hơn ạ?"
    return mask_pii("Dạ, em tìm thấy " + ", ".join(names) + ". " + question)


def safe_promotion_reply(state: TurnState) -> str | None:
    """Describe only promotions applied by a current-turn quote for one SKU."""
    if not re.search(r"(?i)\b(?:khuyến mãi|ưu đãi|giảm giá|tặng kèm)\b",
                     state.get("safe_text", "")):
        return None
    calls = state.get("tool_calls", [])
    quotes = [call for call in calls if call.get("name") == "pricing.get_quote"
              and isinstance(call.get("result"), dict)
              and "error" not in call["result"]
              and isinstance(call.get("args", {}).get("sku"), str)
              and call["result"].get("sku") == call["args"]["sku"]]
    if len({call["args"]["sku"] for call in quotes}) != 1:
        return None
    quote = quotes[-1]["result"]
    sku = quotes[-1]["args"]["sku"]
    items = [item for call in calls if call.get("name") == "catalog.search"
             for item in call.get("result", {}).get("items", [])
             if isinstance(item, dict) and isinstance(item.get("sku"), str)
             and isinstance(item.get("name"), str)]
    product = next((item for item in reversed(items) if item["sku"] == sku), None)
    if not product:
        return None
    names = {item["sku"]: item["name"] for item in items}
    offers = []
    for promo in quote.get("applied_promos", []):
        if not isinstance(promo, dict):
            continue
        gift = promo.get("gift_sku")
        discount = promo.get("discount_vnd")
        if promo.get("type") == "gift" and isinstance(gift, str):
            if gift in names:
                offers.append(f"tặng 1 {names[gift]}")
            elif isinstance(promo.get("promo_code"), str):
                offers.append(f"tặng quà kèm theo chương trình {promo['promo_code']}")
        elif type(discount) is int and discount > 0:
            amount = f"{discount:,}".replace(",", ".")
            offers.append(f"giảm {amount}đ")
    if not offers:
        return None
    return mask_pii(
        f"Dạ, khuyến mãi đang áp dụng cho {product['name']} theo ngày cuộc gọi là "
        + ", ".join(offers) + " ạ."
    )


class SessionNodes:
    def __init__(self, llm: BaseChatModel, tools: ToolGateway, memory: MemoryStore,
                 max_tool_calls: int, prompt_history_turns: int,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.max_tool_calls = max_tool_calls
        self.prompt_history_turns = prompt_history_turns
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @trace_node("accept")
    async def accept(self, state: TurnState) -> dict[str, Any]:
        return {
            "safe_text": mask_pii(state["request"].text),
            "received_at_monotonic": state.get("received_at_monotonic", time.perf_counter()),
            "tool_calls": state.get("tool_calls", []), "tool_count": 0,
            "tool_failed": False,
            "needs_handoff": False, "handoff_ticket_id": None,
        }

    @trace_node("retrieve_context")
    async def retrieve_context(self, state: TurnState) -> dict[str, Any]:
        result = await load_context(state, self.memory, self.tools, self.clock)
        log_event(state, "retrieve_context", "context_loaded",
                  history_turns=len(result.get("history", [])),
                  profile_facts=len(result.get("profile", {})),
                  episodes=len(result.get("episodes", [])),
                  call_brief=bool(result.get("call_brief")),
                  success=not result.get("tool_failed", False))
        return result
