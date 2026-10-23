"""Turn-linked diagnosis of BTC reference-evaluator failures."""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def _finding(stage: str, turn: int, reason: str) -> dict:
    return {"stage": stage, "turn": turn, "reason": reason, "status": "observed"}


def build_failure_matrix(scenarios_dir: Path, trace_path: Path,
                         stages_path: Path, btc_report_path: Path) -> list[dict]:
    trace = defaultdict(list)
    trace_rows = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        trace_rows.append(row)
        trace[(row["scenario_id"], row["call"])].append(row)
    identities = {(row.get("run_id"), row.get("config")) for row in trace_rows}
    if len(identities) != 1 or not trace_rows:
        raise ValueError("trace run/config must be one nonempty pair")
    run_id, config = next(iter(identities))
    if not run_id or config not in {"full", "baseline_no_memory"}:
        raise ValueError("trace run/config invalid")
    stages = defaultdict(list)
    stage_rows = json.loads(stages_path.read_text(encoding="utf-8"))
    trace_coords = [(row.get("run_id"), row.get("config"), row.get("scenario_id"),
                     row.get("call"), row.get("turn")) for row in trace_rows]
    stage_coords = [(item.get("run_id"), item.get("config"), item.get("scenario_id"),
                     item.get("call"), item.get("turn")) for item in stage_rows]
    if any(item[0] != run_id or item[1] != config for item in stage_coords):
        raise ValueError("stage run/config differs from trace")
    if trace_coords != stage_coords:
        raise ValueError("stage coverage differs from trace")
    for item in stage_rows:
        stages[(item["scenario_id"], item["call"])].append(item)
    report = json.loads(btc_report_path.read_text(encoding="utf-8"))
    section = "system" if config == "full" else "baseline"
    if section not in report:
        raise ValueError(f"BTC score missing {section}")
    failures = {(item["scenario"], item["call"]): item.get("reasons", [])
                for item in report[section]["task_success_rate"].get("failures", [])}
    matrix = []
    for path in sorted(scenarios_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        scenario = json.loads(path.read_text(encoding="utf-8"))
        sid = scenario["scenario_id"]
        call_names = list(scenario["calls"])
        for call, spec in scenario["calls"].items():
            if "success_if" not in spec:
                continue
            rows = trace.get((sid, call), [])
            observed = stages.get((sid, call), [])
            expected_tool = spec["success_if"].get("tool_called")
            tool_calls = [(row["turn"], tool) for row in rows
                          for tool in row.get("tool_calls", [])
                          if isinstance(tool, dict)]
            evidence = [{"turn": turn, "name": tool.get("name"),
                         "status": next((item.get("status", "unknown")
                                         for stage in observed if stage.get("turn") == turn
                                         for item in stage.get("business_tools", [])
                                         if item.get("name") == tool.get("name")), "unknown")}
                        for turn, tool in tool_calls]
            uncertain = ["agent_use"] if spec.get("must_carry_over") else []
            if len(observed) != len(rows) or not observed:
                uncertain.extend(("identity", "memory_read", "call_brief"))
            elif any(stage.get("memory_read_status") == "unknown" for stage in observed):
                uncertain.append("memory_read")
            first = None
            if spec.get("must_carry_over"):
                for prior_call in call_names[:call_names.index(call)]:
                    failed_write = next((stage for stage in stages.get((sid, prior_call), [])
                                         if stage.get("memory_write_status") == "failed"), None)
                    if failed_write:
                        first = {**_finding("memory_write", failed_write["turn"],
                                            "prior commit_turn failed"), "call": prior_call}
                        break
            if first is None and observed:
                failed = next((stage for stage in observed
                               if stage.get("memory_read_status") == "failed"), None)
                if failed:
                    first = _finding("memory_read", failed["turn"], "memory.read failed")
                elif (spec.get("must_carry_over") and
                      observed[0].get("identity_status") == "ambiguous"):
                    first = _finding("identity", observed[0]["turn"], "identity ambiguous")
                elif (spec.get("must_carry_over") and
                      observed[0].get("identity_status") == "known" and
                      observed[0].get("prior_episode_count", 0) > 0 and
                      not observed[0].get("call_brief_present")):
                    first = _finding("call_brief", observed[0]["turn"],
                                     "known returning customer has no brief")
            if first is None and expected_tool:
                matched_name = [(turn, tool) for turn, tool in tool_calls
                                if tool.get("name") == expected_tool]
                if not matched_name:
                    first = _finding("business_tool_call", rows[-1]["turn"] if rows else 0,
                                     f"{expected_tool} not called")
                else:
                    expected_args = spec["success_if"].get("args_match") or {}
                    matched_args = [(turn, tool) for turn, tool in matched_name
                                    if all(value is None or tool.get("args", {}).get(key) == value
                                           for key, value in expected_args.items())]
                    if not matched_args:
                        first = _finding("business_tool_arguments", matched_name[0][0],
                                         "tool called with different required arguments")
                    else:
                        failed_result = next(((turn, tool) for turn, tool in matched_args
                                              if isinstance(tool.get("result"), dict)
                                              and (tool["result"].get("error") or
                                                   tool["result"].get("ok") is False)), None)
                        if failed_result:
                            first = _finding("business_tool_result", failed_result[0],
                                             "tool returned failure")
            reasons = failures.get((sid, call), [])
            if first is None:
                failed_write = next((stage for stage in observed
                                     if stage.get("memory_write_status") == "failed"), None)
                if failed_write:
                    first = _finding("memory_write", failed_write["turn"],
                                     "current commit_turn failed")
            if first is None and reasons:
                uncertain.append("agent_outcome")
            matrix.append({"scenario_id": sid, "call": call,
                           "expected_tool": expected_tool,
                           "btc_passed": not bool(reasons), "btc_reasons": reasons,
                           "first_observed_failure": first,
                           "uncertain_stages": sorted(set(uncertain)),
                           "tool_evidence": evidence})
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--stages", required=True, type=Path)
    parser.add_argument("--score", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = build_failure_matrix(args.scenarios, args.trace, args.stages, args.score)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


if __name__ == "__main__":
    main()
