"""Measure the current lexical policy retriever on BTC QA without a running DB."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ai-services"))

from dataloader_offline.source import read_policy  # noqa: E402
from app.rag.policy_retrieval import lexical_rank  # noqa: E402


def active(chunk, on: date, order_date: date) -> bool:
    if chunk.access_level != "public":
        return False
    basis = order_date if chunk.date_basis == "order_date" else on
    return ((chunk.effective_from is None or date.fromisoformat(chunk.effective_from) <= basis)
            and (chunk.effective_until is None or date.fromisoformat(chunk.effective_until) >= basis))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=ROOT / "BTC-Data-Vong1-TEAMS")
    parser.add_argument("--on", type=date.fromisoformat, default=date(2026, 10, 15))
    parser.add_argument("--order-date", type=date.fromisoformat)
    args = parser.parse_args()
    qa = json.loads((args.data_dir / "rag" / "qa_labeled.json").read_text(encoding="utf-8"))
    source = read_policy(args.data_dir / "policy")
    allowed = [chunk for chunk in source if active(chunk, args.on, args.order_date or args.on)]
    rows = [{"chunk_id": chunk.chunk_id, "title": chunk.title, "body": chunk.body}
            for chunk in allowed]
    scores = defaultdict(lambda: {"n": 0, "hit_at_3": 0, "hit_at_5": 0, "full_at_5": 0})
    excluded = defaultdict(int)
    for question in qa["questions"]:
        expected = set(question["relevant_chunk_ids"])
        # Restricted targets are intentionally invisible to the runtime policy.search.
        if not expected or question["type"] == "restricted" or not expected.issubset(
                {chunk.chunk_id for chunk in allowed}):
            excluded[question["type"]] += 1
            continue
        ranking = [key for key, _ in lexical_rank(question["question"], rows)]
        bucket = scores[question["type"]]
        bucket["n"] += 1
        bucket["hit_at_3"] += bool(expected.intersection(ranking[:3]))
        bucket["hit_at_5"] += bool(expected.intersection(ranking[:5]))
        bucket["full_at_5"] += expected.issubset(ranking[:5])
    print(json.dumps({
        "mode": "offline_lexical_baseline", "on": args.on.isoformat(),
        "order_date": (args.order_date or args.on).isoformat(),
        "public_active_chunks": len(allowed), "by_type": scores,
        "excluded": excluded,
        "limitations": "Excluded restricted/empty/inactive targets; no answer quality or live DB measured."
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
