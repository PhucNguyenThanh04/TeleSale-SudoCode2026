"""Policy lookup must use dated, public PostgreSQL rows before the agent can quote them."""

import unittest
from datetime import date
from unittest.mock import AsyncMock

from app.agent.guardrails.checks import check_answer
from app.agent.harness.policy import prepare_tool_call
from app.agent.harness.state import Decision
from app.mcp_servers.mcp_catalog.repos.postgres import CatalogRepo
from app.mcp_servers.mcp_catalog.services.catalog import search_policy
from app.rag.policy_retrieval import retrieve
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

    async def test_hybrid_recovers_paraphrase_but_keeps_authorized_source_rows(self):
        chunks = [
            {"chunk_id": "DT-03", "title": "Đổi cỡ", "body": "Miễn phí đổi kích cỡ lần đầu",
             "source_hash": "approved-1"},
            {"chunk_id": "VC-01", "title": "Vận chuyển", "body": "Giao hàng nội thành",
             "source_hash": "approved-2"},
        ]
        def dense_search(query, allowed, **_):
            self.assertIn("DT-03", allowed)
            return [("DT-03", 0.8, "approved-1"), ("NB-01", 0.99, "private")]
        result = await retrieve("Giày chật, muốn lên size có tốn tiền không?", chunks,
                                dense_enabled=True, dense_search=dense_search)
        self.assertEqual(result["retrieval_status"], "hybrid")
        self.assertEqual([c["chunk_id"] for c in result["chunks"]], ["DT-03"])
        self.assertNotIn("retrieval_debug", result)

    async def test_dense_failure_falls_back_to_lexical_without_widening_scope(self):
        chunks = [{"chunk_id": "VC-01", "title": "Giao hàng", "body": "Nội thành 2 ngày",
                   "source_hash": "approved"}]
        def broken_search(*_args, **_kwargs):
            raise TimeoutError("index unavailable")
        result = await retrieve("Giao hàng mấy ngày?", chunks, dense_enabled=True,
                                dense_search=broken_search)
        self.assertEqual(result["retrieval_status"], "degraded_lexical")
        self.assertEqual([c["chunk_id"] for c in result["chunks"]], ["VC-01"])

    async def test_unrelated_question_still_has_no_lexical_evidence(self):
        chunks = [{"chunk_id": "DT-03", "title": "Đổi cỡ", "body": "Miễn phí đổi kích cỡ",
                   "source_hash": "approved"}]
        result = await retrieve("Thanh toán trả góp?", chunks, dense_enabled=False)
        self.assertEqual(result["chunks"], [])

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

    def test_policy_fee_follow_up_uses_verified_policy_without_authorizing_sale_price(self):
        calls = [{"name": "policy.search", "args": {"query": "đổi size", "on": "2026-10-15"},
                  "result": {"chunks": [{"chunk_id": "DT-03", "body":
                      "Từ lần đổi thứ hai, khách chịu phí vận chuyển 30.000đ/chiều."}]}}]
        question = "Nếu đổi size lần thứ hai thì phí thế nào?"
        answer = "Dạ, từ lần thứ hai, phí vận chuyển là 30.000đ mỗi chiều ạ."
        self.assertEqual(check_answer(answer, calls, question), (answer, None))
        self.assertEqual(check_answer(answer, [], question)[1],
                         "unsupported_policy_or_internal_claim")
        self.assertEqual(check_answer("Dạ, phí vận chuyển là 40.000đ/chiều ạ.",
                                      calls, question)[1], "price_without_quote")
        self.assertEqual(check_answer("Dạ, mẫu này giá 30.000đ ạ.", calls, question)[1],
                         "price_without_quote")

    def test_another_policy_fee_wording_and_non_policy_price_control(self):
        calls = [{"name": "policy.search", "args": {"query": "phí vận chuyển", "on": "2026-10-15"},
                  "result": {"chunks": [{"chunk_id": "VC-02", "body":
                      "Các ngành khác: 25.000đ nội thành, 35.000đ liên tỉnh."}]}}]
        answer = "Dạ, phí giao liên tỉnh là 35.000đ ạ."
        self.assertEqual(check_answer(answer, calls, "Chính sách ship liên tỉnh?"),
                         (answer, None))
        self.assertEqual(check_answer("Dạ, mẫu này giá 35.000đ ạ.", calls,
                                      "Chính sách ship liên tỉnh?")[1], "price_without_quote")


if __name__ == "__main__":
    unittest.main()
