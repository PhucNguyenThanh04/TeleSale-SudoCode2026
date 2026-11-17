"""Run BTC's scorer and bind its report to the exact input trace bytes."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scenario_sha(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def score_pair(scenarios_dir: Path, full_trace: Path,
               baseline_trace: Path, score_out: Path,
               btc_root: Path | None = None) -> dict:
    root = btc_root.resolve() if btc_root else scenarios_dir.resolve().parents[1]
    scorer = root / "eval" / "reference_eval.py"
    if not scorer.is_file():
        raise FileNotFoundError("BTC reference_eval.py is unavailable")
    before = {"full_trace_sha256": _sha(full_trace),
              "baseline_trace_sha256": _sha(baseline_trace),
              "scorer_sha256": _sha(scorer),
              "scenario_sha256": _scenario_sha(scenarios_dir)}
    score_out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(scorer), "--scenarios", str(scenarios_dir),
                    "--trace", str(full_trace), "--baseline", str(baseline_trace),
                    "--out", str(score_out)], check=True, capture_output=True, text=True)
    after = {"full_trace_sha256": _sha(full_trace),
             "baseline_trace_sha256": _sha(baseline_trace),
             "scorer_sha256": _sha(scorer),
             "scenario_sha256": _scenario_sha(scenarios_dir)}
    if before != after:
        raise RuntimeError("BTC scorer inputs changed during scoring")
    score = json.loads(score_out.read_text(encoding="utf-8"))
    if not isinstance(score.get("system"), dict) or not isinstance(score.get("baseline"), dict):
        raise RuntimeError("BTC scorer did not produce a paired report")
    provenance = {**before, "score_sha256": _sha(score_out)}
    score_out.with_suffix(".inputs.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return provenance


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--full", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument('--btc-root', type=Path, help='Gói BTC chứa scorer dùng cho cặp trace')
    args = parser.parse_args()
    score_pair(args.scenarios, args.full, args.baseline, args.out, btc_root=args.btc_root)


if __name__ == "__main__":
    main()
