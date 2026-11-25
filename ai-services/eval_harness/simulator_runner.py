import argparse
import asyncio
from datetime import date, datetime, timezone
import hashlib
import json
import os
import platform
from pathlib import Path
from uuid import uuid4

from eval_harness.benchmark_runner import run_scenario_call, scenario_call_date
from eval_harness.customer_simulator import CustomerSimulator, LLMObserver, summarize_runs
from eval_harness.semantic_eval import _scorer, _successful, evaluate


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def simulate_configuration(runtime, scenarios, *, btc_root, seed, config, run_id,
                                 observer, wait_for_jobs=None, capture_writes=None,
                                 on_row=None, on_log=None):
    if config not in {'full', 'baseline_no_memory'}:
        raise ValueError('Unsupported configuration')
    runtime.memory.include_prior = config == 'full'
    scorer = _scorer(btc_root)
    traces, logs = [], []
    safety_issues = []
    for sid, scenario in scenarios.items():
        prior_rows, prior_facts = [], {}
        for name, spec in sorted(scenario['calls'].items()):
            on = scenario_call_date(scenario['calls'], name, date(2026, 10, 15))
            from eval_harness.seed_history import SeedHistoryGateway, parse_seed_history
            if isinstance(getattr(runtime, 'tools', None), SeedHistoryGateway):
                identities = {c.get('channel', 'hotline'): c.get('channel_identity', scenario['customer_phone'])
                              for c in scenario['calls'].values()}
                runtime.tools.select(sid, identities, parse_seed_history(spec.get('seed_history', []), call_date=on))
            simulator = CustomerSimulator(scenario, name, btc_root=btc_root, seed=seed,
                                          prior_facts=prior_facts, observer=observer)
            rows = await run_scenario_call(runtime, sid, name, spec, on, scenario['customer_phone'],
                call_date=on, customer_name=scenario.get('customer_name'), run_id=run_id, config=config,
                customer_simulator=simulator, wait_for_jobs=wait_for_jobs, capture_writes=capture_writes,
                on_row=on_row, safety_issues=safety_issues)
            aliases = {call['result']['order_id'] for row in prior_rows for call in row.get('tool_calls', [])
                       if call.get('name') == 'order.create' and _successful(call)}
            passed, _ = scorer.check_call(spec, rows, aliases)
            log = {**simulator.log(), 'config': config,
                   'task_success': bool(rows) and passed is True and not any(r.get('memory_error') for r in rows)}
            logs.append(log)
            if on_log:
                on_log(log)
            traces.extend(rows)
            prior_rows.extend(rows)
            prior_facts.update(spec.get('facts_established', {}))
    schema = json.loads((Path(btc_root) / 'schemas/trace_log.schema.json').read_text())
    from jsonschema import Draft202012Validator
    validator = Draft202012Validator(schema)
    if any(not validator.is_valid(row) for row in traces):
        raise ValueError('Invalid simulator trace schema')
    return {'trace': traces, 'logs': logs, 'safety_issues': safety_issues,
            'btc_style_score': scorer.evaluate(scenarios,
                {(sid, name): [r for r in traces if (r['scenario_id'], r['call']) == (sid, name)]
                 for sid, scenario in scenarios.items() for name in scenario['calls']}),
            'supplemental': evaluate(scenarios, traces, btc_root=btc_root)}


async def run_experiment(args):
    from app.configs import Settings
    from app.agent.factory import build_runtime
    from app.infarstructure.llm import build_llm
    from app.knowledge.context import capture_release, release_context
    from app.mcp_servers.mcp_shared.config import database_url
    from eval.trace_audit import source_snapshot_digest
    from eval_harness.benchmark_runner import (preflight_runtime, prepare_runtime_for_eval,
        warm_up_configuration, WarmupGateway, wait_for_distillation, read_distillation_writes)
    from eval_harness.btc_release import prepare_btc_release
    from eval_harness.official_pipeline import atomic_json, atomic_bytes
    from eval_harness.seed_fingerprint import fingerprint_btc_source
    from eval_harness.seed_history import SeedHistoryGateway
    from eval_harness.scenario_contract import load_scenarios, snapshot_scenarios
    settings = Settings().model_copy(update={'langfuse_capture_content': False})
    if settings.app_env == 'production' or not args.expected_database:
        raise ValueError('Explicit non-production evaluation database required')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    summary = {'kind': 'customer_simulator_experiment', 'status': 'running', 'seeds': args.seeds,
               'created_at_utc': datetime.now(timezone.utc).isoformat(), 'runs': [],
               'limitations': ['Adaptive customer turns differ between configurations; this is not the deterministic BTC paired run.',
                   'TSR here uses BTC assertions, not a semantic quality verdict.',
                   'Prior customer knowledge follows declared facts; interrupted earlier calls require manual review of carry-over expectations.']}
    atomic_json(out / 'run.json', summary)
    try:
        btc_root = prepare_btc_release(args.btc_root, out / 'btc-release')
        scenarios = load_scenarios(args.scenarios, btc_root=btc_root)
        snapshot_scenarios(scenarios, out / 'scenarios')
        summary['scenario_digest'] = _digest(scenarios)
        source = source_snapshot_digest(Path(__file__).resolve().parents[2])
        release = await capture_release(database_url(settings))
        source_seed = await fingerprint_btc_source(database_url(settings))
        summary.update(source_digest=source, btc_seed_digest=source_seed, knowledge_release=release,
                       agent={'model': settings.llm_model, 'temperature': settings.llm_temperature,
                              'max_tokens': settings.llm_max_tokens},
                       simulator={'model': settings.llm_model, 'temperature': 0.3})
        summary['hardware'] = {'platform': platform.platform(), 'cpu_count': os.cpu_count()}
        database_identity = None
        all_logs = []
        for seed in args.seeds:
            current_settings = settings.model_copy(update={'llm_seed': seed})
            observer = LLMObserver(build_llm(current_settings.model_copy(update={'llm_temperature': 0.3})))
            for config in ('full', 'baseline_no_memory'):
                if source_seed != await fingerprint_btc_source(database_url(settings)):
                    raise ValueError('BTC source seed changed')
                folder = out / f'seed-{seed}' / config
                folder.mkdir(parents=True)
                runtime = build_runtime(current_settings)
                runtime = build_runtime(current_settings, gateway=SeedHistoryGateway(runtime.tools))
                run_id = uuid4().hex
                with release_context(release['release_id']):
                    identity = await preflight_runtime(runtime, current_settings,
                        expected_database=args.expected_database, release=release)
                    if database_identity is not None and identity != database_identity:
                        raise ValueError('Database identity changed between configurations')
                    database_identity = identity
                    summary['database_identity'] = identity
                    warm = build_runtime(current_settings, gateway=WarmupGateway(runtime.tools))
                    if getattr(warm, 'nodes', None) is not None:
                        warm.nodes.safe_fallback_on_rejection = False
                    warm.memory.include_prior = config == 'full'
                    await warm_up_configuration(warm)
                    await prepare_runtime_for_eval(runtime, current_settings,
                        expected_database=args.expected_database, release=release)
                    with (folder / 'trace.jsonl').open('x') as stream, (folder / 'simulator.jsonl').open('x') as log_stream:
                        def append(row):
                            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                            stream.flush()
                        def append_log(row):
                            log_stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                            log_stream.flush()
                        result = await simulate_configuration(runtime, scenarios, btc_root=btc_root,
                            seed=seed, config=config, run_id=run_id, observer=observer,
                            wait_for_jobs=lambda source_id: wait_for_distillation(database_url(settings), source_id),
                            capture_writes=lambda ids: read_distillation_writes(database_url(settings), ids),
                            on_row=append, on_log=append_log)
                    atomic_bytes(folder / 'trace.jsonl', ''.join(
                        json.dumps(row, ensure_ascii=False) + '\n' for row in result['trace']).encode())
                    if result['safety_issues']:
                        raise ValueError('Trace redaction affects scoring')
                for name in ('btc_style_score', 'supplemental'):
                    atomic_json(folder / (name + '.json'), result[name])
                all_logs.extend(result['logs'])
                summary['runs'].append({'seed': seed, 'config': config, 'run_id': run_id,
                    'artifacts': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}})
                atomic_json(out / 'run.json', summary)
        if source != source_snapshot_digest(Path(__file__).resolve().parents[2]):
            raise ValueError('Evaluation source changed')
        if summary['scenario_digest'] != _digest(load_scenarios(args.scenarios, btc_root=btc_root)):
            raise ValueError('Scenario source changed')
        if source_seed != await fingerprint_btc_source(database_url(settings)):
            raise ValueError('BTC source seed changed')
        expected = {(sid, name) for sid, scenario in scenarios.items() for name in scenario['calls']}
        summary['repeatability'] = {config: summarize_runs([r for r in all_logs if r['config'] == config],
            seeds=args.seeds, expected_calls=expected) for config in ('full', 'baseline_no_memory')}
        summary['status'] = 'completed'
        summary['semantic_review_complete'] = False
    except Exception as exc:
        summary.update(status='failed', error_type=type(exc).__name__)
        atomic_json(out / 'run.json', summary)
        raise RuntimeError('simulator_execution_failed; inspect run.json') from None
    atomic_json(out / 'run.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description='LIVE customer simulator: model calls and evaluation database reset for three seeds.')
    parser.add_argument('--scenarios', type=Path, required=True)
    parser.add_argument('--btc-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--expected-database', required=True)
    parser.add_argument('--seeds', default='7,17,27')
    parser.add_argument('--allow-model-calls', action='store_true')
    args = parser.parse_args()
    if not args.allow_model_calls:
        parser.error('Explicit --allow-model-calls is required; this command calls models and resets runtime.')
    try:
        args.seeds = [int(value) for value in args.seeds.split(',')]
        if len(args.seeds) != 3 or len(set(args.seeds)) != 3:
            raise ValueError('three distinct seeds required')
        summary = asyncio.run(run_experiment(args))
    except (ValueError, RuntimeError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({'status': summary['status'], 'repeatability': summary['repeatability']}))


if __name__ == '__main__':
    main()
