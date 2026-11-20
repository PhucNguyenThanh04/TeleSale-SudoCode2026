import argparse
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path

from eval.score_pair import _sha
from eval_harness.scenario_contract import load_scenarios, snapshot_scenarios


def attach_replay(scenarios, bundle, bindings):
    from speech.replay import verify_bundle
    bundle = Path(bundle)
    verify_bundle(bundle, 'replay')
    if (not isinstance(bindings, dict) or set(bindings) != {'schema_version', 'identities', 'sessions'}
            or type(bindings['schema_version']) is not int or bindings['schema_version'] != 1
            or not isinstance(bindings['identities'], dict) or not isinstance(bindings['sessions'], list)):
        raise ValueError('asr_bindings_invalid')
    turns = [json.loads(line) for line in (bundle / 'turns.jsonl').read_text().splitlines()]
    grouped = {}
    for turn in turns:
        grouped.setdefault(turn['session_key'], []).append(turn)
    expected = {(sid, call) for sid, sc in scenarios.items() for call in sc['calls']}
    used, linked, identities, conversations = set(), set(), set(), {}
    output = deepcopy(scenarios)
    dates = {}
    for sid, sc in scenarios.items():
        on = date(2026, 10, 15)
        for call, spec in sc['calls'].items():
            on = date.fromisoformat(spec['call_date']) if 'call_date' in spec else on + timedelta(days=spec.get('days_later', 0))
            dates[(sid, call)] = on.isoformat()
    manifest_hash = _sha(bundle / 'manifest.json')
    for binding in bindings['sessions']:
        if not isinstance(binding, dict) or set(binding) != {'scenario_id', 'call', 'session_key'}:
            raise ValueError('asr_session_binding_invalid')
        key = (binding['scenario_id'], binding['call'])
        session = binding['session_key']
        if key not in expected or key in linked or session in used or session not in grouped:
            raise ValueError('asr_session_binding_mismatch')
        recognized = grouped[session]
        first = recognized[0]
        sid, call = key
        spec = output[sid]['calls'][call]
        if (bindings['identities'].get(first['identity_ref']) != sid
                or first['session_index'] != int(call.removeprefix('call_'))
                or first['call_date'] != dates[key]
                or len(recognized) != len(spec['customer_turns'])):
            raise ValueError('asr_identity_date_or_turn_count_mismatch')
        previous = conversations.setdefault(sid, first['conversation_key'])
        if previous != first['conversation_key']:
            raise ValueError('asr_conversation_mismatch')
        spec['customer_turns_asr'] = [turn['text'] for turn in recognized]
        spec['input_mode'] = 'asr_transcript'
        spec['asr_provenance'] = {'bundle_sha256': manifest_hash,
            'session_key': session, 'audio_sha256': [t['audio_sha256'] for t in recognized]}
        used.add(session)
        linked.add(key)
        identities.add(first['identity_ref'])
    if linked != expected or used != set(grouped) or identities != set(bindings['identities']):
        raise ValueError('asr_binding_coverage_incomplete')
    return output


def main():
    parser = argparse.ArgumentParser(description='Attach a sealed customer-only ASR replay to explicitly mapped BTC scenarios.')
    parser.add_argument('--scenarios', required=True, type=Path)
    parser.add_argument('--btc-root', required=True, type=Path)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--bindings', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        scenarios = load_scenarios(args.scenarios, btc_root=args.btc_root)
        output = attach_replay(scenarios, args.bundle, json.loads(args.bindings.read_text()))
        snapshot_scenarios(output, args.out)
    except (OSError, ValueError, KeyError, TypeError):
        parser.error('ASR replay, bindings or output invalid; no runtime requests were sent.')
    print(json.dumps({'status': 'prepared_inputs_only', 'scenarios': len(output),
                      'bundle_sha256': _sha(args.bundle / 'manifest.json')}))


if __name__ == '__main__':
    main()
