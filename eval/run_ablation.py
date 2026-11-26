import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ABLATION_CONFIGS = {
    "full": {
        "eval_config": "full",
        "env": {
            "AGENT_AUTHORIZER_ENABLED": "true",
            "AGENT_VERIFY_ENABLED": "true",
            "AGENT_PROGRESSIVE_STREAMING": "true",
        },
    },
    "no_memory": {
        "eval_config": "baseline_no_memory",
        "env": {
            "AGENT_AUTHORIZER_ENABLED": "true",
            "AGENT_VERIFY_ENABLED": "true",
            "AGENT_PROGRESSIVE_STREAMING": "true",
        },
    },
    "no_authorizer": {
        "eval_config": "full",
        "env": {
            "AGENT_AUTHORIZER_ENABLED": "false",
            "AGENT_VERIFY_ENABLED": "true",
            "AGENT_PROGRESSIVE_STREAMING": "true",
        },
    },
    "no_verify": {
        "eval_config": "full",
        "env": {
            "AGENT_AUTHORIZER_ENABLED": "true",
            "AGENT_VERIFY_ENABLED": "false",
            "AGENT_PROGRESSIVE_STREAMING": "true",
        },
    },
    "no_progressive_streaming": {
        "eval_config": "full",
        "env": {
            "AGENT_AUTHORIZER_ENABLED": "true",
            "AGENT_VERIFY_ENABLED": "true",
            "AGENT_PROGRESSIVE_STREAMING": "false",
        },
    },
}


def _extract_metrics(score_path: Path) -> dict:
    data = json.loads(score_path.read_text(encoding="utf-8"))
    sys_m = data["system"]
    lat = sys_m.get("latency") or {}
    ttft = lat.get("ttft") or {}
    total = lat.get("total") or {}
    return {
        "rqr": sys_m["repeat_question_rate"]["value"],
        "ccr": sys_m["context_carryover_rate"]["value"],
        "tsr": sys_m["task_success_rate"]["value"],
        "tsr_hard": (sys_m["task_success_rate"].get("hard_cases") or {}).get("value"),
        "hr_price_promo": sys_m["hallucination_rate"]["price_promo_only"]["value"],
        "guardrail_violations": sys_m["guardrail_violations"]["total"],
        "ttft_p50_ms": ttft.get("p50_ms"),
        "ttft_p95_ms": ttft.get("p95_ms"),
        "total_p50_ms": total.get("p50_ms"),
        "total_p95_ms": total.get("p95_ms"),
    }


def _render_markdown(rows: list[tuple[str, dict]]) -> str:
    lines = [
        "| Config | RQR (%) | CCR (%) | TSR (%) | Hard TSR (%) | HR Price&Promo (%) | Guardrail Viol. | TTFT p50/p95 (ms) | Total p50/p95 (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, m in rows:
        lines.append(
            f"| `{name}` | {m['rqr']} | {m['ccr']} | {m['tsr']} | {m['tsr_hard']} | "
            f"{m['hr_price_promo']} | {m['guardrail_violations']} | "
            f"{m['ttft_p50_ms']} / {m['ttft_p95_ms']} | {m['total_p50_ms']} / {m['total_p95_ms']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run harness ablation matrix and build comparison table")
    parser.add_argument("--scenarios", required=True, type=Path)
    parser.add_argument("--btc-root", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--expected-database", default=os.getenv("EVAL_EXPECTED_DATABASE", "telesale_eval_m1"))
    parser.add_argument("--configs", default=",".join(ABLATION_CONFIGS))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    selected = [c.strip() for c in args.configs.split(",") if c.strip()]
    for name in selected:
        if name not in ABLATION_CONFIGS:
            parser.exit(2, f"Unknown ablation config: {name}\n")

    ref_eval = args.btc_root / "eval" / "reference_eval.py"
    summary_rows = []
    for name in selected:
        spec = ABLATION_CONFIGS[name]
        trace_path = args.out_dir / f"{name}.jsonl"
        score_path = args.out_dir / f"{name}.score.json"
        if not (args.skip_existing and trace_path.exists() and score_path.exists()):
            env = {**os.environ, **spec["env"], "PYTHONPATH": f"{ROOT / 'ai-services'}:{ROOT}"}
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "eval" / "run_eval.py"),
                    "--scenarios", str(args.scenarios),
                    "--btc-root", str(args.btc_root),
                    "--config", spec["eval_config"],
                    "--isolated-db",
                    "--expected-database", args.expected_database,
                    "--seed", str(args.seed),
                    "--out", str(trace_path),
                ],
                env=env,
                check=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    str(ref_eval),
                    "--scenarios", str(args.scenarios),
                    "--trace", str(trace_path),
                    "--out", str(score_path),
                ],
                check=True,
            )
        summary_rows.append((name, _extract_metrics(score_path)))

    summary_json = {name: m for name, m in summary_rows}
    (args.out_dir / "summary.json").write_text(json.dumps(summary_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = _render_markdown(summary_rows)
    (args.out_dir / "summary.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
