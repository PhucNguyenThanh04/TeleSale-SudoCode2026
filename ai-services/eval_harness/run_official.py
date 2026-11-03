"""Run paired text conversations and publish the BTC score for one run."""

import argparse
import asyncio
import json
import os
from app.knowledge.context import capture_release, release_context, selected_release
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.configs import Settings
from app.mcp_servers.mcp_shared.config import database_url
from eval_harness.seed_fingerprint import fingerprint_btc_source

PROJECT = Path(__file__).resolve().parents[2]
SERVICE = PROJECT / "ai-services"
sys.path.insert(0, str(PROJECT))

from eval.trace_audit import source_snapshot_digest  # noqa: E402
from eval_harness.official_pipeline import publish_pair  # noqa: E402


def require_same_seed(full_digest: str, baseline_digest: str) -> str:
    if not full_digest or full_digest != baseline_digest:
        raise ValueError("btc_source changed between full and baseline")
    return full_digest


def _run_one(config: str, scenarios: Path, agent: str, seed: int,
             run_id: str, out: Path) -> Path:
    report = out / f"{config}.diagnostics.json"
    env = dict(os.environ)
    if selected_release():
        env['KNOWLEDGE_RELEASE_ID'] = selected_release()
    subprocess.run([sys.executable, "-m", "eval_harness.benchmark_runner",
                    "--agent", agent, "--config", config, "--seed", str(seed),
                    "--scenarios", str(scenarios), "--run-id", run_id,
                    "--out", str(report)], cwd=SERVICE, check=True, env=env)
    trace = report.with_name(report.stem + f"_{config}.jsonl")
    if not trace.is_file():
        raise RuntimeError(f"{config} trace was not written")
    return trace


async def run_pair(*, scenarios: Path, btc_root: Path, agent: str,
                   seed: int, out_root: Path) -> Path:
    settings = Settings()
    if settings.app_env == "production":
        raise ValueError("Evaluation cannot run in production")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    out = out_root / run_id
    out.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    source_before = source_snapshot_digest(PROJECT)
    dsn = database_url(settings)
    knowledge_release = await capture_release(dsn)
    seed_before_full = await fingerprint_btc_source(dsn)
    with release_context(knowledge_release["release_id"]):
        full = _run_one("full", scenarios, agent, seed, run_id, out)
    seed_after_full = await fingerprint_btc_source(dsn)
    require_same_seed(seed_before_full, seed_after_full)
    seed_before_base = await fingerprint_btc_source(dsn)
    require_same_seed(seed_before_full, seed_before_base)
    with release_context(knowledge_release["release_id"]):
        baseline = _run_one("baseline", scenarios, agent, seed, run_id, out)
    seed_after_base = await fingerprint_btc_source(dsn)
    seed_digest = require_same_seed(seed_before_full, seed_after_base)
    if source_before != source_snapshot_digest(PROJECT):
        raise RuntimeError("Evaluation source changed during the run")
    full_identity = json.loads(full.with_suffix(".report.json").read_text(
        encoding="utf-8"))["database_identity"]
    base_identity = json.loads(baseline.with_suffix(".report.json").read_text(
        encoding="utf-8"))["database_identity"]
    if full_identity != base_identity:
        raise ValueError("MCP database identity changed between configurations")
    metadata = dict(source_digest=source_before, seed_id=f"btc-source-seed-{seed}",
                    seed_digest=seed_digest, model_id=settings.llm_model,
                    model_params={"temperature": settings.llm_temperature,
                                  "max_tokens": settings.llm_max_tokens,
                                  "seed": seed, "agent": agent,
                                  "prompt_history_turns": settings.agent_prompt_history_turns},
                    tool_mode="mcp", guardrails={"enabled": settings.agent_guardrails_enabled},
                    database_identity=full_identity,
                    hardware={"platform": platform.platform(), "machine": platform.machine()},
                    started_at_utc=started, expected_database=full_identity["database"],
                    app_env=settings.app_env, knowledge_release=knowledge_release)
    result = publish_pair(scenarios, full, baseline, out / "btc_score.json",
                          metadata, btc_root=btc_root)
    scenario_groups = {item["scenario_id"]: item.get("level") or "Khác"
                       for item in (json.loads(path.read_text(encoding="utf-8"))
                                    for path in sorted(scenarios.glob("*.json"))
                                    if not path.name.startswith("_"))}
    run_summary = {
        "run_id": run_id, "status": "validated", "score": "btc_score.json",
        "manifests": {key: f"{key}.manifest.json" for key in result["manifests"]},
        "traces": {"full": full.name, "baseline_no_memory": baseline.name},
        "scenario_groups": scenario_groups,
        "scenarios": str(scenarios.resolve()), "btc_root": str(btc_root.resolve())}
    (out / "run.json").write_text(json.dumps(
        run_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Paired BTC text conversation evaluation")
    parser.add_argument("--scenarios", type=Path, default=SERVICE / "eval_harness/scenarios")
    parser.add_argument("--btc-root", type=Path, required=True)
    parser.add_argument("--agent", choices=("deep", "react"), default="deep")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out-root", type=Path, default=SERVICE / "eval_harness/results")
    args = parser.parse_args()
    if not args.scenarios.is_dir():
        parser.error("--scenarios must be a directory of BTC JSON scenarios")
    output = asyncio.run(run_pair(scenarios=args.scenarios.resolve(),
                                  btc_root=args.btc_root.resolve(), agent=args.agent,
                                  seed=args.seed, out_root=args.out_root.resolve()))
    print(f"Validated BTC score: {output / 'btc_score.json'}")


if __name__ == "__main__":
    main()
