"""The three MCP handler boundaries explain calls without exposing customer data."""

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.mcp_servers.mcp_catalog.tools.handlers import invoke as catalog_invoke
from app.mcp_servers.mcp_memory.tools.handlers import invoke as memory_invoke
from app.mcp_servers.mcp_order.tools.handlers import invoke as order_invoke


class FakeRepo:
    @asynccontextmanager
    async def transaction(self):
        yield object()


class MCPLoggingTest(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_logs_search_input_and_result_but_masks_crm(self):
        repo = FakeRepo()
        with patch("app.mcp_servers.mcp_catalog.tools.handlers.service.get_customer",
                   new_callable=AsyncMock) as crm, patch(
                   "app.mcp_servers.mcp_catalog.tools.handlers.service.search",
                   new_callable=AsyncMock) as search:
            crm.return_value = {"found": True, "customer_id": "C001", "name": "Hoa",
                                "phone": "0984726714", "orders": [{"order_id": "OD-1"}]}
            search.return_value = {"items": [{"sku": "SKU-SN-TRK",
                                               "name": "Giày trekking HikePro"}], "total": 1}
            with self.assertLogs("app.mcp.catalog", level="INFO") as captured:
                await catalog_invoke(repo, "crm.get_customer", {"phone": "0984726714"})
                await catalog_invoke(repo, "catalog.search", {"query": "Giày trekking HikePro"})
        logs = "\n".join(captured.output)
        self.assertIn("crm.get_customer nhận vào", logs)
        self.assertIn('"lookup": "phone"', logs)
        self.assertIn('"orders_count": 1', logs)
        self.assertIn('"total": 1', logs)
        self.assertIn("Giày trekking HikePro", logs)
        for secret in ("0984726714", "C001", "Hoa", "OD-1"):
            self.assertNotIn(secret, logs)

    async def test_order_logs_business_fields_and_hides_address_and_ids(self):
        args = {"customer_phone": "0984726714", "sku": "SKU-AP-X", "qty": 1,
                "price_vnd": 4890000, "payment": "COD", "on": "2026-10-15",
                "address": "12 đường Lê Lợi", "operation_key": "secret-operation"}
        with patch("app.mcp_servers.mcp_order.tools.handlers.service_invoke",
                   new_callable=AsyncMock) as service:
            service.return_value = {"order_id": "OD600001", "status": "created",
                                    "total_vnd": 4890000}
            with self.assertLogs("app.mcp.order", level="INFO") as captured:
                await order_invoke(FakeRepo(), "order.create", args)
        logs = "\n".join(captured.output)
        self.assertIn('"price_vnd": 4890000', logs)
        self.assertIn('"address_provided": true', logs)
        self.assertIn('"order_id_created": true', logs)
        for secret in ("0984726714", "Lê Lợi", "secret-operation", "OD600001"):
            self.assertNotIn(secret, logs)

    async def test_order_logs_validation_and_service_error_types(self):
        args = {"customer_phone": "0984726714", "sku": "SKU-AP-X", "qty": 0,
                "price_vnd": 4890000, "payment": "COD", "on": "2026-10-15"}
        with self.assertLogs("app.mcp.order", level="INFO") as captured:
            self.assertEqual((await order_invoke(FakeRepo(), "order.create", args))["error"],
                             "invalid_args")
        logs = "\n".join(captured.output)
        self.assertIn("tham số không hợp lệ", logs)
        self.assertIn('"field": "qty"', logs)
        self.assertNotIn("0984726714", logs)

        with patch("app.mcp_servers.mcp_order.tools.handlers.service_invoke",
                   new_callable=AsyncMock) as service:
            service.side_effect = RuntimeError("postgresql://user:password@localhost/db")
            with self.assertLogs("app.mcp.order", level="INFO") as captured:
                self.assertEqual((await order_invoke(FakeRepo(), "order.create",
                    {**args, "qty": 1}))["error"], "tool_unavailable")
        logs = "\n".join(captured.output)
        self.assertIn("RuntimeError", logs)
        self.assertNotIn("password", logs)

    async def test_memory_logs_counts_and_fact_operation_only(self):
        session_id = "22222222-2222-4222-8222-222222222222"
        with patch("app.mcp_servers.mcp_memory.tools.handlers.read",
                   new_callable=AsyncMock) as read, patch(
                   "app.mcp_servers.mcp_memory.tools.handlers.write",
                   new_callable=AsyncMock) as write:
            read.return_value = {"history": [{"customer": "SĐT 0984726714"}],
                                 "profile": {"budget_vnd": {"value": 4890000}},
                                 "episodes": [], "owned_order_ids": []}
            write.return_value = {"customer_id": "C001", "key": "budget_vnd",
                                  "value": 4890000, "fact_id": session_id, "op": "set"}
            with self.assertLogs("app.mcp.memory", level="INFO") as captured:
                await memory_invoke(FakeRepo(), "memory.read", {
                    "customer_id": "C001", "session_id": session_id})
                await memory_invoke(FakeRepo(), "memory.write", {
                    "action": "fact", "customer_id": "C001", "session_id": session_id,
                    "data": {"key": "budget_vnd", "value": 4890000, "op": "set",
                             "source": "secret"}})
        logs = "\n".join(captured.output)
        self.assertIn('"history_turns": 1', logs)
        self.assertIn('"profile_keys": ["budget_vnd"]', logs)
        self.assertIn('"fact_op": "set"', logs)
        for secret in ("0984726714", "C001", session_id, '"source": "secret"'):
            self.assertNotIn(secret, logs)
