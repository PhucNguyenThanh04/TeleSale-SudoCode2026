"""Single MCP tool boundary with an injectable protocol."""
from app.knowledge.config import enabled, pinned_release

import asyncio
from app.knowledge.context import selected_release, BASE_ONLY
from typing import Any, Protocol

from fastmcp import Client


class ToolGateway(Protocol):
    async def invoke(self, name: str, args: dict[str, Any]) -> dict[str, Any]: ...


class MCPGateway:
    def __init__(self, catalog: Any, order: Any, memory: Any,
                 token: str | None = None, *, knowledge: Any = None,
                 context_secret: str | None = None) -> None:
        self.transports = {"catalog": catalog, "order": order, "memory": memory}
        self.token = token
        self.transports["knowledge"] = knowledge
        self.context_secret = context_secret or token

    async def database_identity(self, service: str) -> dict[str, Any]:
        """Read the database actually reached by one configured MCP endpoint."""
        if service not in self.transports:
            return {"error": "unknown_service"}
        try:
            async with asyncio.timeout(10):
                async with Client(self.transports[service], auth=self.token) as client:
                    response = await client.call_tool("eval.database_identity", {})
            if response.is_error:
                return {"error": "mcp_tool_error"}
            result = response.data if isinstance(response.data, dict) else response.structured_content
            if not isinstance(result, dict) or "error" in result:
                return {"error": "invalid_tool_result"}
            return {key: result.get(key) for key in
                    ("database", "host", "port", "server_started_at")}
        except Exception:
            return {"error": "mcp_unavailable"}

    async def knowledge_release(self) -> dict:
        pinned = pinned_release()
        if not self.transports.get("knowledge"):
            return {"release_id": BASE_ONLY, "manifest_hash": BASE_ONLY}
        async with Client(self.transports["knowledge"], auth=self.token) as client:
            response = await client.call_tool("eval.knowledge_release", {"release_id": pinned})
        result = response.data if isinstance(response.data, dict) else response.structured_content
        if response.is_error or not isinstance(result, dict) or "error" in result:
            raise RuntimeError("Knowledge release cannot be pinned")
        return result

    async def invoke(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        key = args.get("operation_key") if name == "memory.write" else None
        return await self.invoke_trusted(name, args, None, operation_key=key)

    async def invoke_trusted(self, name: str, args: dict[str, Any],
                             customer_id: str | None,
                             channel: str | None = None,
                             channel_identity: str | None = None,
                             operation_key: str | None = None,
                             policy_context: Any = None) -> dict[str, Any]:
        if name == "policy.search":
            return await self._policy_search(args, policy_context)
        group = "memory" if name.startswith("memory.") else (
            "catalog" if name in {"crm.get_customer", "catalog.search", "inventory.check",
                                  "pricing.get_quote", "pricing.quote_order"} else "order")
        if group == "order" and name not in {"order.create", "order.status", "order.update",
                                                "schedule.callback", "handoff.transfer"}:
            return {"error": "unknown_tool"}
        payload = dict(args)
        payload.pop("knowledge_release_id", None)
        payload.pop("verified_customer_id", None)
        payload.pop("source_channel", None)
        payload.pop("source_identity", None)
        payload.pop("operation_key", None)
        if (name in {"pricing.get_quote", "pricing.quote_order", "order.create", "order.status",
                     "order.update", "schedule.callback", "handoff.transfer"}
                and channel and channel_identity):
            payload["source_channel"] = channel
            payload["source_identity"] = channel_identity
        if operation_key and name in {"order.create", "order.update", "schedule.callback",
                                      "handoff.transfer", "memory.write"}:
            payload["operation_key"] = operation_key
        try:
            async with Client(self.transports[group], auth=self.token) as client:
                response = await client.call_tool(name, payload)
            if response.is_error:
                return {"error": "mcp_tool_error"}
            result = response.data if isinstance(response.data, dict) else response.structured_content
            return result if isinstance(result, dict) else {"error": "invalid_tool_result"}
        except Exception:
            return {"error": "mcp_unavailable"}



    async def _policy_search(self, args, context):
        from uuid import uuid4
        from app.mcp_servers.mcp_knowledge.tools.auth import sign_policy_context
        from app.mcp_servers.mcp_knowledge.schemas import PolicySearchInput, TrustedPolicyContext
        transport = self.transports.get('knowledge')
        if not transport or not self.context_secret:
            return {'error':'knowledge_unavailable','retrieval_status':'unavailable','evidence':[]}
        try:
            payload = {key: value for key, value in args.items() if key in {
                'query','on','customer_reported_order_date','top_k'}}
            if context is None:
                context = TrustedPolicyContext(request_id=str(uuid4()),principal='harness',on=payload['on'])
            if context.verified_order_date:
                payload['order_date'] = context.verified_order_date.isoformat()
            request = PolicySearchInput.model_validate(payload)
            context = context.model_copy(update={
                'release_id': selected_release() or pinned_release() or context.release_id,
                'include_supplements': enabled()})
            payload = request.model_dump(mode='json',exclude_none=True)
            payload['trusted_context'] = sign_policy_context(request,context,self.context_secret)
            async with Client(transport,auth=self.token) as client:
                response = await client.call_tool('policy.search',payload)
            result = response.data if isinstance(response.data,dict) else response.structured_content
            return result if isinstance(result,dict) and not response.is_error else {
                'error':'knowledge_unavailable','retrieval_status':'unavailable','evidence':[]}
        except Exception:
            return {'error':'knowledge_unavailable','retrieval_status':'unavailable','evidence':[]}
