
import hashlib
import json
from collections import Counter
from pathlib import Path


def load_run(run_dir: Path) -> dict:
    index = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if index.get("status") != "validated" or index.get("score") != "btc_score.json":
        raise ValueError("run is not validated")
    score_path = run_dir / "btc_score.json"
    score = json.loads(score_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(score_path.read_bytes()).hexdigest()
    manifests = {}
    for config in ("full", "baseline_no_memory"):
        manifest = json.loads((run_dir / f"{config}.manifest.json").read_text(
            encoding="utf-8"))
        if (manifest.get("config") != config or
                not (manifest.get("run_id") == index.get("run_id") or
                     manifest.get("run_id", "").startswith(str(index.get("run_id")))) or
                manifest.get("trace_rows") != manifest.get("expected_rows") or
                manifest.get("scorer_report_sha256") != digest):
            raise ValueError("invalid run manifest")
        trace_name = (index.get("traces") or {}).get(config)
        if trace_name:
            trace_path = run_dir / trace_name
            if (trace_path.resolve().parent != run_dir.resolve() or
                    not trace_path.is_file() or
                    hashlib.sha256(trace_path.read_bytes()).hexdigest() !=
                    manifest.get("trace_sha256")):
                raise ValueError("invalid run trace")
        manifests[config] = manifest
    if manifests["full"]["expected_rows"] != manifests["baseline_no_memory"]["expected_rows"]:
        raise ValueError("paired manifests disagree on turn count")
    if not isinstance(score.get("system"), dict) or not isinstance(score.get("baseline"), dict):
        raise ValueError("invalid BTC paired score")
    rag_path = run_dir / "rag_summary.json"
    rag = json.loads(rag_path.read_text(encoding="utf-8")) if rag_path.exists() else None
    return {"run_id": index["run_id"], "score": score,
            "scenarios": score.get("n_scenarios"),
            "turns": manifests["full"]["expected_rows"],
            "manifests": manifests, "rag": rag, "path": run_dir,
            "index": index}


def _rate(key: str, label: str, source: dict, numerator: str,
          denominator: str, target: float | None = None) -> dict:
    value, n, d = source.get("value"), source.get(numerator), source.get(denominator)
    status = "measured" if value is not None and d not in (None, 0) else "not_measured"
    return {"key": key, "label": label, "value": value if status == "measured" else None,
            "numerator": n, "denominator": d, "unit": "%", "target": target,
            "status": status}


def metric_rows(score: dict) -> list[dict]:
    system = score.get("system", {})
    tsr = system.get("task_success_rate") or {}
    hard = tsr.get("hard_cases") or {}
    rqr = system.get("repeat_question_rate") or {}
    ccr = system.get("context_carryover_rate") or {}
    halluc = system.get("hallucination_rate") or {}
    price = halluc.get("price_promo_only") or {}
    rows = [
        _rate("tsr", "Hoàn thành nhiệm vụ", tsr, "passed", "total", 70),
        _rate("tsr_hard", "Ca khó", hard, "passed", "total"),
        _rate("rqr", "Hỏi lại", rqr, "redundant", "total_questions"),
        _rate("ccr", "Mang ngữ cảnh", ccr, "used", "required"),
        _rate("hallucination", "Sai sự thật", halluc, "wrong", "total_claims"),
        _rate("price_promo", "Sai giá/khuyến mãi", price, "wrong", "total", 5),
    ]
    reduction = (score.get("comparison") or {}).get("rqr_relative_reduction_pct")
    rows.append({"key": "rqr_reduction", "label": "Giảm hỏi lại", "value": reduction,
                 "numerator": None, "denominator": None, "unit": "%", "target": 40,
                 "status": "measured" if reduction is not None else "not_measured"})
    guard = system.get("guardrail_violations") or {}
    rows.append({"key": "guardrails", "label": "Vi phạm an toàn",
                 "value": guard.get("total"), "numerator": guard.get("total"),
                 "denominator": None, "unit": "lần", "target": 0,
                 "status": "measured" if guard.get("total") is not None else "not_measured"})
    return rows


def failure_counts(score: dict) -> dict[str, int]:
    failures = (score.get("system", {}).get("task_success_rate") or {}).get("failures") or []
    return dict(Counter(reason for item in failures for reason in item.get("reasons", [])))


def scenario_outcomes(score: dict, groups: dict[str, str],
                      selected_group: str | None = None) -> list[dict]:
    failures = (score.get("system", {}).get("task_success_rate") or {}).get("failures") or []
    failed = {item.get("scenario") for item in failures}
    return [{"scenario": scenario, "group": group,
             "status": "fail" if scenario in failed else "pass"}
            for scenario, group in sorted(groups.items())
            if selected_group is None or group == selected_group]
