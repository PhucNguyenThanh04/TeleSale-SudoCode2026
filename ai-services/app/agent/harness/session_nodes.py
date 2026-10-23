"""Acceptance and context nodes shared by the production one-turn graph."""

import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel

from app.agent.harness.context import load_context
from app.agent.guardrails.checks import mask_pii
from app.agent.memory.store import MemoryStore
from app.agent.harness.observability import log_event, trace_node
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
