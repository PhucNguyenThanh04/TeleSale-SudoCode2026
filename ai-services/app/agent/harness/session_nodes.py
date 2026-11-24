import time
from datetime import datetime, timezone
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel

from app.agent.harness.context import load_context
from app.agent.guardrails.checks import mask_pii
from app.mcp_servers.mcp_shared.pii import private_delivery_context
from app.agent.memory.store import MemoryStore
from app.agent.harness.observability import log_event, trace_node
from app.agent.harness.state import TurnState
from app.agent.mcp.gateway import ToolGateway


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
            'private_delivery': private_delivery_context(state['request'].text,
                str(state['request'].client_msg_id), state['request'].on.isoformat()),
            "reply_context": {}, "reply_error": None, 'verified_answer': '',
            "received_at_monotonic": state.get("received_at_monotonic", time.perf_counter()),
            "tool_calls": state.get("tool_calls", []), "tool_count": 0, 'tool_attempts': 0,
            "tool_failed": False,
            "needs_handoff": False, "handoff_ticket_id": None,
        }

    @trace_node("retrieve_context")
    async def retrieve_context(self, state: TurnState) -> dict[str, Any]:
        result = await load_context(state, self.memory, self.tools, self.clock, refresh_brief=True)
        log_event(state, "retrieve_context", "context_loaded",
                  history_turns=len(result.get("history", [])),
                  profile_facts=len(result.get("profile", {})),
                  episodes=len(result.get("episodes", [])),
                  call_brief=bool(result.get("call_brief")),
                  success=not result.get("tool_failed", False))
        return result
