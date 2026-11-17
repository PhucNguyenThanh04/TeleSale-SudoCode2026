"""BTC-compatible single-trace CLI using the canonical conversation runner."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ai-services'))
from app.configs import get_settings
from app.knowledge.context import capture_release
from app.mcp_servers.mcp_shared.config import database_url
from eval.catalog_search_benchmark import catalog_search_metrics
from eval_harness import benchmark_runner as runner
from eval_harness.extractor import extract_questions as _questions, extract_claims as _claims
from eval_harness.reference_adapter import facts_used, _safe_tool_calls
from eval_harness.scenario_contract import load_scenarios
from eval_harness.official_pipeline import atomic_json


def _trace_args(args):
    """Compatibility export; masking is owned by the canonical adapter."""
    return _safe_tool_calls([{'name':'diagnostic.tool','args':args}])[0]['args']


def _facts_used(answer, state):
    return facts_used(answer, state.get('tool_calls',[]), state.get('profile',{}),
                      state.get('scoped_facts',{}), str(state['request'].session_id))


async def _require_eval_database(runtime, isolated_db, *, expected_database=None, release=None):
    if not isolated_db:
        raise ValueError('Pass --isolated-db and explicitly configure --expected-database')
    return await runner.preflight_runtime(runtime, get_settings(),
        expected_database=expected_database or os.getenv('EVAL_EXPECTED_DATABASE',''), release=release or {})


async def run(args, runtime=None) -> int:
    btc_root = getattr(args,'btc_root',None)
    if btc_root is None:
        raise ValueError('--btc-root is required')
    if not args.isolated_db:
        raise ValueError('--isolated-db is required')
    target = getattr(args,'expected_database',None) or os.getenv('EVAL_EXPECTED_DATABASE')
    if not target:
        raise ValueError('--expected-database is required')
    if args.out.exists() or args.out.with_suffix('.report.json').exists():
        raise FileExistsError('output_exists_choose_new_path')
    from eval_harness.btc_release import prepare_btc_release
    btc_root = prepare_btc_release(btc_root, args.out.with_suffix('.btc-release'))
    scenarios = load_scenarios(args.scenarios, btc_root=btc_root)
    settings = get_settings()
    settings = settings.model_copy(update={'llm_seed':getattr(args,'seed',7)})
    release = await capture_release(database_url(settings))
    sidecars_complete = False
    try:
        result = await runner.execute_configuration(settings=settings, scenarios=scenarios,config=args.config,
            runtime=runtime,run_id=str(uuid4()),out=args.out,btc_root=btc_root,
            expected_database=target,release=release)
        rows = [r for rs in result['trace'].values() for r in rs]
        report_path=args.out.with_suffix('.report.json')
        report=json.loads(report_path.read_text())
        report['catalog_search']=catalog_search_metrics(rows)
        atomic_json(getattr(args,'report_out',None) or report_path,report)
        sidecars_complete = True
        if result['status'] != 'completed':
            raise RuntimeError('invalid: redaction_affects_scoring')
        return len(rows)
    except Exception as exc:
        report_path=args.out.with_suffix('.report.json')
        report=json.loads(report_path.read_text()) if report_path.exists() else {}
        if not (sidecars_complete and report.get('status')=='invalid'):
            report.update(status='failed',error_type=type(exc).__name__)
            atomic_json(report_path,report)
            if getattr(args,'report_out',None):
                atomic_json(args.report_out,report)
        raise


def main():
    parser=argparse.ArgumentParser(description='LIVE BTC text runner; model calls and runtime reset')
    parser.add_argument('--scenarios',required=True,type=Path)
    parser.add_argument('--btc-root',required=True,type=Path)
    parser.add_argument('--config',required=True,choices=('full','baseline_no_memory'))
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--report-out',type=Path)
    parser.add_argument('--isolated-db',action='store_true')
    parser.add_argument('--expected-database',default=os.getenv('EVAL_EXPECTED_DATABASE'))
    parser.add_argument('--seed',type=int,default=7)
    args=parser.parse_args()
    try:
        count=asyncio.run(run(args))
    except FileExistsError:
        parser.exit(1,"Output already exists; choose a new --out path.\n")
    except Exception as exc:
        parser.exit(1,f'Run failed ({type(exc).__name__}); inspect safe report.\n')
    print(f'Wrote {count} real turns to {args.out}')


if __name__=='__main__':
    main()
