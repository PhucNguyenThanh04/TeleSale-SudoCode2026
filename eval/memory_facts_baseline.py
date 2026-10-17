"""Measure the current fallback memory path on a fixed synthetic turn set.

This runs the real configured model and agent, with read-only business-tool mocks.
It does not call the memory MCP or write customer data to PostgreSQL.
"""

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai-services"))

from app.agent.guardrails.checks import FALLBACK, mask_pii  # noqa: E402
from app.agent.harness.agent_nodes import AgentNodes  # noqa: E402
from app.agent.memory.fact_candidates import accepted_candidates  # noqa: E402
from app.configs import get_settings  # noqa: E402
from app.infarstructure.llm import build_llm  # noqa: E402
from app.schemas.agent import TextTurnRequest  # noqa: E402


class ReadOnlyTools:
    """Allow the agent loop to run without touching CRM, catalog, or orders."""

    async def invoke(self, name, _args):
        if name == "catalog.search":
            return {"items": [], "total": 0}
        return {"error": "baseline_mock_unavailable"}


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


async def evaluate(cases: list[dict]) -> dict:
    settings = get_settings()
    model = build_llm(settings)
    nodes = AgentNodes(model, ReadOnlyTools(), None, settings.agent_max_tool_calls,
                       settings.agent_prompt_history_turns,
                       clock=lambda: datetime(2026, 10, 15, tzinfo=timezone.utc),
                       agent_kind=settings.agent_kind, fact_extraction_mode="fallback")
    from app.agent.harness import agent_nodes

    rows = []
    for case in cases:
        request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
                                  channel="web_chat", channel_identity="synthetic-eval",
                                  on=date(2026, 10, 15), text=case["text"],
                                  input_mode=case["input_mode"])
        state = {"request": request, "safe_text": case["text"],
                 "identity_status": "known", "customer_id": "synthetic-eval",
                 "profile": {key: {"value": value, "source_kind": "customer"}
                             for key, value in case.get("prior_slots", {}).items()},
                 "history": [], "episodes": [], "tool_calls": [], "tool_count": 0}
        extraction_calls = 0
        original = agent_nodes.extract_customer_candidates

        async def tracked(model_arg, text_arg):
            nonlocal extraction_calls
            extraction_calls += 1
            return await original(model_arg, text_arg)

        started = time.perf_counter()
        with patch.object(agent_nodes, "extract_customer_candidates", tracked):
            result = await nodes.run_agent(state)
        accepted = accepted_candidates(case["text"], result.get("tool_calls", []),
                                       result.get("fact_candidates", []))
        predicted = {item["key"]: item["value"] for item in accepted
                     if item["source_kind"] == "customer"}
        rows.append({"id": case["id"], "expected_slots": case["expected_slots"],
                     "predicted_slots": predicted, "expected_open_count": len(case["open_facts"]),
                     "extraction_calls": extraction_calls,
                     "tool_calls": result.get("tool_count", 0),
                     "agent_fallback": result.get("agent_draft") == FALLBACK,
                     "duration_ms": round((time.perf_counter() - started) * 1000)})
        print(f"{case['id']}: {len(predicted)} slot, {extraction_calls} lần trích, "
              f"{rows[-1]['duration_ms']} ms", flush=True)

    return {"dataset_cases": len(rows), "configuration": {
                "model": settings.llm_model, "temperature": settings.llm_temperature,
                "max_tokens": settings.llm_max_tokens, "agent_kind": settings.agent_kind,
                "fact_extraction_mode": "fallback", "business_tools": "read_only_mock"},
            "typed_slots": score(rows),
            "open_facts": {"expected": sum(r["expected_open_count"] for r in rows),
                           "predicted": 0,
                           "note": "Current allowlist has no open-fact output"},
            "agent_fallbacks": sum(r["agent_fallback"] for r in rows),
            "extraction_calls": sum(r["extraction_calls"] for r in rows),
            "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval/memory_facts_v1.jsonl")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    cases = load_cases(args.dataset)
    if args.limit:
        cases = cases[:args.limit]
    report = asyncio.run(evaluate(cases))
    report["dataset_sha256"] = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    report["method"] = ("Isolated single-turn run_agent path with configured LLM, "
                        "fallback gate, current fact validator, and read-only tool mocks; "
                        "no PostgreSQL, MCP HTTP, or cross-session memory")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
