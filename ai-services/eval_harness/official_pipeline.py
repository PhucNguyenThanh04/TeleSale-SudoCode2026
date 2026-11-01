"""Validate a paired text run and publish only BTC's authoritative score."""

import json
import shutil
import tempfile
from pathlib import Path

from eval.score_pair import score_pair
from eval.trace_audit import audit_pair, audit_trace, build_manifest


def publish_pair(scenarios_dir: Path, full_trace: Path, baseline_trace: Path,
                 score_out: Path, metadata: dict,
                 *, btc_root: Path) -> dict:
    """Audit, score and commit a complete pair; leave no score on failure."""
    traces = {"full": full_trace, "baseline_no_memory": baseline_trace}
    for config, trace in traces.items():
        audit = audit_trace(scenarios_dir, trace, config, btc_root=btc_root)
        if audit["errors"]:
            raise ValueError(f"Trace audit failed ({config}): {audit['errors']}")
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
        shutil.copyfile(pending, score_out)
        shutil.copyfile(pending.with_suffix(".inputs.json"),
                        score_out.with_suffix(".inputs.json"))
        for config, manifest in manifests.items():
            (score_out.parent / f"{config}.manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
    return {"score": score, "manifests": manifests, "provenance": provenance}
