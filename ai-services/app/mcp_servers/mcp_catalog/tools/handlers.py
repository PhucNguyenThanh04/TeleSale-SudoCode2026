"""Thin FastMCP catalog handlers: validation, service call, safe errors."""

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from pydantic import ValidationError

from app.mcp_servers.mcp_catalog.schemas import (
    CRMInput, InventoryInput, PolicySearchInput, QuoteInput, SearchInput,
)
from app.mcp_servers.mcp_catalog.services import catalog as service
from app.mcp_servers.mcp_shared.observability import (
    log_mcp_exception, log_mcp_validation, trace_mcp_call,
)


async def invoke(repo, name: str, args: dict) -> dict:
    return await trace_mcp_call("catalog", name, args, lambda: _invoke(repo, name, args))


async def _invoke(repo, name: str, args: dict) -> dict:
    models = {"crm.get_customer": CRMInput, "catalog.search": SearchInput,
              "inventory.check": InventoryInput, "pricing.get_quote": QuoteInput,
              "policy.search": PolicySearchInput}
    functions = {"crm.get_customer": service.get_customer, "catalog.search": service.search,
                 "inventory.check": service.inventory, "pricing.get_quote": service.get_quote,
                 "policy.search": service.search_policy}
    if name not in models:
        return {"error": "unknown_tool"}
    try:
        payload = models[name].model_validate(args).model_dump(mode="json", exclude_none=True)
    except ValidationError as exc:
        log_mcp_validation("catalog", name, exc)
        return {"error": "invalid_args"}
    try:
        async with repo.transaction() as session:
            return await functions[name](repo, session, payload)
    except Exception as exc:
        log_mcp_exception("catalog", name, exc)
        return {"error": "tool_unavailable"}


def create_server(repo, token: str | None = None) -> FastMCP:
    auth = StaticTokenVerifier({token: {"client_id": "harness", "scopes": ["tools"]}}) if token else None
    mcp = FastMCP("telesale-catalog", auth=auth)

    @mcp.tool(name="eval.database_identity")
    async def eval_database_identity() -> dict:
        return await repo.database_identity()

    @mcp.tool(name="crm.get_customer")
    async def crm_get_customer(phone: str | None = None, zalo_id: str | None = None,
                               fb_id: str | None = None) -> dict:
        return await invoke(repo, "crm.get_customer", locals())

    @mcp.tool(name="catalog.search")
    async def catalog_search(query: str | None = None, category: str | None = None,
                             sku: str | None = None, max_price_vnd: int | None = None,
                             min_room_area_m2: float | None = None,
                             include_discontinued: bool = False) -> dict:
        return await invoke(repo, "catalog.search", locals())

    @mcp.tool(name="inventory.check")
    async def inventory_check(sku: str, on: str) -> dict:
        return await invoke(repo, "inventory.check", locals())

    @mcp.tool(name="pricing.get_quote")
    async def pricing_get_quote(sku: str, on: str, qty: int = 1,
                                customer_phone: str | None = None, address: str | None = None,
                                basket_skus: list[str] | None = None,
                                source_channel: str | None = None,
                                source_identity: str | None = None) -> dict:
        return await invoke(repo, "pricing.get_quote", locals())

    @mcp.tool(name="policy.search")
    async def policy_search(query: str, on: str,
                            order_date: str | None = None) -> dict:
        return await invoke(repo, "policy.search", locals())

    return mcp
