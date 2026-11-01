"""Collect current policy rankings for BTC's 60 labeled text questions."""

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import asyncpg

from app.rag.policy_retrieval import retrieve


def question_order_date(question: str) -> str | None:
    explicit = re.search(r"(?:đơn\s+(?:tạo|mua)[^?]*?)\bngày\s+(\d{1,2})/(\d{1,2})/(\d{4})", question,
                         re.IGNORECASE)
    if explicit:
        day, month, year = map(int, explicit.groups())
        return date(year, month, day).isoformat()
    month_only = re.search(r"\bđơn\s+mua[^?]*?\btháng\s+(\d{1,2})/(\d{4})", question,
                           re.IGNORECASE)
    if month_only:
        month, year = map(int, month_only.groups())
        return date(year, month, 15).isoformat()
    return None


async def collect_retrieval(questions: list[dict], chunks: list[dict] | dict,
                            *, retrieve_fn=retrieve) -> dict:
    results = {}
    for item in questions:
        order_date = question_order_date(item["question"])
        relevant_chunks = (chunks.get(order_date, chunks.get(None, []))
                           if isinstance(chunks, dict) else chunks)
        result = await retrieve_fn(item["question"], relevant_chunks)
        results[item["qid"]] = {
            "retrieved_chunk_ids": [chunk["chunk_id"] for chunk in result["chunks"]],
            "retrieval_status": result.get("retrieval_status", "unknown"),
            "order_date": order_date}
    return results


async def current_policy_chunks(dsn: str, on: str = "2026-10-15",
                                order_date: str | None = None) -> list[dict]:
    connection = await asyncpg.connect(dsn.replace("postgresql+asyncpg://",
                                                  "postgresql://", 1))
    try:
        rows = await connection.fetch("""SELECT chunk_id,title,body,source_hash
            FROM btc_source.policy_chunks
            WHERE access_level='public' AND date_basis IN ('call_date','order_date')
            AND (effective_from IS NULL OR effective_from <=
                 CASE WHEN date_basis='order_date' THEN $2::date ELSE $1::date END)
            AND (effective_until IS NULL OR effective_until >=
                 CASE WHEN date_basis='order_date' THEN $2::date ELSE $1::date END)""",
                                      date.fromisoformat(on),
                                      date.fromisoformat(order_date or on))
        return [dict(row) for row in rows]
    finally:
        await connection.close()


async def score_current_rag(*, dsn: str, btc_root: Path, scenarios: Path,
                            full_trace: Path, baseline_trace: Path,
                            conversation_score: Path, out: Path) -> dict:
    qa_path = btc_root / "rag" / "qa_labeled.json"
    questions = json.loads(qa_path.read_text(encoding="utf-8"))["questions"]
    if len(questions) != 60 or len({item["qid"] for item in questions}) != 60:
        raise ValueError("BTC RAG QA set must contain 60 distinct questions")
    chunks = await current_policy_chunks(dsn)
    dates = {question_order_date(item["question"]) for item in questions}
    chunks_by_date = {None: chunks}
    for order_date in sorted(dates - {None}):
        chunks_by_date[order_date] = await current_policy_chunks(
            dsn, order_date=order_date)
    results = await collect_retrieval(questions, chunks_by_date)
    if len(results) != len(questions):
        raise RuntimeError("RAG retrieval coverage is incomplete")
    results_path = out / "rag_retrieval.json"
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    report_path = out / "rag_btc_report.json"
    subprocess.run([sys.executable, str(btc_root / "eval" / "reference_eval.py"),
                    "--scenarios", str(scenarios), "--trace", str(full_trace),
                    "--baseline", str(baseline_trace), "--rag", str(results_path),
                    "--out", str(report_path)], check=True, capture_output=True, text=True)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    conversation = json.loads(conversation_score.read_text(encoding="utf-8"))
    for key in ("system", "baseline", "comparison"):
        if report.get(key) != conversation.get(key):
            raise RuntimeError("BTC RAG invocation changed conversation score")
    summary = {"question_count": len(questions), "corpus_chunk_count": len(chunks),
               "retrieval_metrics": {key: value for key, value in report["rag"].items()
                                     if key.startswith(("recall@", "multi_hop_full_recall@",
                                                        "by_type_recall@"))},
               "answer_abstention": {"status": "not_measured",
                                      "reason": "No agent answers or calibrated abstention labels supplied"},
               "version_accuracy": {"status": "not_measured"}}
    (out / "rag_summary.json").write_text(json.dumps(summary, ensure_ascii=False,
                                                    indent=2) + "\n", encoding="utf-8")
    return summary
