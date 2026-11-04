"""Coordinate an audited BTC pair; final run.json is the publication authority."""
import argparse
import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.configs import Settings
from app.knowledge.context import capture_release, release_context, selected_release
from app.mcp_servers.mcp_shared.config import database_url
from eval_harness.seed_fingerprint import fingerprint_btc_source
from eval_harness.scenario_contract import load_scenarios, dataset_coverage, snapshot_scenarios

PROJECT = Path(__file__).resolve().parents[2]
SERVICE = PROJECT / 'ai-services'
sys.path.insert(0,str(PROJECT))
from eval.trace_audit import source_snapshot_digest
from eval_harness.official_pipeline import publish_pair, atomic_json


def require_same_seed(full_digest, baseline_digest):
    if not full_digest or full_digest != baseline_digest:
        raise ValueError('btc_source changed between full and baseline')
    return full_digest


def _run_one(config, scenarios, agent, seed, run_id, out, *, btc_root, expected_database, release):
    report=out/f'{config}.diagnostics.json'
    env=dict(os.environ)
    env['_EVAL_PINNED_RELEASE']=json.dumps(release)
    env['KNOWLEDGE_RELEASE_ID']=release['release_id']
    # The child applies the same offline dataset validator before any mutation.
    print(f"[eval] {config}: starting", flush=True)
    completed=subprocess.run([sys.executable,'-u','-m','eval_harness.benchmark_runner','--agent',agent,
        '--config',config,'--seed',str(seed),'--scenarios',str(scenarios),'--btc-root',str(btc_root),
        '--expected-database',expected_database,'--run-id',run_id,'--out',str(report)],
        cwd=SERVICE,env=env,stdout=None,stderr=subprocess.PIPE,text=True)
    suffix='baseline' if config in {'baseline','baseline_no_memory'} else config
    trace=report.with_name(report.stem+f'_{suffix}.jsonl')
    # An invalid child deliberately exits nonzero but leaves complete safe evidence.
    side=trace.with_suffix('.report.json')
    status=json.loads(side.read_text()).get('status') if side.exists() else None
    if (completed.returncode and status!='invalid') or not trace.is_file():
        failure=RuntimeError('configuration_execution_failed')
        details=json.loads(side.read_text()) if side.exists() else {}
        failure.safety_issues=details.get('safety_issues',[])
        failure.error_code=details.get('error_code','configuration_execution_failed')
        failure.phase=details.get('phase','configuration')
        failure.service=details.get('service')
        raise failure
    return trace


def _dataset_digest(scenarios):
    return hashlib.sha256(json.dumps(scenarios,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


async def run_pair(*, scenarios: Path, btc_root: Path, agent: str, seed: int,
                   out_root: Path, expected_database: str | None = None,
                   limit_scenarios: int | None = None) -> Path:
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    out=out_root/run_id
    out.mkdir(parents=True,exist_ok=False)
    summary={'run_id':run_id,'status':'running','btc_root':str(btc_root.resolve())}
    atomic_json(out/'run.json',summary)
    safety_issues=[]
    try:
        inputs=load_scenarios(scenarios,btc_root=btc_root)
        original_digest=_dataset_digest(inputs)
        if limit_scenarios is not None:
            if limit_scenarios<1:
                raise ValueError('limit_scenarios must be positive')
            inputs=dict(list(inputs.items())[:limit_scenarios])
        selected=snapshot_scenarios(inputs,out/'scenarios')
        selected_digest=_dataset_digest(inputs)
        target=expected_database or os.getenv('EVAL_EXPECTED_DATABASE')
        if not target:
            raise ValueError('Explicit --expected-database is required')
        settings=Settings()
        if settings.app_env=='production':
            raise ValueError('Evaluation cannot run in production')
        started=datetime.now(timezone.utc).isoformat()
        source_before=source_snapshot_digest(PROJECT)
        dsn=database_url(settings)
        release=await capture_release(dsn)
        seed_digest=await fingerprint_btc_source(dsn)
        traces={}
        identity=None
        for config in ('full','baseline'):
            require_same_seed(seed_digest,await fingerprint_btc_source(dsn))
            with release_context(release['release_id']):
                trace=_run_one(config,selected,agent,seed,run_id,out,
                    btc_root=btc_root,expected_database=target,release=release)
            require_same_seed(seed_digest,await fingerprint_btc_source(dsn))
            report=json.loads(trace.with_suffix('.report.json').read_text())
            current=report['database_identity']
            if current.get('database') != target or (identity is not None and current != identity):
                raise ValueError('MCP database identity changed between configurations')
            identity=current
            safety_issues.extend(report.get('safety_issues',[]))
            traces['full' if config=='full' else 'baseline_no_memory']=trace
        if source_before!=source_snapshot_digest(PROJECT):
            raise RuntimeError('Evaluation source changed during the run')
        if original_digest!=_dataset_digest(load_scenarios(scenarios,btc_root=btc_root)):
            raise RuntimeError('Dataset changed during the run')
        if selected_digest!=_dataset_digest(load_scenarios(selected,btc_root=btc_root)):
            raise RuntimeError('Dataset snapshot changed during the run')
        from urllib.parse import urlsplit
        provider=urlsplit(str(settings.ollama_base_url)).hostname
        metadata=dict(source_digest=source_before,seed_id=f'btc-source-seed-{seed}',seed_digest=seed_digest,
            model_id=settings.llm_model,model_params={'temperature':settings.llm_temperature,
                'max_tokens':settings.llm_max_tokens,'seed':seed,'agent':agent,'provider':provider,
                'streaming':False,'warmup_turns':3,'prompt_history_turns':settings.agent_prompt_history_turns},
            tool_mode='mcp',guardrails={'enabled':settings.agent_guardrails_enabled},database_identity=identity,
            hardware={'platform':platform.platform(),'machine':platform.machine(),'cpu_count':os.cpu_count(),
                      'ram_bytes':os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')},
            started_at_utc=started,expected_database=target,app_env=settings.app_env,knowledge_release=release)
        print("[eval] pair: audit and BTC scoring", flush=True)
        result=publish_pair(selected,traces['full'],traces['baseline_no_memory'],out/'btc_score.json',
            metadata,btc_root=btc_root,safety_issues=safety_issues)
        summary.update(status=result.get('status','validated'),
            score='btc_score.json' if result.get('status','validated')=='validated' else None,
            manifests={key:f'{key}.manifest.json' for key in result['manifests']},
            traces={key:path.name for key,path in traces.items()},scenarios=str(selected.resolve()),
            scenario_groups={sid:sc.get('level','Khác') for sid,sc in inputs.items()},
            coverage=dataset_coverage(inputs),subset=limit_scenarios is not None,
            latency_scale_sufficient=dataset_coverage(inputs)['turns']>=100,
            safety_issues=safety_issues)
    except Exception as exc:
        safety_issues.extend(getattr(exc,'safety_issues',[]))
        # Exception strings can contain PII/DSNs. Persist only a bounded type/code.
        summary.update(status='failed',error_type=type(exc).__name__,
            error_code=getattr(exc,'error_code','pair_failed'),
            phase=getattr(exc,'phase','coordinator'),service=getattr(exc,'service',None),
            safety_issues=safety_issues)
    atomic_json(out/'run.json',summary)
    return out


def main():
    parser=argparse.ArgumentParser(description='LIVE paired BTC text evaluation; model calls and runtime reset')
    parser.add_argument('--scenarios',type=Path,default=SERVICE/'eval_harness/scenarios')
    parser.add_argument('--btc-root',type=Path,required=True)
    parser.add_argument('--expected-database',default=os.getenv('EVAL_EXPECTED_DATABASE'))
    parser.add_argument('--agent',choices=('deep','react'),default='deep')
    parser.add_argument('--seed',type=int,default=7)
    parser.add_argument('--limit-scenarios',type=int)
    parser.add_argument('--out-root',type=Path,default=SERVICE/'eval_harness/results')
    args=parser.parse_args()
    out=asyncio.run(run_pair(scenarios=args.scenarios.resolve(),btc_root=args.btc_root.resolve(),
        agent=args.agent,seed=args.seed,out_root=args.out_root.resolve(),
        expected_database=args.expected_database,limit_scenarios=args.limit_scenarios))
    summary=json.loads((out/'run.json').read_text())
    status=summary['status']
    print(f'{status}: {out / "run.json"}')
    if status=='failed':
        print(f"phase={summary.get('phase')} code={summary.get('error_code')} service={summary.get('service')}")
    if status!='validated':
        raise SystemExit(1)


if __name__=='__main__':
    main()
