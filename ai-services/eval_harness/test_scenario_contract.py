import json
from pathlib import Path
import pytest
from eval_harness.scenario_contract import load_scenarios, dataset_coverage

BTC = Path(__file__).resolve().parents[3] / 'BTC-Data-Vong1-TEAMS'


def test_rejects_empty_duplicate_or_invalid_dataset(tmp_path):
    p = tmp_path / 'cases.json'
    case = {'scenario_id': 'X', 'calls': {'call_1': {'customer_turns': ['xin chào']}}}
    for value in ([], [case, case], [{'scenario_id': 'X', 'calls': {}}]):
        p.write_text(json.dumps(value))
        with pytest.raises(ValueError):
            load_scenarios(p, btc_root=BTC)


def test_call_order_and_asr_inputs_are_explicit(tmp_path):
    p = tmp_path / 'cases.json'
    value = {'scenario_id': 'X', 'calls': {
        'call_2': {'customer_turns': ['hai'], 'days_later': 2},
        'call_1': {'customer_turns': ['một'], 'customer_turns_asr': ['mot'], 'input_mode': 'asr_transcript'}}}
    p.write_text(json.dumps(value))
    scenarios = load_scenarios(p, btc_root=BTC)
    assert list(scenarios['X']['calls']) == ['call_1', 'call_2']
    assert dataset_coverage(scenarios)['turns'] == 2
    value['calls']['call_1']['customer_turns_asr'] = []
    p.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='asr'):
        load_scenarios(p, btc_root=BTC)


@pytest.mark.parametrize('success', [
    {'max_agent_questions':-1}, {'args_match':[]}, {'trace_must_not_match':['[']},
    {'must_say_any':'wrong shape'},
])
def test_invalid_scoring_contract_is_rejected_before_runtime(tmp_path,success):
    p=tmp_path/'bad.json'
    p.write_text(json.dumps({'scenario_id':'X','calls':{'call_1':{'customer_turns':['a'],'success_if':success}}}))
    with pytest.raises(ValueError):
        load_scenarios(p,btc_root=BTC)
