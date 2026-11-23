import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


def _scorer(btc_root):
    spec = importlib.util.spec_from_file_location('btc_semantic_reference', Path(btc_root) / 'eval/reference_eval.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _successful(call):
    result = call.get('result')
    if not isinstance(result, dict) or result.get('error') or result.get('ok') is False or result.get('success') is False:
        return False
    name = call.get('name')
    if name == 'order.create':
        return result.get('status') == 'created' and isinstance(result.get('order_id'), str) and bool(result['order_id'])
    if name == 'order.status':
        return isinstance(result.get('orders'), list) and bool(result['orders'])
    if name == 'order.update':
        return bool(result.get('order_id')) and result.get('status') in {'updated', 'pickup_scheduled'}
    if name == 'handoff.transfer':
        return result.get('status') == 'queued' and bool(result.get('ticket_id'))
    if name == 'schedule.callback':
        return bool(result.get('callback_id')) and bool(result.get('callback_at'))
    if name == 'pricing.get_quote':
        return type(result.get('final_price_vnd')) is int
    if name == 'pricing.quote_order':
        return type(result.get('total_vnd')) is int and bool(result.get('units'))
    if name == 'inventory.check':
        return type(result.get('in_stock')) is bool
    if name == 'catalog.search':
        return isinstance(result.get('items'), list)
    return result.get('ok') is True or result.get('success') is True


def _lines(calls):
    return Counter((line.get('sku'), line.get('price_vnd'))
        for call in calls for line in call.get('args', {}).get('lines', [call.get('args', {})])
        for _ in range(line.get('qty', 1)))


def check_call(spec, rows, prior_rows, *, btc_root):
    scorer = _scorer(btc_root)
    calls = [call for row in rows for call in row.get('tool_calls', [])]
    previous = [call for row in prior_rows for call in row.get('tool_calls', [])
                if call.get('name') == 'order.create' and _successful(call)]
    aliases = {call['result']['order_id'] for call in previous}
    checks = []

    def add(name, passed):
        checks.append({'name': name, 'status': 'needs_review' if passed is None else 'pass' if passed else 'fail'})

    add('trace_present', bool(rows))
    official, _ = scorer.check_call(spec, rows, aliases)
    add('btc_call_assertions', official is True)
    expected = spec.get('success_if', {}).get('tool_called')
    matching = [call for call in calls if call.get('name') == expected
                and scorer.args_match(spec.get('success_if', {}).get('args_match'), call.get('args', {}), aliases)
                and _successful(call)] if expected else []
    if expected:
        add('successful_expected_tool', bool(matching))
    if expected == 'order.status':
        requested = spec.get('success_if', {}).get('args_match', {}).get('order_id')
        targets = aliases if requested == 'generated_by_order.create' else {requested} if requested else aliases
        add('correct_order_receipt', any(order.get('order_id') in targets
            for call in matching for order in call['result']['orders']) if targets else None)
    if expected == 'order.update':
        add('updated_order_receipt', any(call['result'].get('order_id') == call.get('args', {}).get('order_id')
                                        for call in matching))
    if expected == 'handoff.transfer':
        schema = json.loads((Path(btc_root) / 'schemas/handoff_brief.schema.json').read_text())
        schema = deepcopy(schema)
        schema['properties']['customer_phone'] = {'anyOf': [schema['properties']['customer_phone'],
            {'enum': ['[PII ĐÃ ẨN]', '[SỐ ĐÃ ẨN]']}]}
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        add('handoff_schema_after_redaction', any(validator.is_valid(call.get('args', {}).get('brief'))
                                                 for call in matching))
    rules = spec.get('supplemental_checks', {})
    orders = [call for call in calls if call.get('name') == 'order.create' and _successful(call)]
    if 'order_count' in rules:
        add('order_count', len(orders) == rules['order_count'])
    if 'order_lines' in rules:
        wanted = Counter((line['sku'], line['price_vnd'])
                         for line in rules['order_lines'] for _ in range(line.get('qty', 1)))
        add('exact_order_lines', _lines(orders) == wanted)
    if spec.get('semantic_requirements'):
        add('semantic_judgment', None)
    statuses = {check['status'] for check in checks}
    return {'status': 'fail' if 'fail' in statuses else 'needs_review' if 'needs_review' in statuses else 'pass',
            'checks': checks}


def evaluate(scenarios, rows, *, btc_root):
    identities = [(row['scenario_id'], row['call'], row['turn']) for row in rows]
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate trace identity')
    for field in ('config', 'run_id'):
        if len({row.get(field) for row in rows}) > 1:
            raise ValueError('Mixed trace ' + field)
    expected = {(sid, name) for sid, scenario in scenarios.items() for name in scenario['calls']}
    if any((row['scenario_id'], row['call']) not in expected for row in rows):
        raise ValueError('Unknown scenario or call')
    results = []
    for sid, scenario in scenarios.items():
        prior = []
        for name, spec in sorted(scenario['calls'].items()):
            current = sorted([r for r in rows if (r['scenario_id'], r['call']) == (sid, name)], key=lambda r: r['turn'])
            result = check_call(spec, current, prior, btc_root=btc_root)
            results.append({'scenario_id': sid, 'call': name, **result})
            prior.extend(current)
    return {'kind': 'team_supplemental_evaluation', 'btc_score_modified': False,
            'complete': bool(results) and all(r['status'] == 'pass' for r in results),
            'counts': dict(Counter(r['status'] for r in results)), 'calls': results,
            'limitations': ['Keyword checks do not establish semantic correctness.',
                           'Redacted phone format cannot be validated against the original phone.']}


def bound_evaluation(scenarios, trace, *, btc_root):
    payload = Path(trace).read_bytes()
    rows = [json.loads(line) for line in payload.decode().splitlines() if line.strip()]
    result = evaluate(scenarios, rows, btc_root=btc_root)
    result['inputs'] = {'trace_sha256': hashlib.sha256(payload).hexdigest(),
        'scenarios_sha256': hashlib.sha256(json.dumps(scenarios, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        'scorer_sha256': hashlib.sha256((Path(btc_root) / 'eval/reference_eval.py').read_bytes()).hexdigest(),
        'handoff_schema_sha256': hashlib.sha256((Path(btc_root) / 'schemas/handoff_brief.schema.json').read_bytes()).hexdigest(),
        'validator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return result


def main():
    parser = argparse.ArgumentParser(description='Offline supplemental checks; does not change BTC scores or call models.')
    parser.add_argument('--scenarios', type=Path, required=True)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--btc-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--judge-report', type=Path)
    parser.add_argument('--human-review', type=Path)
    args = parser.parse_args()
    from eval_harness.scenario_contract import load_scenarios
    scenarios = load_scenarios(args.scenarios, btc_root=args.btc_root)
    result = bound_evaluation(scenarios, args.trace, btc_root=args.btc_root)
    if args.human_review and not args.judge_report:
        parser.error('--human-review requires --judge-report')
    if args.judge_report:
        from eval_harness.llm_judge import apply_judgments
        result = apply_judgments(result, json.loads(args.judge_report.read_text()), scenarios,
            args.trace, btc_root=args.btc_root,
            human=json.loads(args.human_review.read_text()) if args.human_review else None)
    with args.out.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'complete': result['complete'], 'counts': result['counts']}))


if __name__ == '__main__':
    main()
