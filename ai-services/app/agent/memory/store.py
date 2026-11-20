
from typing import Any, Protocol

from app.agent.mcp.gateway import ToolGateway
from app.mcp_servers.mcp_shared.memory_observations import memory_observations
from app.mcp_servers.mcp_shared.pii import mask_pii
from app.mcp_servers.mcp_memory.schemas import validate_read_response


def safe_observations(calls: list[dict]) -> list[dict]:
    return memory_observations(calls)


def memory_error_code(result: Any) -> str:
    if not isinstance(result, dict):
        return "invalid_tool_result"
    code = result.get("error")
    return code if isinstance(code, str) and code in {
        "mcp_unavailable", "mcp_tool_error", "tool_unavailable", "invalid_args",
        "invalid_tool_result", "session_owner_mismatch", "operation_key_conflict",
        "invalid_turn_data", "invalid_facts_or_identity", "invalid_orders_or_identity",
        "customer_erasure_in_progress", "invalid_scope", "invalid_episode_delta",
        "invalid_outcome", "memory_store_unavailable", "legacy_memory_action_disabled",
    } else "memory_error"


class MemoryStore(Protocol):
    include_prior: bool

    async def read_context(self, session_id: str, customer_id: str | None,
                           *, query: str = "") -> dict: ...

    async def read_turn_status(self, session_id: str, customer_id: str | None,
                               client_msg_id: str) -> dict: ...

    async def read_timeline(self, session_id: str, customer_id: str | None, on: str,
                            *, offset: int = 0, limit: int = 10, crm_sessions=()) -> dict: ...

    async def commit_turn(self, session_id: str, customer_id: str | None,
                          customer_text: str, agent_text: str, on: str, channel: str,
                          client_msg_id: str,
                          orders: list[str] | None = None,
                          outcome: str = "khac",
                          tool_observations: list[dict[str, Any]] | None = None,
                          knowledge_evidence: dict | None = None) -> dict: ...


class MCPMemoryStore:

    supports_tool_observations = True
    supports_knowledge_signals = True
    supports_retrieval_query = True

    def __init__(self, gateway: ToolGateway, namespace: str = "",
                 include_prior: bool = True, max_episodes: int = 5) -> None:
        self.gateway = gateway
        self.namespace = namespace
        self.include_prior = include_prior
        self.max_episodes = max_episodes

    def _id(self, customer_id: str | None) -> str | None:
        return f"{self.namespace}:{customer_id}" if customer_id and self.namespace else customer_id

    async def read_context(self, session_id: str, customer_id: str | None,
                           *, query: str = "") -> dict:
        result = await self.gateway.invoke("memory.read", {"session_id": session_id,
                                                          "customer_id": self._id(customer_id),
                                                          "max_episodes": self.max_episodes,
                                                          "include_prior": self.include_prior,
                                                          "query": mask_pii(query)[:8000]})
        return validate_read_response(self._consume_diagnostics(result, customer_id))

    async def read_turn_status(self, session_id: str, customer_id: str | None,
                               client_msg_id: str) -> dict:
        return await self.gateway.invoke("memory.turn_status", {
            "session_id": session_id, "customer_id": self._id(customer_id),
            "client_msg_id": client_msg_id})

    async def read_timeline(self, session_id: str, customer_id: str | None, on: str,
                            *, offset: int = 0, limit: int = 10, crm_sessions=()) -> dict:
        return await self.gateway.invoke('memory.timeline', {
            'session_id': session_id, 'customer_id': self._id(customer_id), 'on': on,
            'offset': offset, 'limit': limit, 'crm_sessions': list(crm_sessions)})

    async def commit_turn(self, session_id: str, customer_id: str | None,
                          customer_text: str, agent_text: str, on: str, channel: str,
                          client_msg_id: str,
                          orders: list[str] | None = None,
                          outcome: str = "khac",
                          tool_observations: list[dict[str, Any]] | None = None,
                          knowledge_evidence: dict | None = None) -> dict:
        data = {"customer_text": customer_text, "agent_text": agent_text,
                "on": on, "channel": channel, "client_msg_id": client_msg_id,
                "orders": orders or []}
        if knowledge_evidence:
            data["knowledge_evidence"] = knowledge_evidence
        if outcome != "khac":
            data["outcome"] = outcome
        if tool_observations:
            data["tool_observations"] = safe_observations(tool_observations)
        result = await self.gateway.invoke("memory.write", {
            "action": "commit_turn", "session_id": session_id,
            "customer_id": self._id(customer_id),
            "data": data,
            "operation_key": f"{session_id}:{client_msg_id}:commit_turn",
        })

        return self._consume_diagnostics(result, customer_id)

    @staticmethod
    def _consume_diagnostics(result, customer_id):
        if isinstance(result, dict) and "_decision_diagnostics" in result:
            from app.mcp_servers.mcp_shared.decision_diagnostics import ingest
            result = dict(result)
            ingest(result.pop("_decision_diagnostics"), customer_id=customer_id)
        return result
