"""Policy lookup must use dated, public PostgreSQL rows before the agent can quote them."""

import unittest
from datetime import date
from unittest.mock import AsyncMock

from app.agent.guardrails.checks import check_answer
from app.agent.harness.policy import prepare_tool_call
from app.agent.harness.state import Decision
from app.mcp_servers.mcp_catalog.repos.postgres import CatalogRepo
from app.mcp_servers.mcp_catalog.services.catalog import search_policy
from app.schemas.agent import TextTurnRequest
from uuid import uuid4


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class PolicyLookupTest(unittest.IsolatedAsyncioTestCase):
    async def test_query_filters_access_and_effective_date_before_returning_rows(self):
        session = type("Session", (), {})()
        session.execute = AsyncMock(return_value=_Rows([]))
        repo = object.__new__(CatalogRepo)
        await repo.public_policy_chunks(session, "2026-10-15", "2026-09-20")
        statement, values = session.execute.await_args.args
        sql = str(statement)
        self.assertIn("access_level='public'", sql)
        self.assertIn("effective_from", sql)
        self.assertIn("effective_until", sql)
        self.assertIn("date_basis='order_date'", sql)
        self.assertEqual(values, {"on": date(2026, 10, 15),
                                  "order_date": date(2026, 9, 20)})

    async def test_policy_result_ranks_only_repo_filtered_chunks(self):
        repo = type("Repo", (), {})()
        repo.public_policy_chunks = AsyncMock(return_value=[
            {"chunk_id": "DT-01", "title": "Thời hạn đổi trả",
             "body": "Đổi trả trong 7 ngày", "date_basis": "order_date"},
            {"chunk_id": "FAQ-99", "title": "Chăm sóc sản phẩm",
             "body": "Lau chùi sản phẩm", "date_basis": "call_date"},
        ])
        result = await search_policy(repo, object(), {"query": "đổi trả bao nhiêu ngày",
                                                        "on": "2026-10-15"})
        self.assertEqual([item["chunk_id"] for item in result["chunks"]], ["DT-01"])

    def test_harness_supplies_business_date_and_ignores_model_order_date(self):
        request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
            channel="hotline", channel_identity="0123456789", on=date(2026, 10, 15),
            text="Chính sách đổi trả?", input_mode="clean")
        state = {"request": request, "decision": Decision(action="tool",
            tool_name="policy.search", tool_args={"query": "đổi trả", "order_date": "2020-01-01"}),
            "tool_calls": []}
        self.assertEqual(prepare_tool_call(state, lambda: None),
                         ("policy.search", {"query": "đổi trả", "on": "2026-10-15"}))

    def test_answer_rejects_old_policy_and_accepts_evidenced_current_window(self):
        calls = [{"name": "policy.search", "args": {"query": "đổi trả", "on": "2026-10-15"},
                  "result": {"chunks": [{"chunk_id": "DT-01",
                                          "body": "Đổi trả trong vòng 7 ngày."}]}}]
        self.assertEqual(check_answer("Chính sách đổi trả trong 7 ngày.", calls)[1], None)
        self.assertIsNotNone(check_answer("Chính sách đổi trả trong 14 ngày.", calls)[1])
        self.assertIsNotNone(check_answer("Chính sách đổi trả trong 7 ngày.", [])[1])


if __name__ == "__main__":
    unittest.main()
