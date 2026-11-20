from copy import deepcopy
import json

import pytest

from speech.replay import _seal
from speech.tts import file_sha256


def replay_fixture(tmp_path):
    bundle = tmp_path / 'bundle'
    (bundle / 'audio').mkdir(parents=True)
    turns, files = [], []
    for index in (1, 2):
        audio = bundle / 'audio' / f'S{index}-2.wav'
        audio.write_bytes(b'offline clip fixture')
        files.append(audio)
        turns.append({'conversation_key': 'conversation', 'session_key': f'S{index}',
            'session_index': index, 'identity_ref': 'customer', 'call_date': f'2026-10-{14 + index}',
            'turn_index': 1, 'source_turn_index': 2, 'text': f'ASR customer {index}',
            'customer_input_mode': 'asr_transcript', 'audio_sha256': file_sha256(audio)})
    path = bundle / 'turns.jsonl'
    path.write_text(''.join(json.dumps(t) + '\n' for t in turns))
    _seal(bundle, 'replay', [path, *files], {'status': 'ready', 'turn_count': 2})
    scenarios = {'CASE': {'scenario_id': 'CASE', 'customer_phone': '0900000000',
        'calls': {'call_1': {'customer_turns': ['GOLD first'], 'call_date': '2026-10-15'},
                  'call_2': {'customer_turns': ['GOLD second'], 'days_later': 1,
                             'must_carry_over': ['product_advised']}}}}
    bindings = {'schema_version': 1, 'identities': {'customer': 'CASE'}, 'sessions': [
        {'scenario_id': 'CASE', 'call': f'call_{i}', 'session_key': f'S{i}'} for i in (1, 2)]}
    return bundle, scenarios, bindings


def test_verified_asr_replay_attaches_recognized_customer_speech_without_mutation(tmp_path):
    from eval_harness.asr_inputs import attach_replay
    from eval_harness.scenario_contract import input_turns
    bundle, scenarios, bindings = replay_fixture(tmp_path)
    original = deepcopy(scenarios)
    result = attach_replay(scenarios, bundle, bindings)
    assert scenarios == original
    for index in (1, 2):
        call = result['CASE']['calls'][f'call_{index}']
        assert input_turns(call) == [f'ASR customer {index}']
        assert call['input_mode'] == 'asr_transcript'
        assert call['asr_provenance']['bundle_sha256']
    assert result['CASE']['calls']['call_2']['must_carry_over'] == ['product_advised']


@pytest.mark.parametrize('damage', ['date', 'identity', 'count', 'duplicate', 'missing', 'audio'])
def test_bad_replay_binding_is_rejected_before_any_runtime_access(tmp_path, damage):
    from eval_harness.asr_inputs import attach_replay
    bundle, scenarios, bindings = replay_fixture(tmp_path)
    if damage == 'date':
        scenarios['CASE']['calls']['call_2']['days_later'] = 2
    elif damage == 'identity':
        bindings['identities']['customer'] = 'OTHER'
    elif damage == 'count':
        scenarios['CASE']['calls']['call_1']['customer_turns'].append('extra')
    elif damage == 'duplicate':
        bindings['sessions'][1]['session_key'] = 'S1'
    elif damage == 'missing':
        bindings['sessions'].pop()
    else:
        (bundle / 'audio/S1-2.wav').write_bytes(b'tampered')
    with pytest.raises(ValueError):
        attach_replay(scenarios, bundle, bindings)
