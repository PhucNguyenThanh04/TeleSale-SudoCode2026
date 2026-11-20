import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai-services"))
from app.agent.guardrails.checks import mask_pii

RETIRED_REASON = (
    "Legacy memory baseline retired: fact_candidates/fallback no longer exists. "
    "Use eval_harness.run_official for the current runtime (live authorization required); "
    "corpus loading and offline scoring helpers remain available."
)


def load_cases(path: Path) -> list[dict]:
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case id")
    for case in cases:
        if not isinstance(case.get("expected_slots"), dict) or not isinstance(case.get("open_facts"), list):
            raise ValueError(f"Missing labels: {case['id']}")
        safe = mask_pii(case["text"])
        if safe != case["text"]:
            raise ValueError(f"Case must already mask PII: {case['id']}")
        for fact in case["open_facts"]:
            if fact["evidence_quote"] not in safe:
                raise ValueError(f"Open fact lacks exact evidence: {case['id']}")
    return cases


def score(rows: list[dict]) -> dict:
    counts: Counter = Counter()
    by_key: dict[str, Counter] = {}
    for row in rows:
        expected = row["expected_slots"]
        predicted = row["predicted_slots"]
        for key in expected.keys() | predicted.keys():
            bucket = by_key.setdefault(key, Counter())
            if key in expected and key in predicted and type(expected[key]) is type(predicted[key]) \
                    and expected[key] == predicted[key]:
                counts["tp"] += 1
                bucket["tp"] += 1
            else:
                if key in predicted:
                    counts["fp"] += 1
                    bucket["fp"] += 1
                if key in expected:
                    counts["fn"] += 1
                    bucket["fn"] += 1
    precision = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else None
    recall = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else None
    return {"tp": counts["tp"], "fp": counts["fp"], "fn": counts["fn"],
            "precision": precision, "recall": recall,
            "by_key": {key: dict(values) for key, values in sorted(by_key.items())}}


def _metrics(tp: int, fp: int, fn: int) -> dict:
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None}


def score_keys(rows: list[dict]) -> dict:
    tp = fp = fn = 0
    for row in rows:
        expected, predicted = set(row["expected_slots"]), set(row["predicted_slots"])
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
    return _metrics(tp, fp, fn)


def _fold(value: str) -> str:
    value = value.casefold().replace("đ", "d")
    value = "".join(c for c in unicodedata.normalize("NFD", value)
                    if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()


def _blocker_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    folded = _fold(value)
    for person in ("vo", "chong"):
        if re.search(rf"\bhoi\s+{person}\b", folded):
            return f"hoi {person}"
    return folded


def score_normalized_blocker(rows: list[dict]) -> dict:
    normalized = []
    for row in rows:
        expected, predicted = dict(row["expected_slots"]), dict(row["predicted_slots"])
        if "blocker" in expected:
            expected["blocker"] = _blocker_value(expected["blocker"])
        if "blocker" in predicted:
            predicted["blocker"] = _blocker_value(predicted["blocker"])
        normalized.append({"expected_slots": expected, "predicted_slots": predicted})
    return score(normalized)


def candidate_diagnostics(customer_text: str, tool_calls: list[dict],
                          agent_proposals: list[dict], extractor_proposals: list[dict]) -> dict:
    raise RuntimeError(RETIRED_REASON)


async def evaluate(cases: list[dict]) -> dict:
    raise RuntimeError(RETIRED_REASON)


def main() -> None:
    parser = argparse.ArgumentParser(description='Offline corpus/scoring utilities for the retired custom memory baseline.\n\nThe historical live runner used fact_candidates and fact_extraction_mode=fallback.\nProduction memory now uses LangMem; these scores must not represent that pipeline.\n')
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval/memory_facts_v1.jsonl")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.parse_args()
    parser.error(RETIRED_REASON)


if __name__ == "__main__":
    main()
