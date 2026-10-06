"""Persistent agent memory over the MCP memory server."""

from typing import Any, Protocol

from app.agent.tool_gateway import ToolGateway


class MemoryStore(Protocol):
    include_prior: bool

    async def read_context(self, session_id: str, customer_id: str | None) -> dict: ...
    async def record_turn(self, session_id: str, customer_id: str | None,
                          customer_text: str, agent_text: str, on: str, channel: str,
                          outcome: str = "khac", client_msg_id: str | None = None) -> dict: ...
    async def write_fact(self, customer_id: str, session_id: str, key: str, value: Any,
                         op: str, source: str, client_msg_id: str | None = None) -> dict: ...
    async def record_order(self, customer_id: str, session_id: str, order_id: str,
                           client_msg_id: str | None = None) -> dict: ...


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

    async def record_turn(self, session_id: str, customer_id: str | None,
                          customer_text: str, agent_text: str, on: str, channel: str,
                          outcome: str = "khac", client_msg_id: str | None = None) -> dict:
        return await self.gateway.invoke("memory.write", {"action": "turn", "session_id": session_id,
            "customer_id": self._id(customer_id), "data": {"customer_text": customer_text,
            "agent_text": agent_text, "on": on, "channel": channel, "outcome": outcome},
            "operation_key": f"{session_id}:{client_msg_id}:turn" if client_msg_id else None})

    async def write_fact(self, customer_id: str, session_id: str, key: str, value: Any,
                         op: str, source: str, client_msg_id: str | None = None) -> dict:
        return await self.gateway.invoke("memory.write", {"action": "fact",
            "customer_id": self._id(customer_id), "session_id": session_id,
            "data": {"key": key, "value": value, "op": op, "source": source},
            "operation_key": f"{session_id}:{client_msg_id}:fact:{key}" if client_msg_id else None})

    async def record_order(self, customer_id: str, session_id: str, order_id: str,
                           client_msg_id: str | None = None) -> dict:
        return await self.gateway.invoke("memory.write", {"action": "order",
            "customer_id": self._id(customer_id), "session_id": session_id, "data": {"order_id": order_id},
            "operation_key": f"{session_id}:{client_msg_id}:order:{order_id}" if client_msg_id else None})
