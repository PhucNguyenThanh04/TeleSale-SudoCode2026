"""Persistent agent memory over the MCP memory server."""

from typing import Any, Protocol

from app.agent.mcp.gateway import ToolGateway


def memory_error_code(result: Any) -> str:
    """Keep operational error metadata bounded and free of arbitrary payloads."""
    if not isinstance(result, dict):
        return "invalid_tool_result"
    code = result.get("error")
    return code if isinstance(code, str) and code in {
        "mcp_unavailable", "mcp_tool_error", "tool_unavailable", "invalid_args",
        "invalid_tool_result", "session_owner_mismatch", "operation_key_conflict",
        "invalid_turn_data", "invalid_facts_or_identity", "invalid_orders_or_identity",
        "customer_erasure_in_progress", "invalid_scope", "invalid_episode_delta",
        "invalid_outcome",
    } else "memory_error"


class MemoryStore(Protocol):
    include_prior: bool

    async def read_context(self, session_id: str, customer_id: str | None) -> dict: ...

    async def commit_turn(self, session_id: str, customer_id: str | None,
                          customer_text: str, agent_text: str, on: str, channel: str,
                          client_msg_id: str, facts: list[dict[str, Any]],
                          orders: list[str] | None = None,
                          episode_delta: dict[str, Any] | None = None,
                          outcome: str = "khac") -> dict: ...


class MCPMemoryStore:
    """Async graph memory over memory.read/write, with no process-local facts."""

    def __init__(self, gateway: ToolGateway, namespace: str = "",
                 include_prior: bool = True, max_episodes: int = 5) -> None:
        self.gateway = gateway
        self.namespace = namespace
        self.include_prior = include_prior
        self.max_episodes = max_episodes

    def _id(self, customer_id: str | None) -> str | None:
        return f"{self.namespace}:{customer_id}" if customer_id and self.namespace else customer_id

    async def read_context(self, session_id: str, customer_id: str | None) -> dict:
        return await self.gateway.invoke("memory.read", {"session_id": session_id,
                                                          "customer_id": self._id(customer_id),
                                                          "max_episodes": self.max_episodes,
                                                          "include_prior": self.include_prior})

    async def commit_turn(self, session_id: str, customer_id: str | None,
                          customer_text: str, agent_text: str, on: str, channel: str,
                          client_msg_id: str, facts: list[dict[str, Any]],
                          orders: list[str] | None = None,
                          episode_delta: dict[str, Any] | None = None,
                          outcome: str = "khac") -> dict:
        data = {"customer_text": customer_text, "agent_text": agent_text,
                "on": on, "channel": channel, "client_msg_id": client_msg_id,
                "facts": facts, "orders": orders or []}
        if episode_delta:
            data["episode_delta"] = episode_delta
        if outcome != "khac":
            data["outcome"] = outcome
        return await self.gateway.invoke("memory.write", {
            "action": "commit_turn", "session_id": session_id,
            "customer_id": self._id(customer_id),
            "data": data,
            "operation_key": f"{session_id}:{client_msg_id}:commit_turn",
        })
