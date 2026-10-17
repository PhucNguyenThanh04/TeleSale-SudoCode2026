"""Single MCP tool boundary with an injectable protocol."""

from typing import Any, Protocol

from fastmcp import Client


class ToolGateway(Protocol):
    async def invoke(self, name: str, args: dict[str, Any]) -> dict[str, Any]: ...


class MCPGateway:
    def __init__(self, catalog: Any, order: Any, memory: Any,
                 token: str | None = None) -> None:
        self.transports = {"catalog": catalog, "order": order, "memory": memory}
        self.token = token

    async def invoke(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        key = args.get("operation_key") if name == "memory.write" else None
        return await self.invoke_trusted(name, args, None, operation_key=key)

    async def invoke_trusted(self, name: str, args: dict[str, Any],
                             customer_id: str | None,
                             channel: str | None = None,
                             channel_identity: str | None = None,
                             operation_key: str | None = None) -> dict[str, Any]:
        group = "memory" if name.startswith("memory.") else (
            "catalog" if name in {"crm.get_customer", "catalog.search", "inventory.check",
                                  "pricing.get_quote", "policy.search"} else "order")
        if group == "order" and name not in {"order.create", "order.status", "order.update",
                                                "schedule.callback", "handoff.transfer"}:
            return {"error": "unknown_tool"}
        payload = dict(args)
        payload.pop("verified_customer_id", None)
        payload.pop("source_channel", None)
        payload.pop("source_identity", None)
        payload.pop("operation_key", None)
        if name in {"pricing.get_quote", "order.create", "order.status",
                    "order.update", "schedule.callback", "handoff.transfer"}:
            if channel and channel_identity:
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


