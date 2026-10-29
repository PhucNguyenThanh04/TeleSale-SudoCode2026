"""Compare BTC reference reports with an evidence-based LangMem adoption gate."""

import argparse
import json
from pathlib import Path


_META_KEYS = ("model", "temperature", "max_tokens", "seed", "reference_date",
              "dataset_hash")


def _value(section: dict, *path):
    current = section
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _rate(section: dict, numerator_key: str, denominator_key: str) -> float | None:
    denominator = section.get(denominator_key)
    return section.get("value") if isinstance(denominator, int) and denominator > 0 else None


def _failure_category(reasons: list[str]) -> str:
    value = " ".join(reasons).casefold()
    if "handoff" in value or "chuyển máy" in value:
        return "handoff"
    if "tool" in value or "args_match" in value:
        return "tool_or_arguments"
    if "giá" in value or "promo" in value or "khuyến mãi" in value:
        return "price_or_promotion"
    if "hỏi" in value or "question" in value:
        return "repeated_question"
    if "claim" in value or "cấm" in value:
        return "grounding_or_guardrail"
    return "other"


def _variant(report: dict) -> dict:
    system = report.get("system", {})
    rqr = system.get("repeat_question_rate") or {}
    ccr = system.get("context_carryover_rate") or {}
    tsr = system.get("task_success_rate") or {}
    hard = tsr.get("hard_cases") or {}
    hr = _value(system, "hallucination_rate", "price_promo_only") or {}
    guard = system.get("guardrail_violations") or {}
    latency = system.get("latency") or {}
    def p95(name):
        bucket = latency.get(name) or {}
        return bucket.get("p95_ms") if bucket.get("n", 0) > 0 else None
    return {"rqr_pct": _rate(rqr, "redundant", "total_questions"),
            "ccr_pct": _rate(ccr, "used", "required"),
            "tsr_pct": _rate(tsr, "passed", "total"),
            "hard_tsr_pct": _rate(hard, "passed", "total"),
            "price_promo_hr_pct": _rate(hr, "wrong", "total"),
            "guardrail_violations": guard.get("total"),
            "pii_violations": _value(guard, "by_type", "pii_in_memory_or_text"),
            "call_brief_p95_ms": p95("call_brief"),
            "total_p95_ms": p95("total"),
            "ttft_p95_ms": p95("ttft"),
            "cost_per_call_usd": report.get("cost_per_call_usd"),
            "tsr_failures": [{"scenario": failure.get("scenario"),
                              "call": failure.get("call"),
                              "category": _failure_category(failure.get("reasons") or [])}
                             for failure in tsr.get("failures", [])]}


def compare(reference_reports: dict[str, dict]) -> dict:
    """Return sanitized aggregates; missing denominators never become zero scores."""
    names = ("current", "shadow", "enabled")
    variants = {name: _variant(reference_reports.get(name, {})) for name in names}
    current, enabled = variants["current"], variants["enabled"]
    old_rqr, new_rqr = current["rqr_pct"], enabled["rqr_pct"]
    variants["enabled"]["rqr_relative_reduction_pct"] = (
        round((old_rqr - new_rqr) / old_rqr * 100, 1)
        if old_rqr is not None and old_rqr > 0 and new_rqr is not None else None)
    for name in ("current", "shadow"):
        variants[name]["rqr_relative_reduction_pct"] = None
    reasons = []
    meta = [reference_reports.get(name, {}).get("meta", {}) for name in names]
    if any(any(key not in item for key in _META_KEYS) for item in meta) or any(
            tuple(item.get(key) for key in _META_KEYS) !=
            tuple(meta[0].get(key) for key in _META_KEYS) for item in meta[1:]):
        reasons.append("run_metadata_mismatch")
    for name, item in zip(names, meta):
        report = reference_reports.get(name, {})
        expected_ids = report.get("reference_scenario_ids")
        if expected_ids is not None and sorted(item.get("scenario_ids", [])) != sorted(expected_ids):
            reasons.append("scenario_coverage_mismatch")
        elif (report.get("n_scenarios") is not None
              and item.get("total_scenarios_evaluated") is not None
              and report["n_scenarios"] != item["total_scenarios_evaluated"]):
            reasons.append("scenario_coverage_mismatch")
    for key in ("ccr_pct", "tsr_pct", "price_promo_hr_pct", "guardrail_violations",
                "pii_violations", "call_brief_p95_ms"):
        if current[key] is None or enabled[key] is None:
            reasons.append("missing_" + key)
    if all(current[key] is not None and enabled[key] is not None
           for key in ("ccr_pct", "tsr_pct")):
        if enabled["ccr_pct"] < current["ccr_pct"]:
            reasons.append("context_carryover_regression")
        if enabled["tsr_pct"] < current["tsr_pct"]:
            reasons.append("task_success_regression")
        if (enabled["ccr_pct"] <= current["ccr_pct"]
                and enabled["tsr_pct"] <= current["tsr_pct"]):
            reasons.append("no_measurable_gain")
    if enabled["price_promo_hr_pct"] is not None and enabled["price_promo_hr_pct"] > 5:
        reasons.append("price_promo_hr_above_5pct")
    if enabled["guardrail_violations"] is not None and enabled["guardrail_violations"] > 0:
        reasons.append("guardrail_violation")
    if enabled["pii_violations"] is not None and enabled["pii_violations"] > 0:
        reasons.append("pii_violation")
    if enabled["call_brief_p95_ms"] is not None and enabled["call_brief_p95_ms"] > 5000:
        reasons.append("call_brief_p95_above_5s")
    return {"variants": variants, "adoption_gate": {"pass": not reasons,
            "reasons": sorted(set(reasons))},
            "note": "TTFT is a total-latency proxy until streaming measurement exists."}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare official BTC LangMem reports")
    for name in ("current", "shadow", "enabled"):
        parser.add_argument("--" + name, type=Path, required=True)
        parser.add_argument("--" + name + "-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scenarios", type=Path, required=True,
                        help="The exact scenario directory passed to BTC reference_eval")
    args = parser.parse_args()
    expected_ids = sorted(json.loads(path.read_text(encoding="utf-8"))["scenario_id"]
                          for path in args.scenarios.glob("*.json")
                          if not path.name.startswith("_"))
    reports = {}
    for name in ("current", "shadow", "enabled"):
        reports[name] = json.loads(getattr(args, name).read_text(encoding="utf-8"))
        manifest = json.loads(getattr(args, name + "_manifest").read_text(encoding="utf-8"))
        reports[name]["meta"] = manifest.get("meta", {})
        reports[name]["reference_scenario_ids"] = expected_ids
    result = compare(reports)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["adoption_gate"], ensure_ascii=False))


if __name__ == "__main__":
    main()
