"""Read-only compatibility checks before a costly BTC evaluation run."""

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any


_PII_FIELDS = {"customer_name", "customer_phone", "phone", "address"}
_REDACTION = re.compile(r"\[[^\]]*ĐÃ ẨN\]")


def _supports_order_aliases(btc_root: Path) -> bool:
    path = btc_root / "eval" / "reference_eval.py"
    if not path.exists():
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(isinstance(node, ast.FunctionDef) and node.name == "args_match"
               and any(arg.arg == "order_aliases" for arg in node.args.args)
               for node in tree.body)


def _outcomes(btc_root: Path) -> set[str]:
    text = (btc_root / "schemas" / "scenario_format.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        cells = line.split("|")
        if len(cells) > 2 and cells[1].strip() == "`expected_outcome`":
            return set(re.findall(r"\b[a-z]+(?:_[a-z]+)*\b", cells[2]))
    raise ValueError("BTC expected_outcome contract is unavailable")


def _pii_matcher_fields(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(key in _PII_FIELDS or _pii_matcher_fields(item)
               for key, item in value.items())


def _redacted_matcher_fields(value: Any, expected: Any) -> bool:
    if not isinstance(value, dict) or not isinstance(expected, dict):
        return False
    return any((isinstance(value.get(key), str) and
                bool(_REDACTION.search(value[key]))) or
               _redacted_matcher_fields(value.get(key), item)
               for key, item in expected.items() if key in value)


def inspect_eval_inputs(scenarios_dir: Path, btc_root: Path,
                        trace_path: Path | None = None) -> dict[str, Any]:
    """Report scorer contract risks without modifying scenarios or traces."""
    allowed_outcomes = _outcomes(btc_root)
    supports_aliases = _supports_order_aliases(btc_root)
    tool_schema = json.loads((btc_root / "schemas" / "tools.schema.json").read_text(
        encoding="utf-8"))
    allowed_tools = {item["name"] for item in tool_schema["tools"]}
    paths = sorted(path for path in scenarios_dir.glob("*.json")
                   if not path.name.startswith("_"))
    scenarios = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    specs = {item["scenario_id"]: item for item in scenarios}
    issues: list[dict[str, str]] = []

    def add(code: str, scenario_id: str, call: str) -> None:
        issues.append({"code": code, "scenario_id": scenario_id, "call": call})

    for scenario in scenarios:
        sid = scenario["scenario_id"]
        previous_calls: list[dict] = []
        for call, spec in scenario["calls"].items():
            outcome = spec.get("expected_outcome")
            if outcome is not None and outcome not in allowed_outcomes:
                add("unsupported_outcome", sid, call)
            success = spec.get("success_if") or {}
            tool = success.get("tool_called")
            if tool and tool not in allowed_tools:
                add("unknown_expected_tool", sid, call)
            matcher = success.get("args_match") or {}
            if _pii_matcher_fields(matcher):
                add("pii_args_match", sid, call)
            expected_id = matcher.get("order_id")
            if not supports_aliases and expected_id and any(
                earlier.get("facts_established", {}).get("order_id") == expected_id
                and (earlier.get("expected_outcome") in {"chot_don", "len_don_thanh_cong"}
                     or (earlier.get("success_if") or {}).get("tool_called") == "order.create")
                for earlier in previous_calls
            ):
                add("generated_order_id_exact_match", sid, call)
            previous_calls.append(spec)

    redacted_names = False
    if trace_path is not None:
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            sid = row.get("scenario_id", "")
            call = row.get("call", "")
            expected = ((specs.get(sid, {}).get("calls", {}).get(call, {})
                         .get("success_if") or {}).get("args_match") or {})
            for tool_call in row.get("tool_calls", []):
                name = tool_call.get("name", "")
                if _REDACTION.search(name):
                    add("redacted_tool_name", sid, call)
                    redacted_names = True
                elif name not in allowed_tools:
                    add("unknown_tool_name", sid, call)
                if name == "crm.get_customer" and tool_call.get("result", {}).get("found") is False:
                    add("unresolved_customer_identity", sid, call)
                if _redacted_matcher_fields(tool_call.get("args"), expected):
                    add("redacted_scored_arg", sid, call)
                if supports_aliases and name == "order.create":
                    result = tool_call.get("result") or {}
                    if not result.get("error"):
                        order_id = result.get("order_id")
                        if not isinstance(order_id, str) or not order_id:
                            add("missing_created_order_id", sid, call)
                        elif _REDACTION.search(order_id):
                            add("redacted_created_order_id", sid, call)
    issues = list({(item["code"], item["scenario_id"], item["call"]): item
                   for item in issues}.values())
    return {"scenario_count": len(scenarios), "issues": issues,
            "trace_recoverable": None if trace_path is None else not redacted_names}


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only BTC input preflight")
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--btc-root", type=Path, required=True)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--offline-check", action="store_true", help="Validate files only; no model, MCP or database access")
    args = parser.parse_args()
    if args.offline_check:
        from eval_harness.scenario_contract import load_scenarios, dataset_coverage
        print(json.dumps(dataset_coverage(load_scenarios(args.scenarios, btc_root=args.btc_root))))
        return
    report = inspect_eval_inputs(args.scenarios, args.btc_root, args.trace)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
