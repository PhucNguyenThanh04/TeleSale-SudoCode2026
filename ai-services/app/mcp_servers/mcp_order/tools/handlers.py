"""Thin BTC order tool handlers."""

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from pydantic import ValidationError

from app.configs import get_settings
from app.mcp_servers.mcp_order.schemas import CallbackInput, CreateInput, HandoffInput, StatusInput, UpdateInput
from app.mcp_servers.mcp_order.services.order import invoke as service_invoke
from app.mcp_servers.mcp_shared.observability import (
    log_mcp_exception, log_mcp_validation, trace_mcp_call,
)


async def invoke(repo, name: str, args: dict) -> dict:
    return await trace_mcp_call("order", name, args, lambda: _invoke(repo, name, args))


async def _invoke(repo, name: str, args: dict) -> dict:
    models = {"order.create": CreateInput, "order.status": StatusInput,
              "order.update": UpdateInput, "schedule.callback": CallbackInput,
              "handoff.transfer": HandoffInput}
    if name not in models:
        return {"error": "unknown_tool"}
    try:
        payload = models[name].model_validate(args).model_dump(mode="json", exclude_none=True)
    except ValidationError as exc:
        log_mcp_validation("order", name, exc)
        return {"error": "invalid_args"}
    try:
        return await service_invoke(repo, name, payload,
                                    timezone_name=get_settings().timezone)
    except Exception as exc:
        log_mcp_exception("order", name, exc)
        return {"error": "tool_unavailable"}


def create_server(repo, token: str | None = None) -> FastMCP:
    auth = StaticTokenVerifier({token: {"client_id": "harness", "scopes": ["tools"]}}) if token else None
    mcp = FastMCP("telesale-order", auth=auth)

    @mcp.tool(name="order.create")
    async def order_create(customer_phone: str, sku: str, qty: int, price_vnd: int,
                           payment: str, on: str, promo_code: str | None = None,
                           address: str | None = None, basket_skus: list[str] | None = None,
                           source_channel: str | None = None, source_identity: str | None = None,
                           operation_key: str | None = None) -> dict:
        return await invoke(repo, "order.create", locals())

    @mcp.tool(name="order.status")
    async def order_status(order_id: str | None = None, customer_phone: str | None = None,
                           source_channel: str | None = None, source_identity: str | None = None) -> dict:
        return await invoke(repo, "order.status", locals())

    @mcp.tool(name="order.update")
    async def order_update(order_id: str, action: str, on: str,
                           new_variant_sku: str | None = None, reason: str | None = None,
                           source_channel: str | None = None, source_identity: str | None = None,
                           operation_key: str | None = None) -> dict:
        return await invoke(repo, "order.update", locals())

    @mcp.tool(name="schedule.callback")
    async def schedule_callback(customer_phone: str, callback_at: str, note: str | None = None,
                                source_channel: str | None = None, source_identity: str | None = None,
                                operation_key: str | None = None) -> dict:
        return await invoke(repo, "schedule.callback", locals())

    @mcp.tool(name="handoff.transfer")
    async def handoff_transfer(brief: dict, source_channel: str | None = None,
                               source_identity: str | None = None,
                               operation_key: str | None = None) -> dict:
        return await invoke(repo, "handoff.transfer", locals())

    return mcp
