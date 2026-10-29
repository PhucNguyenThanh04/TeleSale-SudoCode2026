"""Focused retrieval tests without MCP/server dependencies."""

import unittest

from app.rag.policy_retrieval import fuse, lexical_rank, retrieve


class PolicyRankingTest(unittest.TestCase):
    def test_fusion_recovers_paraphrase_and_preserves_shared_evidence(self):
        lexical = [("VC-01", 2), ("DT-03", 1)]
        dense = [("DT-03", 0.8), ("FAQ-02", 0.7)]
        self.assertEqual(fuse(lexical, dense)[0], "DT-03")

    def test_lexical_control_does_not_match_unrelated_subject(self):
        rows = [{"chunk_id": "DT-03", "title": "Đổi kích cỡ",
                 "body": "Lần đầu miễn phí"}]
        self.assertEqual(lexical_rank("Có trả góp không?", rows), [])
        self.assertEqual(lexical_rank("Giày chật, muốn lên size có tốn tiền không?", rows), [])


class PolicyRetrievalTest(unittest.IsolatedAsyncioTestCase):
    async def test_dense_paraphrase_cannot_return_unapproved_or_stale_chunks(self):
        rows = [{"chunk_id": "DT-03", "title": "Đổi kích cỡ",
                 "body": "Lần đầu miễn phí", "source_hash": "current"}]
        def search(*_args, **_kwargs):
            return [("DT-03", 0.8, "current"), ("NB-01", 0.99, "private"),
                    ("DT-03", 0.95, "obsolete")]
        result = await retrieve("Giày chật, muốn lên size có tốn tiền không?", rows,
                                dense_enabled=True, dense_search=search)
        self.assertEqual(result["retrieval_status"], "hybrid")
        self.assertEqual([row["chunk_id"] for row in result["chunks"]], ["DT-03"])

    async def test_failure_keeps_lexical_evidence_and_reports_degraded(self):
        rows = [{"chunk_id": "VC-01", "title": "Giao hàng",
                 "body": "Nội thành trong 2 ngày", "source_hash": "current"}]
        def broken(*_args, **_kwargs):
            raise TimeoutError("unavailable")
        result = await retrieve("Giao hàng mấy ngày?", rows,
                                dense_enabled=True, dense_search=broken)
        self.assertEqual(result["retrieval_status"], "degraded_lexical")
        self.assertEqual([row["chunk_id"] for row in result["chunks"]], ["VC-01"])

    async def test_unrelated_lexical_question_does_not_create_evidence(self):
        rows = [{"chunk_id": "DT-03", "title": "Đổi kích cỡ",
                 "body": "Lần đầu miễn phí", "source_hash": "current"}]
        result = await retrieve("Có trả góp không?", rows, dense_enabled=False)
        self.assertEqual(result["chunks"], [])


if __name__ == "__main__":
    unittest.main()
