import argparse
import json
from pathlib import Path

from eval.score_pair import _sha, _scenario_sha
from eval.trace_audit import audit_pair, audit_trace
from eval_harness.scenario_contract import load_scenarios, dataset_coverage


def _check(name, passed, evidence):
    return {'name': name, 'status': 'missing' if passed is None else 'pass' if passed else 'fail',
            'evidence': evidence}


def _rqr_check(full, baseline, comparison):
    system = full.get('repeat_question_rate', {}).get('value')
    base = baseline.get('repeat_question_rate', {}).get('value')
    reduction = comparison.get('rqr_relative_reduction_pct')
    evidence = {'value': reduction, 'full_rqr': system, 'baseline_rqr': base,
                'requirement': 'Relative RQR reduction >=40%; BTC zero-baseline exception'}
    if base == 0 and type(system) in (int, float):
        if system == 0:
            return {'name': 'repeat_question_reduction', 'status': 'not_applicable',
                    'evidence': {**evidence, 'ccr': full.get('context_carryover_rate', {}).get('value'),
                                 'jury_review_required': True, 'note': 'BGK xét CCR thay thế.'}}
        return _check('repeat_question_reduction', False, evidence)
    passed = reduction >= 40 if type(reduction) in (int, float) and base is not None and system is not None else None
    return _check('repeat_question_reduction', passed, evidence)


def _call_brief_check(rows, expected):
    returning = [r for r in rows if r.get('turn') == 1 and r.get('call') != 'call_1']
    observed = {(r['scenario_id'], r['call']) for r in returning}
    values = [r.get('call_brief_latency_ms') for r in returning]
    complete = bool(expected) and observed == expected and len(returning) == len(expected) and all(
        type(value) is int and value >= 0 for value in values)
    maximum = max(values) if complete else None
    return _check('call_brief_max', maximum <= 5000 if complete else None,
                  {'max_ms': maximum, 'maximum_ms': 5000, 'measured': sum(
                      type(value) is int and value >= 0 for value in values), 'expected': len(expected)})


def _read(path):
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('object_required')
    return value


def _file(directory, name):
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError('artifact_name_invalid')
    path = directory / name
    if path.resolve().parent != directory.resolve():
        raise ValueError('artifact_outside_run')
    return path


def inspect_dataset(path, *, btc_root):
    scenarios = load_scenarios(Path(path), btc_root=Path(btc_root))
    multi = [s for s in scenarios.values() if len(s['calls']) >= 2]
    coverage = {**dataset_coverage(scenarios), 'multi_session_scenarios': len(multi),
                'unique_customer_phones': len({s.get('customer_phone') for s in scenarios.values()
                                              if s.get('customer_phone')})}
    returning = [c for s in multi for name, c in s['calls'].items() if name != 'call_1']
    labels = sum(all(isinstance(c.get(key), list) and all(isinstance(v, str) for v in c[key])
                     for key in ('must_carry_over', 'must_not_ask')) for c in returning)
    task_labels = sum(bool(list(s['calls'].values())[-1].get('success_if')) for s in scenarios.values())
    checks = [
        _check('multi_session_coverage', len(multi) >= 20,
               {'actual': len(multi), 'minimum': 20}),
        _check('hard_case_coverage', coverage['hard_cases'] >= 5,
               {'actual': coverage['hard_cases'], 'minimum': 5}),
        _check('memory_labels_available', bool(returning) and labels == len(returning),
               {'labelled_returning_calls': labels, 'returning_calls': len(returning),
                'note': 'Explicit empty lists are allowed when nothing should carry over; review correctness before freezing.'}),
        _check('task_labels_available', task_labels == len(scenarios),
               {'scenarios_with_final_success_criteria': task_labels, 'scenarios': len(scenarios)}),
    ]
    return {'scope': 'conversation_dataset_only', 'coverage': coverage, 'checks': checks,
            'dataset_ready': all(c['status'] == 'pass' for c in checks)}


def load_pair(directory, *, btc_root):
    directory, btc_root = Path(directory), Path(btc_root)
    run = _read(directory / 'run.json')
    if run.get('status') != 'validated':
        raise ValueError('run_not_validated')
    score_path = _file(directory, run['score'])
    inputs_path = score_path.with_suffix('.inputs.json')
    inputs = _read(inputs_path)
    score = _read(score_path)
    manifests = {key: _read(_file(directory, run['manifests'][key]))
                 for key in ('full', 'baseline_no_memory')}
    if audit_pair(manifests['full'], manifests['baseline_no_memory']):
        raise ValueError('pair_mismatch')
    scenarios = directory / 'scenarios'
    if inputs['scenario_sha256'] != _scenario_sha(scenarios):
        raise ValueError('scenario_hash_mismatch')
    if inputs['score_sha256'] != _sha(score_path):
        raise ValueError('score_hash_mismatch')
    scorer_hash = _sha(btc_root / 'eval/reference_eval.py')
    if inputs['scorer_sha256'] != scorer_hash:
        raise ValueError('scorer_hash_mismatch')
    traces, rows = {}, {}
    for key, manifest in manifests.items():
        path = _file(directory, run['traces'][key])
        trace_hash = _sha(path)
        source_key = 'full_trace_sha256' if key == 'full' else 'baseline_trace_sha256'
        if (trace_hash != manifest['trace_sha256'] or trace_hash != inputs[source_key]
                or manifest['scorer_report_sha256'] != _sha(score_path)
                or manifest['runner_report_sha256'] != _sha(path.with_suffix('.report.json'))
                or manifest['score_inputs_sha256'] != _sha(inputs_path)
                or manifest['scorer_sha256'] != scorer_hash):
            raise ValueError('artifact_hash_mismatch')
        audit = audit_trace(scenarios, path, key, btc_root=btc_root)
        if audit['errors'] or audit['rows'] != manifest['trace_rows']:
            raise ValueError('trace_audit_failed')
        traces[key] = path
        rows[key] = [json.loads(line) for line in path.read_text().splitlines()]
    return run, score, manifests, traces, rows


def inspect_run(directory, *, btc_root, extraction_review=None):
    directory = Path(directory)
    checks = []
    try:
        run, score, manifests, traces, rows = load_pair(directory, btc_root=btc_root)
        dataset = inspect_dataset(directory / 'scenarios', btc_root=btc_root)
    except (OSError, ValueError, KeyError, TypeError):
        return {'scope': 'm1_conversation_only', 'conversation_accepted': False,
                'checks': [_check('artifact_integrity', False, 'Missing, invalid or mismatched saved evidence.')],
                'remaining_evidence': ['ASR', 'reviewed_two_round_improvement', 'demo', 'cost']}
    checks.append(_check('artifact_integrity', True, 'Score, input hashes, manifests and trace schema match.'))
    checks.append(_check('complete_dataset_run', None if 'subset' not in run else run['subset'] is False,
                         'A smoke subset is not a full-dataset acceptance run.'))
    checks.extend(dataset['checks'])
    measurement = run.get('conversation_measurement', {})
    bound_measurements = [m['model_params'].get('conversation_measurement') for m in manifests.values()]
    checks.append(_check('m1_text_lifecycle', None if not measurement else
        measurement.get('delivery_mode') == 'text' and all(m == measurement for m in bound_measurements),
        'Run and both model manifests must record the same text lifecycle.'))
    checks.append(_check('guardrails_enabled', all(m.get('guardrails', {}).get('enabled') is True
                        for m in manifests.values()), 'Answer checks enabled in both configurations.'))
    try:
        from eval_harness.turn_diagnostics import verify_report_turn_diagnostics, trace_execution_health
        for path in traces.values():
            verify_report_turn_diagnostics(path)
        healthy = all(trace_execution_health(p) == 'healthy' for p in traces.values())
    except (OSError, ValueError, KeyError, TypeError):
        healthy = None
    checks.append(_check('execution_health', healthy, 'Verified per-turn model/tool execution diagnostics.'))
    extraction_evidence = 'Verified extraction report; unresolved candidates require review.'
    try:
        from eval_harness.extraction_report import verify_extraction_report
        reference = run['extraction_report']
        path = _file(directory, reference['path'])
        if _sha(path) != reference['sha256']:
            raise ValueError('extraction_hash_mismatch')
        extraction = verify_extraction_report(path)
        for config, trace in traces.items():
            score_key = 'system' if config == 'full' else 'baseline'
            if (extraction['artifacts'][config]['trace_sha256'] != _sha(trace)
                    or extraction['configs'][config]['btc_checked'] != score[score_key]):
                raise ValueError('extraction_run_binding_mismatch')
        extraction_complete = extraction['extraction_status'] == 'complete'
        if extraction_review is not None:
            from eval_harness.extraction_review import verify_review
            reviewed = verify_review(path, extraction_review)
            extraction_complete = reviewed['complete']
            extraction_evidence = {'automated_status': extraction['extraction_status'],
                'review_sha256': _sha(Path(extraction_review)), 'review': reviewed}
    except (OSError, ValueError, KeyError, TypeError):
        extraction_complete = None
    checks.append(_check('extraction_review', extraction_complete, extraction_evidence))
    full, baseline = score['system'], score['baseline']
    tsr = full.get('task_success_rate', {}).get('value')
    hr = full.get('hallucination_rate', {}).get('price_promo_only', {})
    for name, value, passes, detail in [
        ('task_success', tsr, tsr is not None and tsr >= 70, 'TSR >= 70%'),
        ('price_promo_hallucination', hr.get('value'),
         hr.get('value') is not None and hr['value'] <= 5 and hr.get('total', 0) > 0, 'HR price/promo <= 5%; nonempty denominator'),
    ]:
        checks.append(_check(name, None if value is None else passes, {'value': value, 'requirement': detail}))
    checks.append(_rqr_check(full, baseline, score.get('comparison', {})))
    violations = full.get('guardrail_violations', {}).get('total')
    checks.append(_check('safety', None if violations is None else violations == 0 and not run.get('safety_issues'),
                         {'violations': violations}))
    sample_ok = all(len(value) >= 100 for value in rows.values())
    checks.append(_check('latency_sample_size', sample_ok, {'turns': {k: len(v) for k, v in rows.items()}, 'minimum': 100}))
    warmup = {key: {'manifest': manifests[key]['model_params'].get('warmup_turns'),
                    'runner_report': _read(path.with_suffix('.report.json')).get('warmup_turns')}
              for key, path in traces.items()}
    warmup_values = [value for evidence in warmup.values() for value in evidence.values()]
    warmup_ok = all(type(value) is int and value >= 3 for value in warmup_values)
    checks.append(_check('latency_warmup', None if any(value is None for value in warmup_values)
                         else warmup_ok, {'turns': warmup, 'minimum': 3}))
    measured = (measurement.get('ttft_is_proxy') is False
                and measurement.get('ttft_basis') == 'nonstreaming_total_btc_rule_7'
                and all(r.get('latency', {}).get('ttft_is_proxy') is False
                        and r['latency']['ttft_ms'] == r['latency']['total_ms']
                        for rs in rows.values() for r in rs))
    streamed = (measurement.get('ttft_is_proxy') is False
                and measurement.get('ttft_basis') == 'streaming_guarded_answer_delta'
                and all(m['model_params'].get('streaming') is True for m in manifests.values())
                and all(_read(p.with_suffix('.report.json')).get('streaming') is True for p in traces.values())
                and all(r.get('latency', {}).get('streaming') is True
                        and r['latency'].get('ttft_is_proxy') is False
                        and r['latency'].get('stream_completed') is True
                        and type(r['latency'].get('answer_delta_count')) is int
                        and r['latency']['answer_delta_count'] >= 1
                        and type(r['latency'].get('ttft_ms')) is int
                        and type(r['latency'].get('total_ms')) is int
                        and 0 <= r['latency']['ttft_ms'] <= r['latency']['total_ms']
                        for rs in rows.values() for r in rs))
    measured = measured or streamed
    checks.append(_check('ttft_measured', True if measured else None,
                         'Streaming first answer delta, completion and timestamps bound in both arms.' if streamed else
                         'BTC rule 7: nonstreaming chat TTFT = Total; voice proxies are excluded.'))
    for name, field, limit in [('ttft_p95', 'ttft', 3000), ('total_p95', 'total', 8000)]:
        values = [m.get('latency', {}).get(field, {}).get('p95_ms') for m in (full, baseline)]
        available = (sample_ok and all(type(v) in (int, float) for v in values) and measured
                     and (field != 'total' or not streamed
                          or measurement.get('total_basis') == 'streaming_last_answer_delta'))
        checks.append(_check(name, all(v <= limit for v in values) if available else None,
                             {'p95_ms': values, 'maximum_ms': limit}))
    scenarios = load_scenarios(directory / 'scenarios', btc_root=Path(btc_root))
    expected_briefs = {(sid, name) for sid, scenario in scenarios.items()
                       for name in scenario['calls'] if name != 'call_1'}
    checks.append(_call_brief_check(rows['full'], expected_briefs))
    return {'scope': 'm1_conversation_only', 'run_id': run.get('run_id'),
            'conversation_accepted': all(c['status'] == 'pass' for c in checks),
            'coverage': dataset['coverage'], 'checks': checks,
            'remaining_evidence': ['ASR', 'reviewed_two_round_improvement', 'demo', 'cost']}


def main():
    parser = argparse.ArgumentParser(description='Read-only M1 conversation evidence checks; never run a model or rescore a run.')
    parser.add_argument('kind', choices=('run', 'dataset'))
    parser.add_argument('path', type=Path)
    parser.add_argument('--btc-root', required=True, type=Path)
    parser.add_argument('--extraction-review', type=Path,
                        help='Optional per-candidate review bound to the saved extraction report')
    args = parser.parse_args()
    try:
        if args.kind == 'dataset' and args.extraction_review is not None:
            parser.error('--extraction-review requires run evidence')
        report = (inspect_run(args.path, btc_root=args.btc_root, extraction_review=args.extraction_review)
                  if args.kind == 'run' else inspect_dataset(args.path, btc_root=args.btc_root))
    except (OSError, ValueError, KeyError, TypeError):
        parser.error('Invalid evidence or dataset contract; no inference was performed.')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get('conversation_accepted', report.get('dataset_ready', False)):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
