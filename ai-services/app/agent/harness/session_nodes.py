"""Identity and context nodes shared by the production one-turn graph."""

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel

from app.agent.harness.context import load_context
from app.agent.guardrails.checks import mask_pii
from app.agent.memory.store import MemoryStore
from app.agent.harness.observability import log_event, log_tool_input, log_tool_output, trace_node
from app.agent.harness.state import TurnState
from app.agent.mcp.gateway import ToolGateway


def safe_catalog_reply(state: TurnState) -> str | None:
    """Use catalog names if a product-advice draft cannot be verified."""
    if not re.search(r"(?i)\b(?:tư vấn|gợi ý|phù hợp)\b", state["safe_text"]):
        return None
    calls = [call for call in state.get("tool_calls", []) if call["name"] != "crm.get_customer"]
    if not calls or calls[-1]["name"] != "catalog.search":
        return None
    result = calls[-1].get("result", {})
    if "error" in result or not isinstance(result.get("items"), list):
        return None
    names = [item["name"] for item in result["items"]
             if isinstance(item, dict) and isinstance(item.get("name"), str)
             and item["name"].strip()][:3]
    if not names:
        return None
    question = ("Chị muốn tìm hiểu mẫu nào kỹ hơn ạ?"
                if re.search(r"(?i)\b\d+\s*(?:m2|m²|mét vuông)\b", state["safe_text"])
                else "Chị cho em biết diện tích phòng để em tư vấn mẫu phù hợp hơn ạ?")
    return mask_pii("Dạ, em tìm thấy " + ", ".join(names) + ". " + question)


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
            "received_at_monotonic": time.perf_counter(),
            "tool_calls": [], "tool_count": 0, "tool_failed": False,
            "needs_handoff": False, "handoff_ticket_id": None,
        }

    @trace_node("resolve_identity")
    async def resolve_identity(self, state: TurnState) -> dict[str, Any]:
        request = state["request"]
        key = {"hotline": "phone", "chat_fanpage": "fb_id",
               "zalo_oa": "zalo_id"}.get(request.channel)
        if not key or not request.channel_identity:
            log_event(state, "resolve_identity", "identity_resolved", status="unknown",
                      lookup="skipped")
            return {"identity_status": "unknown", "customer_id": None,
                    "customer_phone": None, "customer_name": None,
                    "honorific": None, "crm_sessions": [], "owned_order_ids": []}
        args = {key: request.channel_identity}
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
                    "honorific": None, "crm_sessions": [], "owned_order_ids": [],
                    "tool_calls": calls}
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
                "honorific": None, "crm_sessions": [], "owned_order_ids": [],
                "tool_calls": calls}

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
