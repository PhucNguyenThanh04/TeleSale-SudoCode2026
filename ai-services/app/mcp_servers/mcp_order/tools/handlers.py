
from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from pydantic import StrictInt, ValidationError

from app.configs import get_settings
from app.mcp_servers.mcp_order.schemas import CallbackInput, CreateInput, HandoffInput, StatusInput, UpdateInput, OrderLine, PreviewUpdateInput
from app.mcp_servers.mcp_order.services.order import invoke as service_invoke
from app.mcp_servers.mcp_shared.observability import (
    log_mcp_exception, log_mcp_validation, trace_mcp_call,
)


async def invoke(repo, name: str, args: dict, *, context_secret: str | None = None) -> dict:
    return await trace_mcp_call("order", name, args,
                               lambda: _invoke(repo, name, args, context_secret))


async def _invoke(repo, name: str, args: dict, context_secret: str | None = None) -> dict:
    models = {"order.create": CreateInput, "order.status": StatusInput,
              'order.preview_update': PreviewUpdateInput,
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
                                    timezone_name=get_settings().timezone,
                                    context_secret=context_secret)
    except Exception as exc:
        log_mcp_exception("order", name, exc)
        return {"error": "tool_unavailable"}


def create_server(repo, token: str | None = None, *, context_secret: str | None = None) -> FastMCP:
    secret = context_secret or token
    auth = StaticTokenVerifier({token: {"client_id": "harness", "scopes": ["tools"]}}) if token else None
    mcp = FastMCP("telesale-order", auth=auth)

    @mcp.tool(name="eval.database_identity")
    async def eval_database_identity() -> dict:
        return await repo.database_identity()

    @mcp.tool(name="order.create")
    async def order_create(customer_phone: str, payment: str, on: str,
                           sku: str | None = None, qty: int = 1, price_vnd: int | None = None,
                           lines: list[OrderLine] | None = None, promo_code: str | None = None,
                           address: str | None = None, basket_skus: list[str] | None = None,
                           source_channel: str | None = None, source_identity: str | None = None,
                           operation_key: str | None = None,
                           trusted_authorization: str | None = None) -> dict:
        payload = dict(locals())
        if lines is not None:
            payload['lines'] = [line.model_dump() for line in lines]
        return await invoke(repo, "order.create", payload, context_secret=secret)

    @mcp.tool(name="order.status")
    async def order_status(order_id: str | None = None, customer_phone: str | None = None,
                           source_channel: str | None = None, source_identity: str | None = None,
                           trusted_identity: str | None = None) -> dict:
        return await invoke(repo, "order.status", locals(), context_secret=secret)

    @mcp.tool(name="order.update")
    async def order_update(order_id: str, action: str, on: str,
                           new_variant_sku: str | None = None, reason: str | None = None,
                           line_index: int | None = None, qty: int | None = None,
                           address: str | None = None,
                           source_channel: str | None = None, source_identity: str | None = None,
                           operation_key: str | None = None,
                           trusted_authorization: str | None = None) -> dict:
        return await invoke(repo, "order.update", locals(), context_secret=secret)

    @mcp.tool(name='order.preview_update')
    async def order_preview_update(order_id: str, action: str, on: str,
                                   new_variant_sku: str | None = None, reason: str | None = None,
                                   line_index: StrictInt | None = None, qty: StrictInt | None = None,
                                   source_channel: str | None = None, source_identity: str | None = None,
                                   trusted_identity: str | None = None) -> dict:
        return await invoke(repo, 'order.preview_update', locals(), context_secret=secret)

    @mcp.tool(name="schedule.callback")
    async def schedule_callback(customer_phone: str, callback_at: str, note: str | None = None,
                                requested_callback_at: str | None = None,
                                source_channel: str | None = None, source_identity: str | None = None,
                                operation_key: str | None = None,
                                trusted_authorization: str | None = None) -> dict:
        return await invoke(repo, "schedule.callback", locals(), context_secret=secret)

    @mcp.tool(name="handoff.transfer")
    async def handoff_transfer(brief: dict, source_channel: str | None = None,
                               source_identity: str | None = None,
                               operation_key: str | None = None,
                               trusted_authorization: str | None = None) -> dict:
        return await invoke(repo, "handoff.transfer", locals(), context_secret=secret)

    return mcp
