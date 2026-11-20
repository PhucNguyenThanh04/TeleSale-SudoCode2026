import copy
import hashlib
import json
import subprocess
import sys

import pytest

from eval_harness.tool_accuracy import score_trace


def row(turn=1, calls=None, text='Kiểm tồn size 42 giúp tôi'):
    return {'scenario_id': 'S1', 'call': 'call_1', 'turn': turn,
            'user_text': text, 'tool_calls': calls or []}


def label(turn=1, expected=None, text='Kiểm tồn size 42 giúp tôi'):
    return {'id': f'case-{turn}', 'scenario_id': 'S1', 'call': 'call_1', 'turn': turn,
            'user_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'scored_tools': ['inventory.check', 'order.create'],
            'expected_calls': expected or []}


def labels(*cases):
    return {'schema_version': 1, 'label_source': 'synthetic_fixture', 'cases': list(cases)}


def call(name='inventory.check', **args):
    return {'name': name, 'args': args, 'result': {'error': 'timeout'}}


def test_accuracy_counts_missing_wrong_extra_and_abstention():
    expected = [{'name': 'inventory.check', 'args_match': {'sku': 'SKU-42'}}]
    rows = [row(1, [call(sku='SKU-42')]), row(2),
            row(3, [call(sku='SKU-43')]), row(4, [call('order.create', sku='SKU-42')]),
            row(5), row(6, [call(sku='SKU-42'), call(sku='SKU-42')])]
    report = score_trace(rows, labels(*(label(n, expected if n in (1, 2, 3, 6) else [])
                                       for n in range(1, 7))))
    assert report['tool_call_accuracy'] == {'passed': 2, 'total': 6, 'percent': 33.33}
    assert report['calls'] == {'matched': 2, 'missing': 2, 'unexpected': 3}
    assert report['cases'][0]['passed']
    assert report['cases'][1]['missing_expected_indexes'] == [0]
    assert report['cases'][2]['unexpected_actual_indexes'] == [0]
    assert report['cases'][5]['unexpected_actual_indexes'] == [1]


def test_maximum_one_to_one_matching_and_nested_args():
    expected = [{'name': 'order.create', 'args_match': {}},
                {'name': 'order.create', 'args_match': {'items': [{'sku': 'A', 'qty': 1}]}}]
    actual = [call('order.create', items=[{'sku': 'A', 'qty': 1, 'price_vnd': 100}]),
              call('order.create', items=[{'sku': 'B', 'qty': 1}])]
    report = score_trace([row(calls=actual)], labels(label(expected=expected)))
    assert report['tool_call_accuracy']['percent'] == 100
    assert report['name_only_expectations'] == 1
    actual[0]['args']['items'][0]['qty'] = True
    assert score_trace([row(calls=actual)], labels(label(expected=expected)))['calls']['missing'] == 1


def test_reports_partial_coverage_and_ignores_only_out_of_scope_tools():
    rows = [row(calls=[call('catalog.search', query='máy'), call(sku='A')]), row(2)]
    case = label(expected=[{'name': 'inventory.check', 'args_match': {'sku': 'A'}}])
    report = score_trace(rows, labels(case))
    assert report['coverage'] == {'trace_turns': 2, 'labeled_turns': 1, 'unlabeled_turns': 1,
                                  'out_of_scope_calls_on_labeled_turns': 1}
    assert report['cases'][0]['scored_tools'] == case['scored_tools']
    assert report['cases'][0]['matched_calls'] == [{'expected_index': 0, 'actual_index': 1}]
    assert 'Kiểm tồn' not in json.dumps(report, ensure_ascii=False)
    assert 'máy' not in json.dumps(report, ensure_ascii=False)


@pytest.mark.parametrize('mutation', ['duplicate_trace', 'duplicate_label', 'missing_turn',
                                    'question_hash', 'mixed_config', 'mixed_run',
                                    'invalid_calls', 'invalid_args', 'unknown_label_field',
                                    'unscored_expectation', 'empty_labels', 'bool_turn', 'invalid_version'])
def test_invalid_inputs_are_rejected(mutation):
    rows, data = [row()], labels(label())
    if mutation == 'duplicate_trace': rows.append(copy.deepcopy(rows[0]))
    if mutation == 'duplicate_label': data['cases'].append(copy.deepcopy(data['cases'][0]))
    if mutation == 'missing_turn': data['cases'][0]['turn'] = 9
    if mutation == 'question_hash': rows[0]['user_text'] = 'Câu hỏi khác'
    if mutation == 'mixed_config': rows = [dict(row(), config='full'), dict(row(2), config='baseline_no_memory')]
    if mutation == 'mixed_run': rows = [dict(row(), run_id='one'), dict(row(2), run_id='two')]
    if mutation == 'invalid_calls': rows[0]['tool_calls'] = None
    if mutation == 'invalid_args': rows[0]['tool_calls'] = [{'name': 'order.create', 'args': []}]
    if mutation == 'unknown_label_field': data['cases'][0]['expected_tool'] = 'order.create'
    if mutation == 'unscored_expectation': data['cases'][0]['expected_calls'] = [{'name': 'order.update', 'args_match': {}}]
    if mutation == 'empty_labels': data['cases'] = []
    if mutation == 'bool_turn': rows[0]['turn'] = True
    if mutation == 'invalid_version': data['schema_version'] = True
    with pytest.raises(ValueError): score_trace(rows, data)


def test_cli_outputs_bound_reports_and_refuses_overwrite(tmp_path):
    trace, annotations, out = tmp_path/'trace.jsonl', tmp_path/'labels.json', tmp_path/'out'
    trace.write_text(json.dumps(row()) + '\n')
    annotations.write_text(json.dumps(labels(label())))
    args = [sys.executable, '-m', 'eval_harness.tool_accuracy', '--trace', str(trace),
            '--labels', str(annotations), '--out', str(out)]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads((out/'report.json').read_text())
    assert report['inputs']['trace_sha256'] == hashlib.sha256(trace.read_bytes()).hexdigest()
    assert report['inputs']['labels_sha256'] == hashlib.sha256(annotations.read_bytes()).hexdigest()
    assert (out/'report.md').is_file()
    original = (out/'report.json').read_bytes()
    assert subprocess.run(args, capture_output=True).returncode != 0
    assert (out/'report.json').read_bytes() == original


@pytest.mark.parametrize('bad_json', ['{"schema_version":1,"schema_version":2}',
                                    '{"number":NaN}', '{"number":Infinity}'])
def test_cli_rejects_ambiguous_json_without_output(tmp_path, monkeypatch, bad_json):
    from eval_harness import tool_accuracy
    trace, annotations, out = tmp_path/'trace.jsonl', tmp_path/'labels.json', tmp_path/'out'
    trace.write_text(json.dumps(row()) + '\n')
    annotations.write_text(bad_json)
    monkeypatch.setattr(sys, 'argv', ['tca', '--trace', str(trace), '--labels', str(annotations), '--out', str(out)])
    with pytest.raises(SystemExit) as exc:
        tool_accuracy.main()
    assert exc.value.code == 2
    assert not out.exists()


def test_shipped_fixture_has_known_partial_success():
    from pathlib import Path
    folder = Path(__file__).with_name('fixtures')/'tool_accuracy'
    rows = [json.loads(line) for line in (folder/'trace.jsonl').read_text().splitlines()]
    report = score_trace(rows, json.loads((folder/'labels.json').read_text()))
    assert report['tool_call_accuracy'] == {'passed': 3, 'total': 6, 'percent': 50.0}
    assert report['calls'] == {'matched': 2, 'missing': 2, 'unexpected': 2}
