"""MCP discovery and trusted context remain BTC-compatible."""

import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from fastmcp import FastMCP
from app.agent.mcp.gateway import MCPGateway
from app.agent.memory.store import MCPMemoryStore
from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
from app.mcp_servers.mcp_memory.tools.handlers import create_server as memory_server
from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server


class FakeRepo:
    @asynccontextmanager
    async def transaction(self):
        yield object()

    async def database_identity(self):
        return {"database": "telesale_eval", "host": "eval-postgres", "port": 5432}


class GatewayTest(unittest.IsolatedAsyncioTestCase):
    async def test_database_identity_uses_each_configured_mcp_server(self):
        repo = FakeRepo()
        gateway = MCPGateway(catalog_server(repo), order_server(repo), memory_server(repo))
        for service in ("catalog", "order", "memory"):
            result = await gateway.database_identity(service)
            self.assertEqual(result, {"database": "telesale_eval",
                                      "host": "eval-postgres", "port": 5432})
        self.assertEqual(await gateway.invoke("eval.database_identity", {}),
                         {"error": "unknown_tool"})

    async def test_old_mcp_without_identity_tool_fails_closed(self):
        gateway = MCPGateway(FastMCP("old-catalog"), None, None)
        result = await gateway.database_identity("catalog")
        self.assertIn(result.get("error"), {"mcp_tool_error", "mcp_unavailable"})

    async def test_identity_response_discards_any_extra_connection_details(self):
        class LeakyRepo(FakeRepo):
            async def database_identity(self):
                return {**await super().database_identity(),
                        "dsn": "postgresql://user:secret@eval-postgres:5432/telesale_eval",
                        "password": "secret"}

        gateway = MCPGateway(catalog_server(LeakyRepo()), None, None)
        result = await gateway.database_identity("catalog")
        self.assertEqual(result, {"database": "telesale_eval", "host": "eval-postgres",
                                  "port": 5432})

    async def test_database_identity_timeout_fails_closed(self):
        class SlowRepo(FakeRepo):
            async def database_identity(self):
                await asyncio.sleep(0.1)
                return await super().database_identity()

        gateway = MCPGateway(catalog_server(SlowRepo()), None, None)
        real_timeout = asyncio.timeout
        with patch("app.agent.mcp.gateway.asyncio.timeout",
                   side_effect=lambda _seconds: real_timeout(0.01)):
            self.assertEqual(await gateway.database_identity("catalog"),
                             {"error": "mcp_unavailable"})

    async def test_commit_turn_uses_memory_mcp_with_evidenced_facts(self):
        gateway = MCPGateway(None, None, memory_server(FakeRepo()))
        memory = MCPMemoryStore(gateway)
        session_id = "22222222-2222-4222-8222-222222222222"
        message_id = "11111111-1111-4111-8111-111111111111"
        with (patch("app.mcp_servers.mcp_memory.tools.handlers.get_settings",
                    return_value=SimpleNamespace(memory_summary_turns=3,
                                                 memory_summary_max_chars=800)),
              patch("app.mcp_servers.mcp_memory.tools.handlers.write",
                    new_callable=AsyncMock) as service):
            service.return_value = {"turn_no": 1, "memory_writes": [
                {"key": "room_area_m2", "value": 25, "op": "set",
                 "source": "turn-1", "customer_id": "C001"}]}
            result = await memory.commit_turn(
                session_id, "C001", "Phòng anh 25 m²", "Dạ, em tư vấn ạ.",
                "2026-10-15", "hotline", message_id,
                [{"key": "room_area_m2", "value": 25, "op": "set",
                  "source_kind": "customer"}])
        self.assertEqual(result["memory_writes"][0]["value"], 25)
        self.assertEqual(service.await_args.kwargs["action"], "commit_turn")
        self.assertEqual(service.await_args.kwargs["operation_key"],
                         f"{session_id}:{message_id}:commit_turn")

    async def test_mcp_failure_returns_unavailable(self):
        gateway = MCPGateway("http://127.0.0.1:1/mcp", None, None)
        with patch("app.agent.mcp.gateway.Client", side_effect=RuntimeError("offline")):
            self.assertEqual(await gateway.invoke("catalog.search", {"query": "máy lọc"}),
                             {"error": "mcp_unavailable"})

    async def test_mcp_catalog_keeps_btc_search_result(self):
        import json
        from pathlib import Path
        products = json.loads((Path(__file__).resolve().parents[3] /
            "BTC-Data-Vong1-TEAMS/catalog/products.json").read_text())["products"]

        class CatalogRepo(FakeRepo):
            async def rows(self, _session, table):
                self_table = table
                if self_table != "products":
                    raise AssertionError(table)
                return products

        repo = CatalogRepo()
        mcp = MCPGateway(catalog_server(repo), None, None)
        args = {"sku": "SKU-AP-X"}
        result = await mcp.invoke("catalog.search", args)
        self.assertEqual(result["items"][0]["sku"], "SKU-AP-X")

    async def test_catalog_and_order_routes_keep_btc_names(self):
        repo = FakeRepo()
        gateway = MCPGateway(catalog_server(repo), order_server(repo), None)
        with patch("app.mcp_servers.mcp_catalog.tools.handlers.service.get_quote", new_callable=AsyncMock) as quote:
            quote.return_value = {"final_price_vnd": 4890000}
            result = await gateway.invoke_trusted("pricing.get_quote", {"sku": "SKU-AP-X",
                "on": "2026-10-15", "verified_customer_id": "C999"},
                "C001", "hotline", "0984726714")
            self.assertEqual(result["final_price_vnd"], 4890000)
            payload = quote.await_args.args[2]
            self.assertNotIn("verified_customer_id", payload)
            self.assertEqual(payload["source_identity"], "0984726714")
        with patch("app.mcp_servers.mcp_order.tools.handlers.service_invoke", new_callable=AsyncMock) as order:
            order.return_value = {"order_id": "OD600001", "status": "created"}
            created = await gateway.invoke_trusted("order.create", {"sku": "SKU-AP-X",
                "on": "2026-10-15", "qty": 1, "price_vnd": 4890000,
                "payment": "COD", "customer_phone": "0984726714"},
                "C001", "hotline", "0984726714", "turn-1")
            self.assertEqual(created["order_id"], "OD600001")
            self.assertEqual(order.await_args.args[2]["operation_key"], "turn-1")

    async def test_crm_routes_to_catalog(self):
        repo = FakeRepo()
        gateway = MCPGateway(catalog_server(repo), order_server(repo), None)
        with patch("app.mcp_servers.mcp_catalog.tools.handlers.service.get_customer", new_callable=AsyncMock) as crm:
            crm.return_value = {"found": False}
            self.assertEqual(await gateway.invoke("crm.get_customer", {"fb_id": "fb.hạnh.274"}),
                             {"found": False})
            self.assertEqual(crm.await_args.args[2]["fb_id"], "fb.hạnh.274")

    async def test_policy_search_routes_to_catalog_without_order_identity(self):
        gateway = MCPGateway(catalog_server(FakeRepo()), None, None)
        with patch("app.mcp_servers.mcp_catalog.tools.handlers.service.search_policy",
                   new_callable=AsyncMock) as policy:
            policy.return_value = {"chunks": []}
            result = await gateway.invoke("policy.search", {
                "query": "đổi trả", "on": "2026-10-15"})
            self.assertEqual(result, {"chunks": []})
            self.assertEqual(policy.await_args.args[2]["on"], "2026-10-15")


if __name__ == "__main__":
    unittest.main()
