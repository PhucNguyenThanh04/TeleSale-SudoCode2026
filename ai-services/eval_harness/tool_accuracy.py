"""Offline, explicitly scoped tool-decision accuracy; independent of BTC scores."""
import argparse
import hashlib
import json
from pathlib import Path
import re


TOOL = re.compile(r'[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*')
CASE_FIELDS = {'id', 'scenario_id', 'call', 'turn', 'user_text_sha256',
               'scored_tools', 'expected_calls'}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _locator(value):
    _require(isinstance(value, dict), 'turn_invalid')
    _require(isinstance(value.get('scenario_id'), str) and value['scenario_id'].strip(), 'scenario_id_invalid')
    _require(isinstance(value.get('call'), str) and re.fullmatch(r'call_[1-9][0-9]*', value['call']), 'call_invalid')
    _require(type(value.get('turn')) is int and value['turn'] > 0, 'turn_number_invalid')
    return value['scenario_id'], value['call'], value['turn']


def _name(value):
    return isinstance(value, str) and TOOL.fullmatch(value) is not None


def _contains(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _contains(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            _contains(e, a) for e, a in zip(expected, actual))
    return type(expected) is type(actual) and expected == actual


def _match(expected, actual):
    """Maximum bipartite match: broad expectations cannot steal narrow matches."""
    candidates = [[i for i, call in enumerate(actual) if item['name'] == call['name']
                   and _contains(item['args_match'], call['args'])] for item in expected]
    owners = {}

    def assign(index, visited):
        for candidate in candidates[index]:
            if candidate in visited:
                continue
            visited.add(candidate)
            if candidate not in owners or assign(owners[candidate], visited):
                owners[candidate] = index
                return True
        return False

    for index in range(len(expected)):
        assign(index, set())
    return {expected_index: actual_index for actual_index, expected_index in owners.items()}


def score_trace(rows: list[dict], labels: dict) -> dict:
    _require(isinstance(labels, dict) and set(labels) == {'schema_version', 'label_source', 'cases'}, 'labels_fields_invalid')
    _require(type(labels['schema_version']) is int and labels['schema_version'] == 1, 'labels_version_invalid')
    _require(isinstance(labels['label_source'], str) and labels['label_source'].strip(), 'label_source_required')
    _require(isinstance(labels['cases'], list) and labels['cases'], 'labels_empty')
    _require(isinstance(rows, list) and rows, 'trace_empty')
    indexed, identities = {}, set()
    for row in rows:
        key = _locator(row)
        _require(key not in indexed, 'trace_duplicate_turn')
        _require(isinstance(row.get('user_text'), str) and row['user_text'].strip(), 'trace_user_text_required')
        _require(isinstance(row.get('tool_calls'), list), 'trace_tool_calls_invalid')
        for call in row['tool_calls']:
            _require(isinstance(call, dict) and _name(call.get('name'))
                     and isinstance(call.get('args'), dict), 'trace_tool_call_invalid')
        identity = tuple(row.get(k) for k in ('config', 'run_id'))
        _require(all(v is None or isinstance(v, str) for v in identity), 'trace_identity_invalid')
        identities.add(identity)
        indexed[key] = row
    _require(len(identities) == 1, 'trace_mixed_run_or_config')
    # Reject NaN/Infinity in labels, including when called directly rather than via CLI.
    json.dumps(labels, allow_nan=False)
    results, seen, ids = [], set(), set()
    totals = {'matched': 0, 'missing': 0, 'unexpected': 0}
    ignored, name_only = 0, 0
    for case in labels['cases']:
        _require(isinstance(case, dict) and set(case) == CASE_FIELDS, 'case_fields_invalid')
        key = _locator(case)
        _require(isinstance(case['id'], str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', case['id']), 'case_id_invalid')
        _require(key not in seen and case['id'] not in ids, 'labels_duplicate_case')
        seen.add(key)
        ids.add(case['id'])
        _require(key in indexed, 'labeled_turn_missing_from_trace')
        row = indexed[key]
        _require(isinstance(case['user_text_sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', case['user_text_sha256']), 'question_hash_invalid')
        _require(hashlib.sha256(row['user_text'].encode()).hexdigest() == case['user_text_sha256'], 'question_hash_mismatch')
        scope = case['scored_tools']
        _require(isinstance(scope, list) and scope and all(_name(n) for n in scope)
                 and len(set(scope)) == len(scope), 'scored_tools_invalid')
        expected = case['expected_calls']
        _require(isinstance(expected, list), 'expected_calls_invalid')
        for item in expected:
            _require(isinstance(item, dict) and set(item) == {'name', 'args_match'}
                     and _name(item['name']) and item['name'] in scope
                     and isinstance(item['args_match'], dict), 'expected_call_invalid')
        observed = [(i, c) for i, c in enumerate(row['tool_calls']) if c['name'] in scope]
        ignored += len(row['tool_calls']) - len(observed)
        name_only += sum(not item['args_match'] for item in expected)
        matched = _match(expected, [c for _, c in observed])
        missing = sorted(set(range(len(expected))) - matched.keys())
        unexpected = [original for i, (original, _) in enumerate(observed) if i not in matched.values()]
        totals['matched'] += len(matched)
        totals['missing'] += len(missing)
        totals['unexpected'] += len(unexpected)
        results.append({'id': case['id'], 'scenario_id': key[0], 'call': key[1], 'turn': key[2],
            'scored_tools': scope, 'passed': not missing and not unexpected,
            'matched_calls': [{'expected_index': e, 'actual_index': observed[a][0]} for e, a in sorted(matched.items())],
            'missing_expected_indexes': missing, 'unexpected_actual_indexes': unexpected})
    passed = sum(case['passed'] for case in results)
    return {'kind': 'offline_labeled_tool_decision_accuracy', 'schema_version': 1,
        'label_source': labels['label_source'],
        'formula': '100 * exactly_matched_labeled_turns / labeled_turns',
        'tool_call_accuracy': {'passed': passed, 'total': len(results), 'percent': round(100*passed/len(results), 2)},
        'calls': totals, 'name_only_expectations': name_only,
        'coverage': {'trace_turns': len(rows), 'labeled_turns': len(results),
            'unlabeled_turns': len(rows)-len(results), 'out_of_scope_calls_on_labeled_turns': ignored},
        'cases': results,
        'limitations': ['Team-defined metric, not a replacement for BTC TSR or other official scores.',
            'Only labeled turns and their scored_tools are evaluated; unscored calls are not correct calls.',
            'Args use recursive subset matching; lists preserve order; scalar types must match.',
            'Tool order and result/execution success are not evaluated.',
            'Label-source metadata is a declaration, not evidence of independent human review.']}


def render_report(report):
    metric, coverage = report['tool_call_accuracy'], report['coverage']
    lines = ['# Tool-Call Accuracy (labeled decisions)', '',
        f"TCA: {metric['percent']}% ({metric['passed']}/{metric['total']} labeled turns).", '',
        f"Coverage: {coverage['labeled_turns']}/{coverage['trace_turns']} trace turns; "
        f"{coverage['out_of_scope_calls_on_labeled_turns']} calls outside labeled scope.", '',
        '| Case | Passed | Missing calls | Unexpected calls |', '|---|---|---:|---:|']
    for case in report['cases']:
        lines.append(f"| {case['id']} | {case['passed']} | {len(case['missing_expected_indexes'])} | {len(case['unexpected_actual_indexes'])} |")
    lines += ['', *report['limitations']]
    return '\n'.join(lines) + '\n'


def _json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'json_duplicate_key')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('json_nonfinite_number')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.out.exists():
            raise FileExistsError('Choose a new output directory')
        trace, labels = args.trace.read_bytes(), args.labels.read_bytes()
        rows = [_json(line) for line in trace.decode('utf-8').splitlines() if line.strip()]
        report = score_trace(rows, _json(labels.decode('utf-8')))
        report['inputs'] = {'trace_sha256': hashlib.sha256(trace).hexdigest(),
                            'labels_sha256': hashlib.sha256(labels).hexdigest()}
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (args.out/'report.md').write_text(render_report(report), encoding='utf-8')
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f'Offline scoring rejected ({type(exc).__name__}); check inputs and choose a new output directory.\n')
    print(f"TCA {report['tool_call_accuracy']['percent']}% — {args.out/'report.md'}")


if __name__ == '__main__':
    main()
