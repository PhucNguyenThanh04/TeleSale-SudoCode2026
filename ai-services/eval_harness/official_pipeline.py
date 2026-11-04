"""Validate a paired text run and publish only BTC's authoritative score."""

import json
import hashlib
import os
import tempfile
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from eval.score_pair import score_pair
from eval.trace_audit import audit_pair, audit_trace, build_manifest, _reject_secret_keys, _btc_digest


def atomic_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        Path(temporary).replace(path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def publish_pair(scenarios_dir: Path, full_trace: Path, baseline_trace: Path,
                 score_out: Path, metadata: dict,
                 *, btc_root: Path, safety_issues: list[dict] | None = None) -> dict:
    """Audit, score and commit a complete pair; leave no score on failure."""
    traces = {"full": full_trace, "baseline_no_memory": baseline_trace}
    if score_out.exists() or score_out.with_suffix(".inputs.json").exists():
        raise ValueError("Refusing existing score output; use a new run directory")
    for config, trace in traces.items():
        audit = audit_trace(scenarios_dir, trace, config, btc_root=btc_root)
        if audit["errors"]:
            raise ValueError(f"Trace audit failed ({config}): {audit['errors']}")
    if safety_issues:
        _reject_secret_keys(metadata)
        manifests = {}
        for config, trace in traces.items():
            manifests[config] = {**metadata, "status": "invalid", "config": config,
                "btc_data_digest": _btc_digest(scenarios_dir, btc_root),
                "scorer_sha256": hashlib.sha256((btc_root / "eval/reference_eval.py").read_bytes()).hexdigest(),
                "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
                "safety_issues": safety_issues,
                "reason": "redaction_affects_scoring"}
            atomic_json(score_out.parent / f"{config}.manifest.json", manifests[config])
        return {"status": "invalid", "manifests": manifests, "score": None}
    with tempfile.TemporaryDirectory(prefix="btc-score-") as temporary:
        pending = Path(temporary) / "score.json"
        provenance = score_pair(scenarios_dir, full_trace, baseline_trace,
                                pending, btc_root=btc_root)
        manifests = {config: build_manifest(
            trace_path=trace, scenarios_dir=scenarios_dir, config=config,
            scorer_report_path=pending, btc_root=btc_root, **metadata)
            for config, trace in traces.items()}
        errors = audit_pair(manifests["full"], manifests["baseline_no_memory"])
        if errors:
            raise ValueError(f"Pair audit failed: {errors}")
        score = json.loads(pending.read_text(encoding="utf-8"))
        score_out.parent.mkdir(parents=True, exist_ok=True)

        for config, manifest in manifests.items():
            atomic_json(score_out.parent / f"{config}.manifest.json", manifest)
        atomic_json(score_out.with_suffix(".inputs.json"), provenance)
        atomic_json(score_out, score)
    return {"status": "validated", "score": score, "manifests": manifests, "provenance": provenance}
