"""Source checks for authored inputs; no agent, network, DB or model execution."""
from collections import Counter
from datetime import date
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import unicodedata

import pytest

from eval_harness.preflight import inspect_eval_inputs
from eval_harness.scenario_contract import load_scenarios, dataset_coverage


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BTC = Path(os.environ.get('HELD_OUT_BTC_ROOT', ROOT.parent/'BTC-Data-Vong1-TEAMS'))
CASES = {p.stem: json.loads(p.read_text()) for p in sorted((HERE/'scenarios').glob('*.json'))}
REVIEW = json.loads((HERE/'review.json').read_text())


def load_mock():
    spec = importlib.util.spec_from_file_location('held_out_btc_mock', BTC/'eval/mock_tools.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contains(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and contains(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and all(any(contains(a, e) for a in actual) for e in expected)
    return actual == expected


def shingles(text):
    folded = ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))
    words = re.findall(r'\w+', folded.replace('đ', 'd'))
    return set(zip(words, words[1:], words[2:], words[3:]))


def speech(scenario):
    return ' '.join(t for c in scenario['calls'].values() for t in c['customer_turns'])


def comparison_scenarios():
    paths = sorted((ROOT/'ai-services/eval_harness/scenarios').glob('SC*.json'))
    paths += sorted((BTC/'test_set/public_sample').glob('*.json'))
    values = [json.loads(p.read_text()) for p in paths]
    bundle = json.loads((ROOT/'ai-services/eval_harness/benchmark_dataset.json').read_text())
    values += bundle['scenarios'] if isinstance(bundle, dict) else bundle
    return values


def test_exact_requested_size_and_btc_contract():
    loaded = load_scenarios(HERE/'scenarios', btc_root=BTC)
    assert set(loaded) == {f'HO-{i:02d}' for i in range(1, 21)}
    assert Counter(len(s['calls']) for s in loaded.values()) == {2: 10, 3: 10}
    assert dataset_coverage(loaded) == {'scenarios': 20, 'calls': 50, 'turns': 150, 'hard_cases': 20}
    assert inspect_eval_inputs(HERE/'scenarios', BTC)['issues'] == []
    assert len({s['customer_phone'] for s in loaded.values()}) == 20
    assert REVIEW['review_status'] == 'human_review_pending'
    assert REVIEW['live_evaluation_performed'] is False
    assert set(REVIEW['scenarios']) == set(loaded)


@pytest.mark.parametrize('sid', CASES)
def test_customer_channel_persona_and_product_bindings(sid):
    scenario, metadata = CASES[sid], REVIEW['scenarios'][sid]
    mock = load_mock()
    customer = next(c for c in mock.CRM if c['customer_id'] == metadata['customer_id'])
    for public_key, source_key in [('customer_phone','phone'), ('customer_name','name'), ('honorific','honorific')]:
        assert scenario[public_key] == customer[source_key]
    personas = json.loads((BTC/'simulator/personas.json').read_text())['personas']
    assert scenario['persona'] in {p['persona_id'] for p in personas}
    all_skus = {p['sku'] for p in mock.PRODUCTS} | {v['variant_sku'] for p in mock.PRODUCTS for v in p['variants']}
    assert set(metadata['catalog_skus']) <= all_skus
    previous = None
    for name, call in scenario['calls'].items():
        key = {'hotline':'phone', 'zalo_oa':'zalo_id', 'chat_fanpage':'fb_id'}[call['channel']]
        assert call['channel_identity'] == customer[key] and customer[key]
        result = mock.crm_get_customer(**{key: call['channel_identity']})
        assert result['found'] and not result['ambiguous']
        assert result['customer_id'] == metadata['customer_id']
        on = date.fromisoformat(call['call_date'])
        assert call['days_later'] == ((on-previous).days if previous else 0)
        previous = on
        assert metadata['manual_checks'][name]
        assert call['success_if']
        assert isinstance(call['must_carry_over'], list) and isinstance(call['must_not_ask'], list)


@pytest.mark.parametrize('sid', CASES)
def test_factual_oracles_against_original_btc_tools(sid):
    """Preserve state between calls, especially the customer's one-use promotion."""
    mock = load_mock()
    scenario, metadata = CASES[sid], REVIEW['scenarios'][sid]
    steps = metadata['oracle_checks']
    assert steps
    assert [s['call'] for s in steps] == sorted(s['call'] for s in steps)
    observed = {}
    for step in steps:
        call = scenario['calls'][step['call']]
        function = getattr(mock, step['function'])
        args = dict(step['args'])
        parameters = inspect.signature(function).parameters
        if 'on' in parameters:
            args['on'] = call['call_date']
        if 'customer_phone' in parameters:
            args['customer_phone'] = scenario['customer_phone']
        result = function(**args)
        assert 'error' not in result, (sid, step['call'], result)
        assert contains(result, step['expected']), (sid, step['call'], step['expected'], result)
        observed.setdefault(step['call'], []).append((step['function'].replace('_','.',1), args, result))
    for name, call in scenario['calls'].items():
        criteria = call['success_if']
        tool = criteria['tool_called']
        if not tool:
            continue
        matches = []
        for actual_tool, args, result in observed.get(name, []):
            if actual_tool == tool:
                matches.extend([{**{k:v for k,v in args.items() if k != 'lines'}, **line}
                                for line in args['lines']] if tool == 'order.create' and 'lines' in args else [args])
                if 'total_match_vnd' in criteria:
                    assert result['total_vnd'] == criteria['total_match_vnd']
        assert any(contains(args, criteria.get('args_match', {})) for args in matches), (sid, name, criteria)
        if 'also_ordered' in criteria:
            assert set(criteria['also_ordered']) <= {a.get('sku') for a in matches}


@pytest.mark.parametrize('sid', CASES)
def test_policy_citations_and_memory_labels_are_grounded(sid):
    policy_ids = set()
    for path in (BTC/'policy').glob('*.md'):
        policy_ids.update(re.findall(r'^## \[([^]]+)\]', path.read_text(), re.M))
    metadata, scenario = REVIEW['scenarios'][sid], CASES[sid]
    assert metadata['source_sections'] and set(metadata['source_sections']) <= policy_ids
    established = set()
    for call in scenario['calls'].values():
        assert set(call['must_carry_over']) <= established
        assert set(call['must_not_ask']) <= established
        established.update(call['facts_established'])


def test_no_copied_scenario_or_reused_customer_from_existing_team_set():
    existing = comparison_scenarios()
    team = [json.loads(p.read_text()) for p in (ROOT/'ai-services/eval_harness/scenarios').glob('SC*.json')]
    assert {s['customer_phone'] for s in CASES.values()}.isdisjoint(s['customer_phone'] for s in team)
    assert {s['scenario_id'] for s in CASES.values()}.isdisjoint(s['scenario_id'] for s in existing)
    for sid, scenario in CASES.items():
        new = shingles(speech(scenario))
        for old in existing + [case for other_id, case in CASES.items() if other_id != sid]:
            known = shingles(speech(old))
            # A lexical copy screen, not proof of semantic independence.
            overlap = len(new & known) / len(new | known)
            assert overlap < 0.35, (sid, old['scenario_id'], overlap)
        assert len(REVIEW['scenarios'][sid]['novelty']) > 60


def test_frozen_inputs_and_sources_have_matching_hashes():
    manifest = json.loads((HERE/'manifest.json').read_text())
    for section, base in [('files',HERE), ('btc_sources',BTC), ('comparison_sources',ROOT)]:
        for name, expected in manifest[section].items():
            assert hashlib.sha256((base/name).read_bytes()).hexdigest() == expected, (section, name)
    assert set(manifest['files']) == {'review.json'} | {f'scenarios/{sid}.json' for sid in CASES}
