import asyncio
import json
from datetime import date
from unittest.mock import AsyncMock, patch

from eval_harness.run_rag import collect_retrieval, current_policy_chunks, question_order_date
from eval_harness.run_rag import score_current_rag
from eval_harness.test_official_pipeline import BTC, _case
from eval_harness.official_pipeline import publish_pair


def test_collect_retrieval_records_ranked_ids_without_inventing_answers():
    questions = [{"qid": "Q01", "question": "Đổi size?"},
                 {"qid": "Q02", "question": "Không biết?"}]

    async def fake_retrieve(question, chunks):
        return {"chunks": chunks[:1] if question == "Đổi size?" else [],
                "retrieval_status": "lexical_only"}

    rows = asyncio.run(collect_retrieval(questions, [{"chunk_id": "DT-03"}],
                                         retrieve_fn=fake_retrieve))
    assert rows["Q01"]["retrieved_chunk_ids"] == ["DT-03"]
    assert rows["Q02"]["retrieved_chunk_ids"] == []
    assert all("abstained" not in row and "answer" not in row for row in rows.values())


def test_btc_rag_scoring_keeps_answer_abstention_unmeasured(tmp_path):
    scenarios, paths, metadata = _case(tmp_path)
    score = tmp_path / "btc_score.json"
    publish_pair(scenarios, paths["full"], paths["baseline_no_memory"],
                 score, metadata, btc_root=BTC)
    with patch("eval_harness.run_rag.current_policy_chunks",
               new_callable=AsyncMock, return_value=[]):
        summary = asyncio.run(score_current_rag(
            dsn="unused", btc_root=BTC, scenarios=scenarios,
            full_trace=paths["full"], baseline_trace=paths["baseline_no_memory"],
            conversation_score=score, out=tmp_path))
    assert summary["question_count"] == 60
    assert summary["answer_abstention"]["status"] == "not_measured"
    assert "recall@3" in summary["retrieval_metrics"]
    assert all("abstained" not in row for row in
               json.loads((tmp_path / "rag_retrieval.json").read_text()).values())


def test_policy_query_binds_a_real_date_for_asyncpg():
    connection = AsyncMock()
    connection.fetch.return_value = []
    with patch("eval_harness.run_rag.asyncpg.connect", new_callable=AsyncMock,
               return_value=connection):
        asyncio.run(current_policy_chunks("postgresql://unused", "2026-10-15"))
    assert connection.fetch.await_args.args[1] == date(2026, 10, 15)


def test_old_order_questions_use_their_business_date():
    assert question_order_date("Đơn tạo ngày 28/09/2026, đổi trả?") == "2026-09-28"
    assert question_order_date("Đơn mua tháng 9/2026 được bảo hành?") == "2026-09-15"
    assert question_order_date("Đổi size hôm nay?") is None
