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
from app.agent.harness.execution_diagnostics import safe_failure_details
from app.knowledge.context import capture_release, release_context, selected_release
from app.mcp_servers.mcp_shared.config import database_url
from eval_harness.seed_fingerprint import fingerprint_btc_source
from eval_harness.scenario_contract import load_scenarios, dataset_coverage, snapshot_scenarios
from eval_harness.benchmark_runner import conversation_measurement

PROJECT = Path(__file__).resolve().parents[2]
SERVICE = PROJECT / 'ai-services'
_DECISION_ALIAS_KEY = os.urandom(32).hex()
sys.path.insert(0,str(PROJECT))
from eval.trace_audit import source_snapshot_digest
from eval_harness.official_pipeline import publish_pair, atomic_json


def require_same_seed(full_digest, baseline_digest):
    if not full_digest or full_digest != baseline_digest:
        raise ValueError('btc_source changed between full and baseline')
    return full_digest


def _run_one(config, scenarios, seed, run_id, out, *, btc_root, expected_database, release):
    scenarios, btc_root, out = (Path(path).resolve() for path in (scenarios, btc_root, out))
    report=out/f'{config}.diagnostics.json'
    env=dict(os.environ)
    env['_EVAL_PINNED_RELEASE']=json.dumps(release)
    env['_EVAL_DECISION_ALIAS_KEY'] = _DECISION_ALIAS_KEY
    env['KNOWLEDGE_RELEASE_ID']=release['release_id']
    print(f"[eval] {config}: starting", flush=True)
    completed=subprocess.run([sys.executable,'-u','-m','eval_harness.benchmark_runner',
        '--config',config,'--seed',str(seed),'--scenarios',str(scenarios),'--btc-root',str(btc_root),
        '--expected-database',expected_database,'--run-id',run_id,'--out',str(report)],
        cwd=SERVICE,env=env,stdout=None,stderr=subprocess.PIPE,text=True)
    suffix='baseline' if config in {'baseline','baseline_no_memory'} else config
    trace=report.with_name(report.stem+f'_{suffix}.jsonl')
    side=trace.with_suffix('.report.json')
    try:
        details=json.loads(side.read_text()) if side.exists() else {}
    except (OSError, ValueError):
        details={}
    if not isinstance(details, dict):
        details={}
    status=details.get('status')
    finished = completed.returncode == 0 and status == 'completed'
    invalid_for_scoring = status == 'invalid' and bool(details.get('safety_issues'))
    if not trace.is_file() or not (finished or invalid_for_scoring):
        failure=RuntimeError('configuration_execution_failed')
        failure.safety_issues=details.get('safety_issues',[])
        failure.error_code=details.get('error_code','configuration_execution_failed')
        failure.phase=details.get('phase','configuration')
        failure.service=details.get('service')
        for key,value in safe_failure_details(details).items():
            setattr(failure,key,value)
        raise failure
    return trace


def _ram_bytes():
    if hasattr(os, 'sysconf'):
        return os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')
    import ctypes
    class MemoryStatus(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[
            (name,ctypes.c_ulonglong) for name in ('total_phys','avail_phys','total_page','avail_page',
                                                    'total_virtual','avail_virtual','avail_extended')]
    status=MemoryStatus(length=ctypes.sizeof(MemoryStatus))
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.total_phys


def _dataset_digest(scenarios):
    return hashlib.sha256(json.dumps(scenarios,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


async def run_pair(*, scenarios: Path, btc_root: Path, seed: int,
                   out_root: Path, expected_database: str | None = None,
                   limit_scenarios: int | None = None, baseline_first=False) -> Path:
    measurement = conversation_measurement()
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    out=out_root/run_id
    out.mkdir(parents=True,exist_ok=False)
    summary={'run_id':run_id,'status':'running','btc_root':str(btc_root.resolve()),
             'conversation_measurement': measurement}
    atomic_json(out/'run.json',summary)
    safety_issues=[]
    try:
        from eval_harness.btc_release import prepare_btc_release, release_metadata
        btc_root = prepare_btc_release(btc_root, out / 'btc-release')
        summary.update(btc_root=str(btc_root), btc_contract=release_metadata(btc_root))
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
        for config in (('baseline', 'full') if baseline_first else ('full', 'baseline')):
            require_same_seed(seed_digest,await fingerprint_btc_source(dsn))
            with release_context(release['release_id']):
                trace=_run_one(config,selected,seed,run_id,out,
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
        provider=urlsplit(str(settings.llm_base_url)).hostname
        metadata=dict(source_digest=source_before,seed_id=f'btc-source-seed-{seed}',seed_digest=seed_digest,
            model_id=settings.llm_model,model_params={'temperature':settings.llm_temperature,
                'max_tokens':settings.llm_max_tokens,'seed':seed,'agent':'deep','provider':provider,
                'streaming':True,'warmup_turns':3,'prompt_history_turns':settings.agent_prompt_history_turns,
                'conversation_measurement': measurement, 'btc_contract': release_metadata(btc_root)},
            tool_mode='mcp',guardrails={'enabled':settings.agent_guardrails_enabled},database_identity=identity,
            hardware={'platform':platform.platform(),'machine':platform.machine(),'cpu_count':os.cpu_count(),
                      'ram_bytes':_ram_bytes()},
            started_at_utc=started,expected_database=target,app_env=settings.app_env,knowledge_release=release)
        from app.mcp_servers.mcp_shared.decision_diagnostics import enabled as decision_enabled
        decision_ref = None
        if decision_enabled():
            try:
                from eval_harness.turn_diagnostics import merge_decisions
                decision_ref = merge_decisions(traces, out / 'decision_diagnostics.jsonl')
            except Exception:
                decision_ref = {'error': 'diagnostics_merge_failed', 'complete': False}
            summary['decision_diagnostics'] = decision_ref
        print("[eval] pair: audit and BTC scoring", flush=True)
        result=publish_pair(selected,traces['full'],traces['baseline_no_memory'],out/'btc_score.json',
            metadata,btc_root=btc_root,safety_issues=safety_issues,
            extraction_sidecars={'full':out/'full.extraction.jsonl', 'baseline_no_memory':out/'baseline.extraction.jsonl'},
            require_turn_diagnostics=True, decision_diagnostics=decision_ref)
        if result['status'] == 'validated':
            from eval_harness.extraction_report import verify_extraction_report, sha256
            reference = result['extraction_report']
            if reference['path'] != 'extraction_report.json' or sha256(out/reference['path']) != reference['sha256']:
                raise ValueError('Extraction summary reference mismatch')
            report = verify_extraction_report(out/reference['path'])
            if result['extraction_status'] != report['extraction_status']:
                raise ValueError('Extraction status mismatch')
            from eval_harness.turn_diagnostics import verify_report_turn_diagnostics
            turn_refs=result['turn_diagnostics']
            if set(turn_refs)!=set(traces):
                raise ValueError('Missing configuration turn diagnostics')
            for config,trace in traces.items():
                if verify_report_turn_diagnostics(trace)!=turn_refs[config]:
                    raise ValueError('Turn diagnostic reference mismatch')
            summary.update(extraction_report=reference, extraction_status=report['extraction_status'],
                           turn_diagnostics=turn_refs)
        if result.get('supplemental_evaluation'):
            summary['supplemental_evaluation'] = result['supplemental_evaluation']
        print(f"[eval] execution health: {result.get('execution_health', 'unknown')}", flush=True)
        summary.update(status=result['status'], execution_health=result.get('execution_health','unknown'),
            score='btc_score.json' if result['status']=='validated' else None,
            manifests={key:f'{key}.manifest.json' for key in result['manifests']},
            traces={key:path.name for key,path in traces.items()},scenarios=str(selected.resolve()),
            scenario_groups={sid:sc.get('level','Khác') for sid,sc in inputs.items()},
            coverage=dataset_coverage(inputs),subset=limit_scenarios is not None,
            latency_scale_sufficient=dataset_coverage(inputs)['turns']>=100,
            safety_issues=safety_issues)
    except (Exception, SystemExit) as exc:
        safety_issues.extend(getattr(exc,'safety_issues',[]))
        summary.update(status='failed',error_type=type(exc).__name__,
            error_code=getattr(exc,'error_code',
                'unexpected_process_exit' if isinstance(exc, SystemExit) else 'pair_failed'),
            phase=getattr(exc,'phase','coordinator'),service=getattr(exc,'service',None),
            **safe_failure_details(exc),
            safety_issues=safety_issues)
    atomic_json(out/'run.json',summary)
    if summary['status'] == 'validated':
        from eval_harness.m1_acceptance import inspect_run
        atomic_json(out/'m1_conversation_acceptance.json', inspect_run(out, btc_root=btc_root))
    return out


def main():
    parser=argparse.ArgumentParser(description='LIVE paired BTC text evaluation; model calls and runtime reset')
    parser.add_argument('--scenarios',type=Path,default=PROJECT/'eval/scenario_final')
    parser.add_argument('--btc-root',type=Path,required=True)
    parser.add_argument('--expected-database',default=os.getenv('EVAL_EXPECTED_DATABASE'))
    parser.add_argument('--decision-diagnostics', action='store_true', help='Capture safe decision evidence; remote memory/worker need EVAL_DECISION_DIAGNOSTICS=1')
    parser.add_argument('--seed',type=int,default=7)
    parser.add_argument('--limit-scenarios',type=int)
    parser.add_argument('--out-root',type=Path,default=SERVICE/'eval_harness/results')
    from eval_harness.asr_evidence import add_asr_arguments, asr_sources_from_args, collect_asr_evidence
    add_asr_arguments(parser)
    args=parser.parse_args()
    try:
        sources = asr_sources_from_args(args)
        asr = collect_asr_evidence(sources, btc_root=args.btc_root) if sources else None
        if asr is not None and any(not group['report']['input_integrity'] for group in asr['groups'].values()):
            raise ValueError('asr_input_integrity_failed')
    except (OSError, ValueError, KeyError, TypeError):
        parser.error('Invalid saved ASR evidence/options; no agent evaluation was started.')
    if args.decision_diagnostics:
        os.environ['EVAL_DECISION_DIAGNOSTICS'] = '1'
    out=asyncio.run(run_pair(scenarios=args.scenarios.resolve(),btc_root=args.btc_root.resolve(),
        seed=args.seed,out_root=args.out_root.resolve(),
        expected_database=args.expected_database,limit_scenarios=args.limit_scenarios))
    summary=json.loads((out/'run.json').read_text())
    status=summary['status']
    print(f'{status}: {out / "run.json"}')
    if status=='failed':
        print(f"phase={summary.get('phase')} code={summary.get('error_code')} service={summary.get('service')}")
        if summary.get('verification_rejections'):
            print('Verification rejected: ' + ', '.join(summary['verification_rejections']))
    if status!='validated':
        raise SystemExit(1)
    if asr is not None:
        atomic_json(out/'asr_evidence.json', asr)
    from eval_harness.report_metrics import render_run
    print(render_run(out))
    from eval_harness.knowledge_followup import detect_after_pair
    try:
        asyncio.run(detect_after_pair(out))
    except (Exception, SystemExit) as exc:
        print(f'[knowledge] Detection failed ({type(exc).__name__}); paired metrics are complete. Inspect {out}.knowledge/experiment.json.', flush=True)
        raise SystemExit(1) from None


if __name__=='__main__':
    main()
