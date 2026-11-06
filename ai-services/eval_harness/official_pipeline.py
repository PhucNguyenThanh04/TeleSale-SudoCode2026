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


def atomic_bytes(path: Path, payload: bytes) -> None:
    """Publish exact scorer bytes; rename is atomic only for this one file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


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
                 *, btc_root: Path, safety_issues: list[dict] | None = None,
                 extraction_sidecars: dict[str, Path] | None = None,
                 require_turn_diagnostics: bool = False,
                 decision_diagnostics: dict | None = None) -> dict:
    """Audit, score and commit a complete pair; leave no score on failure."""
    traces = {"full": full_trace, "baseline_no_memory": baseline_trace}
    outputs = [score_out, score_out.with_suffix('.inputs.json'),
               *(score_out.parent / f'{config}.manifest.json' for config in traces)]
    if extraction_sidecars is not None:
        outputs.append(score_out.parent / "extraction_report.json")
    if any(path.exists() for path in outputs):
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
    turn_refs = {}
    if require_turn_diagnostics:
        from eval_harness.turn_diagnostics import verify_report_turn_diagnostics
        turn_refs = {config:verify_report_turn_diagnostics(trace) for config,trace in traces.items()}
    with tempfile.TemporaryDirectory(prefix="btc-score-") as temporary:
        pending = Path(temporary) / "score.json"
        provenance = score_pair(scenarios_dir, full_trace, baseline_trace,
                                pending, btc_root=btc_root)
        manifests = {config: build_manifest(
            trace_path=trace, scenarios_dir=scenarios_dir, config=config,
            scorer_report_path=pending, btc_root=btc_root, **metadata)
            for config, trace in traces.items()}
        if decision_diagnostics is not None:
            for manifest in manifests.values():
                manifest['decision_diagnostics'] = decision_diagnostics
        errors = audit_pair(manifests["full"], manifests["baseline_no_memory"])
        if errors:
            raise ValueError(f"Pair audit failed: {errors}")
        score = json.loads(pending.read_text(encoding="utf-8"))
        extraction = {}
        if extraction_sidecars is not None:
            from eval_harness.extraction_report import summarize_extraction
            extraction = summarize_extraction(traces, extraction_sidecars, score)
        score_out.parent.mkdir(parents=True, exist_ok=True)

        for config, manifest in manifests.items():
            atomic_json(score_out.parent / f"{config}.manifest.json", manifest)
        atomic_bytes(score_out.with_suffix(".inputs.json"), pending.with_suffix('.inputs.json').read_bytes())
        atomic_bytes(score_out, pending.read_bytes())
        diagnostic_ref = {}
        if extraction_sidecars is not None:
            from eval_harness.extraction_report import verify_extraction_report, sha256
            report_path = score_out.parent / 'extraction_report.json'
            atomic_json(report_path, extraction)
            checked = verify_extraction_report(report_path)
            if checked != summarize_extraction(traces, extraction_sidecars, json.loads(score_out.read_text())):
                raise ValueError('Published extraction/score mismatch')
            diagnostic_ref = {'extraction_report': {'path': report_path.name, 'sha256': sha256(report_path)},
                              'extraction_status': checked['extraction_status']}
        # Validate the bytes actually published, not just the staging files.
        final_manifests = {config: build_manifest(
            trace_path=trace, scenarios_dir=scenarios_dir, config=config,
            scorer_report_path=score_out, btc_root=btc_root, **metadata)
            for config, trace in traces.items()}
        if decision_diagnostics is not None:
            for manifest in final_manifests.values():
                manifest['decision_diagnostics'] = decision_diagnostics
        for config, expected in final_manifests.items():
            if json.loads((score_out.parent / f'{config}.manifest.json').read_text()) != expected:
                raise ValueError('Published manifest provenance mismatch')
        if audit_pair(final_manifests['full'], final_manifests['baseline_no_memory']):
            raise ValueError('Published pair provenance mismatch')
        if require_turn_diagnostics:
            for config, trace in traces.items():
                if verify_report_turn_diagnostics(trace) != turn_refs[config]:
                    raise ValueError('Published turn diagnostics mismatch')
            diagnostic_ref['turn_diagnostics'] = turn_refs
    from app.agent.harness.execution_diagnostics import pair_execution_health
    health = pair_execution_health(m.get('execution_health','unknown') for m in manifests.values())
    return {"status": "validated", "execution_health": health, "score": score, "manifests": manifests, "provenance": provenance, **diagnostic_ref}
