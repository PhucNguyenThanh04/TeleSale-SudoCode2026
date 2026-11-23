import json
import hashlib
import re
from datetime import date, timedelta
from pathlib import Path

CRITERIA = {'tool_called', 'args_match', 'also_ordered', 'total_match_vnd',
            'brief_must_contain', 'must_say_any', 'agent_must_say', 'must_not_call_tools',
            'forbidden_claims', 'trace_must_not_match', 'max_agent_questions'}
MODES = {'clean', 'asr_transcript', 'chat_teencode'}
CHANNELS = {'hotline', 'chat_fanpage', 'zalo_oa'}


def verify_manifest(path, btc_root):
    manifest_path = path / '_manifest.json'
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text())
    files = {p.name for p in path.glob('*.json') if not p.name.startswith('_')}
    if files != set(manifest['scenarios']):
        raise ValueError('scenario_manifest_file_mismatch')
    for root, hashes in ((path, manifest['scenarios']), (path, manifest['metadata']),
                         (btc_root, manifest['btc_files'])):
        for name, expected in hashes.items():
            target = root / name
            if (not target.resolve().is_relative_to(root.resolve()) or not target.is_file()
                    or hashlib.sha256(target.read_bytes()).hexdigest() != expected):
                raise ValueError('scenario_manifest_hash_mismatch:' + name)


def input_turns(call):
    return call['customer_turns_asr'] if 'customer_turns_asr' in call else call['customer_turns']


def validate_success(success, tools):
    if not isinstance(success, dict) or set(success) - CRITERIA:
        raise ValueError('success_criteria_unsupported')
    if success.get('tool_called') and success['tool_called'] not in tools:
        raise ValueError('expected_tool_unsupported')
    if 'args_match' in success and not isinstance(success['args_match'],dict):
        raise ValueError('args_match_invalid')
    for key in ('max_agent_questions','total_match_vnd'):
        if key in success and (type(success[key]) is not int or success[key]<0):
            raise ValueError('success_number_invalid')
    for key in ('also_ordered','brief_must_contain','must_say_any','must_not_call_tools','trace_must_not_match'):
        if key in success and (not isinstance(success[key],list) or any(not isinstance(x,str) for x in success[key])):
            raise ValueError('success_list_invalid')
    for rx in success.get('trace_must_not_match',[]):
        try:
            re.compile(rx)
        except re.error:
            raise ValueError('success_regex_invalid') from None
    if 'forbidden_claims' in success:
        values=success['forbidden_claims']
        if not isinstance(values,list) or any(not isinstance(x,str) and
                not (isinstance(x,dict) and isinstance(x.get('field'),str) and 'value' in x) for x in values):
            raise ValueError('forbidden_claims_invalid')


def validate_supplemental(call, source_ids):
    rules = call.get('supplemental_checks', {})
    if not isinstance(rules, dict) or set(rules) - {'order_count', 'order_lines'}:
        raise ValueError('supplemental_checks_invalid')
    if 'order_count' in rules and (type(rules['order_count']) is not int or rules['order_count'] < 0):
        raise ValueError('supplemental_order_count_invalid')
    if 'order_lines' in rules:
        lines = rules['order_lines']
        if not isinstance(lines, list) or any(not isinstance(line, dict)
                or set(line) - {'sku', 'qty', 'price_vnd'}
                or not isinstance(line.get('sku'), str) or not line['sku']
                or type(line.get('price_vnd')) is not int or line['price_vnd'] < 0
                or type(line.get('qty', 1)) is not int or line.get('qty', 1) < 1 for line in lines):
            raise ValueError('supplemental_order_lines_invalid')
    if 'semantic_requirements' in call:
        values = call['semantic_requirements']
        if not isinstance(values, list) or not values:
            raise ValueError('semantic_requirements_invalid')
        ids = set()
        for item in values:
            if (not isinstance(item, dict) or set(item) != {'id', 'requirement', 'source_sections'}
                    or not isinstance(item.get('id'), str) or not item['id'].strip() or item['id'] in ids
                    or not isinstance(item.get('requirement'), str) or not item['requirement'].strip()
                    or not isinstance(item.get('source_sections'), list) or not item['source_sections']
                    or any(not isinstance(k, str) or k not in source_ids for k in item['source_sections'])):
                raise ValueError('semantic_requirements_invalid')
            ids.add(item['id'])


def load_scenarios(path: Path, *, btc_root: Path) -> dict[str, dict]:
    path, btc_root = Path(path), Path(btc_root)
    for name in ('trace_log.schema.json', 'handoff_brief.schema.json', 'tools.schema.json', 'scenario_format.md'):
        if not (btc_root / 'schemas' / name).is_file():
            raise ValueError('btc_contract_missing:' + name)
    if not (btc_root / 'eval/reference_eval.py').is_file():
        raise ValueError('btc_scorer_missing')
    try:
        if path.is_dir():
            verify_manifest(path, btc_root)
        if path.is_dir():
            values = [json.loads(p.read_text()) for p in sorted(path.glob('*.json')) if not p.name.startswith('_')]
        else:
            values = json.loads(path.read_text())
            if isinstance(values, dict):
                values = values.get('scenarios', [values])
        if not isinstance(values, list) or not values:
            raise ValueError('dataset_empty')
        tools = {x['name'] for x in json.loads((btc_root / 'schemas/tools.schema.json').read_text())['tools']}
        from eval_harness.preflight import _outcomes
        outcomes = _outcomes(btc_root)
        source_ids = {key for p in (btc_root / 'policy').glob('*.md')
                      for key in re.findall(r'^## \[([^]]+)\]', p.read_text(), re.M)}
        rubric_path = btc_root / 'eval/llm_judge_rubric.json'
        judge_ids = {r['id'] for r in json.loads(rubric_path.read_text())['criteria']} if rubric_path.is_file() else set()
        result = {}
        for index, sc in enumerate(values):
            if not isinstance(sc, dict) or not isinstance(sc.get('scenario_id'), str) or not sc['scenario_id']:
                raise ValueError(f'scenario_invalid:index={index}')
            sid = sc['scenario_id']
            if sid in result:
                raise ValueError('scenario_duplicate')
            calls = sc.get('calls')
            if not isinstance(calls, dict) or not calls or set(calls) != {f'call_{n}' for n in range(1, len(calls) + 1)} or len(calls) > 3:
                raise ValueError('calls_invalid')
            previous = date(2026, 10, 15)
            ordered = {}
            seeded = {}
            for name in sorted(calls):
                call = calls[name]
                if not isinstance(call, dict):
                    raise ValueError('call_invalid')
                turns = call.get('customer_turns')
                if not isinstance(turns, list) or not turns or any(not isinstance(x, str) or not x.strip() or len(x)>8000 for x in turns):
                    raise ValueError('turns_invalid')
                if 'customer_turns_asr' in call:
                    asr = call['customer_turns_asr']
                    if not isinstance(asr, list) or len(asr) != len(turns) or any(not isinstance(x, str) or not x.strip() or len(x)>8000 for x in asr):
                        raise ValueError('asr_turns_invalid')
                if call.get('channel', 'hotline') not in CHANNELS or call.get('input_mode', 'clean') not in MODES:
                    raise ValueError('input_mode_or_channel_invalid')
                if type(call.get('days_later', 0)) is not int or call.get('days_later', 0) < 0:
                    raise ValueError('days_later_invalid')
                try:
                    on = date.fromisoformat(call['call_date']) if 'call_date' in call else previous + timedelta(days=call.get('days_later', 0))
                except (ValueError, TypeError):
                    raise ValueError('call_date_invalid') from None
                if ordered and on < previous:
                    raise ValueError('call_date_out_of_order')
                previous = on
                success = call.get('success_if') or {}
                validate_success(success, tools)
                validate_supplemental(call, source_ids)
                if 'judge_criteria' in call:
                    selected = call['judge_criteria']
                    if (not isinstance(selected, list) or not selected
                            or any(not isinstance(k, str) or k not in judge_ids for k in selected)
                            or len(set(selected)) != len(selected)):
                        raise ValueError('judge_criteria_invalid')
                if call.get('expected_outcome') is not None and call['expected_outcome'] not in outcomes:
                    raise ValueError('outcome_unsupported')
                if 'seed_history' in call:
                    from eval_harness.seed_history import parse_seed_history
                    for item in parse_seed_history(call['seed_history'], call_date=on):
                        if item['session_id'] in seeded and seeded[item['session_id']] != item:
                            raise ValueError('seed_history_conflict')
                        seeded[item['session_id']]=item
                ordered[name] = call
            result[sid] = {**sc, 'calls': ordered}
        return result
    except (OSError, json.JSONDecodeError, TypeError, KeyError, OverflowError) as exc:
        raise ValueError('dataset_invalid:' + type(exc).__name__) from None


def dataset_coverage(scenarios: dict[str, dict]) -> dict:
    return {'scenarios': len(scenarios), 'calls': sum(len(s['calls']) for s in scenarios.values()),
            'turns': sum(len(input_turns(c)) for s in scenarios.values() for c in s['calls'].values()),
            'hard_cases': sum(bool(s.get('hard_case')) for s in scenarios.values())}


def snapshot_scenarios(scenarios: dict[str, dict], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=False)
    for index, sc in enumerate(scenarios.values()):
        (out / f'{index:04d}.json').write_text(json.dumps(sc, ensure_ascii=False, indent=2) + '\n')
    return out
