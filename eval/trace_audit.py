"""Audit BTC trace coverage and record nonsecret run provenance."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(paths: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        if path.is_file() and not path.is_symlink():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def source_snapshot_digest(root: Path) -> str:
    root = root.resolve()
    folders = (root / "ai-services" / "app", root / "ai-services" / "migrations",
               root / "ai-services" / "config", root / "eval")
    files = [p for folder in folders if folder.exists() for p in folder.rglob("*")
             if p.is_file() and "__pycache__" not in p.parts and "runs" not in p.parts
             and not p.name.startswith(".env") and p.suffix in {".py", ".sql", ".yml", ".yaml", ".json"}]
    for name in ("run_eval.py", "ai-services/requirements.txt"):
        path = root / name
        if path.is_file():
            files.append(path)
    if not files:
        raise ValueError("No source files found for digest")
    return _tree_digest(files, root)


def _btc_digest(scenarios_dir: Path) -> str:
    root = scenarios_dir.resolve().parents[1]
    paths = list(scenarios_dir.glob("*.json"))
    for name in ("schemas", "catalog", "policy"):
        folder = root / name
        if folder.exists():
            paths.extend(p for p in folder.rglob("*") if p.is_file())
    for name in ("eval/mock_tools.py", "DIEU-CHINH-DE.md", "GIAI-DAP-MENTOR.md"):
        path = root / name
        if path.is_file():
            paths.append(path)
    if not paths or not (root / "schemas" / "trace_log.schema.json").is_file():
        raise ValueError("BTC scenario/schema snapshot is incomplete")
    return _tree_digest(paths, root)


def _expected_turns(scenarios_dir: Path) -> list[tuple[str, str, int]]:
    expected = []
    for path in sorted(scenarios_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        scenario = json.loads(path.read_text(encoding="utf-8"))
        for call, spec in scenario["calls"].items():
            turns = spec.get("customer_turns_asr") or spec["customer_turns"]
            expected.extend((scenario["scenario_id"], call, i)
                            for i in range(1, len(turns) + 1))
    return expected


def audit_trace(scenarios_dir: Path, trace_path: Path, expected_config: str) -> dict:
    schema = scenarios_dir.resolve().parents[1] / "schemas" / "trace_log.schema.json"
    validator = Draft202012Validator(json.loads(schema.read_text(encoding="utf-8")))
    expected = _expected_turns(scenarios_dir)
    rows, errors = [], []
    for line_no, line in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"line {line_no}: invalid_json")
            continue
        if not isinstance(row, dict):
            errors.append(f"line {line_no}: schema non-object")
            continue
        rows.append(row)
        if next(validator.iter_errors(row), None):
            errors.append(f"line {line_no}: schema")
        if row.get("config") != expected_config:
            errors.append(f"line {line_no}: config")
    raw_ids = [row.get("run_id") for row in rows]
    run_ids = {value for value in raw_ids if isinstance(value, str) and value}
    if len(run_ids) != 1 or len(raw_ids) != sum(isinstance(i, str) and bool(i)
                                                for i in raw_ids):
        errors.append("run_id must be one nonempty value")
    actual = [(r["scenario_id"], r["call"], r["turn"]) for r in rows
              if isinstance(r.get("scenario_id"), str)
              and isinstance(r.get("call"), str) and type(r.get("turn")) is int]
    counts = Counter(actual)
    missing = list((Counter(expected) - counts).elements())
    extra = list((counts - Counter(expected)).elements())
    duplicate = [key for key, count in counts.items() if count > 1]
    if missing:
        errors.append(f"missing: {missing}")
    if extra:
        errors.append(f"extra: {extra}")
    if duplicate:
        errors.append(f"duplicate: {duplicate}")
    if not (missing or extra or duplicate) and actual != expected:
        errors.append("out_of_order")
    return {"rows": len(rows), "expected_rows": len(expected),
            "run_id": next(iter(run_ids)) if len(run_ids) == 1 else None,
            "missing": missing, "extra": extra, "duplicate": duplicate,
            "errors": errors}


def _reject_secret_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if any(word in key.casefold() for word in
                   ("password", "secret", "token", "api_key", "dsn", "credential")):
                raise ValueError("Secret-bearing manifest field")
            _reject_secret_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secret_keys(item)
    elif isinstance(value, str):
        if ("://" in value or
                re.search(r"(?i)\b(?:password|secret|token|api[_-]?key)\s*=", value) or
                re.search(r"\b(?:sk|pk)-[A-Za-z0-9_-]{8,}\b", value)):
            raise ValueError("Secret-bearing manifest value")


def build_manifest(*, trace_path: Path, scenarios_dir: Path, config: str,
                   source_digest: str, seed_id: str, seed_digest: str,
                   model_id: str, model_params: dict, tool_mode: str,
                   guardrails: dict, database_identity: dict, hardware: dict,
                   started_at_utc: str, scorer_report_path: Path) -> dict:
    audit = audit_trace(scenarios_dir, trace_path, config)
    if audit["errors"]:
        raise ValueError(f"Trace audit failed: {audit['errors']}")
    metadata = dict(source_digest=source_digest, seed_id=seed_id,
                    seed_digest=seed_digest, model_id=model_id,
                    model_params=model_params, tool_mode=tool_mode,
                    guardrails=guardrails, database_identity=database_identity,
                    hardware=hardware, started_at_utc=started_at_utc)
    _reject_secret_keys(metadata)
    if any(value in (None, "", {}) for value in metadata.values()):
        raise ValueError("Incomplete manifest metadata")
    if config not in {"full", "baseline_no_memory"}:
        raise ValueError("Invalid configuration")
    if database_identity.get("database", "").startswith("telesale_eval") is False:
        raise ValueError("Not an eval database")
    runner_report_path = trace_path.with_suffix(".report.json")
    runner_report = json.loads(runner_report_path.read_text(encoding="utf-8"))
    if (runner_report.get("database_identity") != database_identity or
            runner_report.get("run_id") != audit["run_id"] or
            runner_report.get("config") != config):
        raise ValueError("database_identity/run provenance differs from runner report")
    score_inputs_path = scorer_report_path.with_suffix(".inputs.json")
    if not score_inputs_path.is_file():
        raise ValueError("score provenance sidecar is unavailable")
    score_inputs = json.loads(score_inputs_path.read_text(encoding="utf-8"))
    scorer = scenarios_dir.resolve().parents[1] / "eval" / "reference_eval.py"
    input_key = "full_trace_sha256" if config == "full" else "baseline_trace_sha256"
    if (score_inputs.get(input_key) != _sha(trace_path) or
            score_inputs.get("score_sha256") != _sha(scorer_report_path) or
            not scorer.is_file() or score_inputs.get("scorer_sha256") != _sha(scorer)):
        raise ValueError("score provenance does not match trace/scorer/report")
    score = json.loads(scorer_report_path.read_text(encoding="utf-8"))
    if not isinstance(score.get("system"), dict) or not isinstance(score.get("baseline"), dict):
        raise ValueError("score provenance lacks paired BTC report")
    return {"run_id": audit["run_id"], "config": config,
            "trace_rows": audit["rows"], "expected_rows": audit["expected_rows"],
            "trace_sha256": _sha(trace_path),
            "scorer_report_sha256": _sha(scorer_report_path),
            "scorer_sha256": _sha(scorer),
            "score_inputs_sha256": _sha(score_inputs_path),
            "runner_report_sha256": _sha(runner_report_path),
            "btc_data_digest": _btc_digest(scenarios_dir), **metadata}


def audit_pair(full_manifest: dict, baseline_manifest: dict) -> list[str]:
    errors = []
    if full_manifest.get("config") != "full" or baseline_manifest.get("config") != "baseline_no_memory":
        errors.append("config pair must be full/baseline_no_memory")
    for name in ("source_digest", "btc_data_digest", "seed_id", "seed_digest",
                 "model_id", "model_params", "tool_mode", "guardrails", "hardware",
                 "expected_rows", "trace_rows", "scorer_sha256",
                 "scorer_report_sha256", "score_inputs_sha256"):
        if name not in full_manifest or name not in baseline_manifest:
            errors.append(f"missing {name}")
        elif full_manifest[name] != baseline_manifest[name]:
            errors.append(f"{name} differs")
    if not full_manifest.get("run_id") or not baseline_manifest.get("run_id"):
        errors.append("run_id missing")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    trace = commands.add_parser("trace")
    trace.add_argument("--scenarios", type=Path, required=True)
    trace.add_argument("--trace", type=Path, required=True)
    trace.add_argument("--config", choices=("full", "baseline_no_memory"), required=True)
    manifest = commands.add_parser("manifest")
    manifest.add_argument("--scenarios", type=Path, required=True)
    manifest.add_argument("--trace", type=Path, required=True)
    manifest.add_argument("--score", type=Path, required=True)
    manifest.add_argument("--metadata", type=Path, required=True)
    manifest.add_argument("--out", type=Path, required=True)
    pair = commands.add_parser("pair")
    pair.add_argument("--full", type=Path, required=True)
    pair.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "trace":
        result = audit_trace(args.scenarios, args.trace, args.config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["errors"]:
            parser.exit(1)
    elif args.command == "manifest":
        metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
        result = build_manifest(trace_path=args.trace, scenarios_dir=args.scenarios,
                                scorer_report_path=args.score, **metadata)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    else:
        result = audit_pair(json.loads(args.full.read_text(encoding="utf-8")),
                            json.loads(args.baseline.read_text(encoding="utf-8")))
        print(json.dumps({"errors": result}, ensure_ascii=False))
        if result:
            parser.exit(1)


if __name__ == "__main__":
    main()
