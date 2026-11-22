
from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from pydantic import ValidationError

from app.mcp_servers.mcp_catalog.schemas import (
    AttributeFilters, CRMInput, DetailsInput, InventoryInput, QuoteInput, SearchInput, OrderQuoteInput, QuoteLine,
)
from app.mcp_servers.mcp_catalog.services import catalog as service
from app.mcp_servers.mcp_shared.identity import verify_identity
from app.mcp_servers.mcp_shared.observability import (
    log_mcp_exception, log_mcp_validation, trace_mcp_call,
)


async def invoke(repo, name: str, args: dict, *, context_secret=None) -> dict:
    return await trace_mcp_call("catalog", name, args, lambda: _invoke(repo, name, args, context_secret))


async def _invoke(repo, name: str, args: dict, context_secret=None) -> dict:
    models = {"crm.get_customer": CRMInput, "catalog.search": SearchInput,
              'catalog.get_details': DetailsInput,
              "inventory.check": InventoryInput, "pricing.get_quote": QuoteInput,
              "pricing.quote_order": OrderQuoteInput}
    functions = {"crm.get_customer": service.get_customer, "catalog.search": service.search,
                 'catalog.get_details': service.get_details,
                 "inventory.check": service.inventory, "pricing.get_quote": service.get_quote,
                 "pricing.quote_order": service.get_quote_order}
    if name not in models:
        return {"error": "unknown_tool"}
    try:
        payload = models[name].model_validate(args).model_dump(mode="json", exclude_none=True)
    except ValidationError as exc:
        log_mcp_validation("catalog", name, exc)
        return {"error": "invalid_args"}
    try:
        identity_args = {}
        if name in {'pricing.get_quote', 'pricing.quote_order'} and payload.get('trusted_identity'):
            identity_args['verified_customer_id'] = verify_identity(name, payload, context_secret)
        async with repo.transaction() as session:
            return await functions[name](repo, session, payload, **identity_args)
    except PermissionError:
        return {'error': 'identity_changed'}
    except Exception as exc:
        log_mcp_exception("catalog", name, exc)
        return {"error": "tool_unavailable"}


def create_server(repo, token: str | None = None, *, context_secret=None) -> FastMCP:
    secret = context_secret or token
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
                             include_discontinued: bool = False,
                             attribute_filters: AttributeFilters | None = None) -> dict:
        return await invoke(repo, "catalog.search", locals())

    @mcp.tool(name="inventory.check")
    async def inventory_check(sku: str, on: str) -> dict:
        return await invoke(repo, "inventory.check", locals())

    @mcp.tool(name='catalog.get_details')
    async def catalog_get_details(sku: str) -> dict:
        return await invoke(repo, 'catalog.get_details', locals())

    @mcp.tool(name="pricing.get_quote")
    async def pricing_get_quote(sku: str, on: str, qty: int = 1,
                                customer_phone: str | None = None, address: str | None = None,
                                basket_skus: list[str] | None = None,
                                source_channel: str | None = None,
                                source_identity: str | None = None,
                                trusted_identity: str | None = None) -> dict:
        return await invoke(repo, "pricing.get_quote", locals(), context_secret=secret)

    @mcp.tool(name="pricing.quote_order")
    async def pricing_quote_order(lines: list[QuoteLine], on: str,
                                  customer_phone: str | None = None, address: str | None = None,
                                  source_channel: str | None = None,
                                  source_identity: str | None = None,
                                  trusted_identity: str | None = None) -> dict:
        return await invoke(repo, "pricing.quote_order", {
            **locals(), 'lines': [line.model_dump() for line in lines]}, context_secret=secret)

    return mcp
