"""Offline extraction cannot rewrite conversations or invent missing provenance."""
from copy import deepcopy
import json
import subprocess
import sys

import pytest
from eval_harness.reextract_trace import reextract_rows


def row():
    return {'scenario_id':'LOCAL','call':'call_1','turn':1,'agent_text':'Hiện có quà tặng kèm.',
            'tool_calls':[], 'questions':[], 'claims':[], 'facts_used':['price_quoted_vnd'],
            'memory_writes':[], 'latency':{'total_ms':30},'config':'full','run_id':'offline-test'}


def test_only_questions_and_claims_change():
    original = [row()]
    before = deepcopy(original)
    replay = reextract_rows(original)
    assert original == before
    assert replay[0]['claims'][0]['field'] == 'promo_active'
    assert {k:v for k,v in replay[0].items() if k not in {'claims','questions'}} == {
        k:v for k,v in original[0].items() if k not in {'claims','questions'}}


def test_duplicate_and_out_of_order_turns_rejected():
    with pytest.raises(ValueError):
        reextract_rows([row(), row()])
    first = row()
    first['turn'] = 2
    with pytest.raises(ValueError):
        reextract_rows([first])


def test_cli_does_not_overwrite_and_rejects_malformed_input(tmp_path):
    source = tmp_path/'source.jsonl'
    output = tmp_path/'replay.jsonl'
    source.write_text(json.dumps(row())+'\n')
    command = [sys.executable,'-m','eval_harness.reextract_trace','--input',str(source),'--output',str(output)]
    first = subprocess.run(command,capture_output=True,text=True)
    assert first.returncode == 0, first.stderr
    before = source.read_bytes()
    assert subprocess.run(command,capture_output=True).returncode != 0
    assert source.read_bytes() == before
    output.unlink()
    source.write_text('{broken\n')
    assert subprocess.run(command,capture_output=True).returncode != 0
    assert not output.exists()


def source_pair(tmp_path):
    from eval_harness.test_official_pipeline import _case, BTC
    from eval_harness.official_pipeline import publish_pair
    source = tmp_path/'source'
    source.mkdir()
    scenarios, traces, metadata = _case(source)
    publish_pair(scenarios, traces['full'], traces['baseline_no_memory'], source/'btc_score.json', metadata, btc_root=BTC)
    (source/'run.json').write_text(json.dumps({'status':'validated', 'score':'btc_score.json',
        'traces':{k:v.name for k,v in traces.items()}, 'manifests':{k:f'{k}.manifest.json' for k in traces}}))
    return source, BTC


@pytest.mark.parametrize('score_whitespace', [False, True])
def test_paired_replay_preserves_source_and_only_changes_annotations(tmp_path, score_whitespace):
    from eval_harness.reextract_trace import replay_pair
    source, btc = source_pair(tmp_path)
    if score_whitespace:
        with (source/'btc_score.json').open('ab') as stream: stream.write(b'\n')
    before = {str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    out = tmp_path/'replay'
    result = replay_pair(source, out, btc)
    assert result['kind'] == 'offline-extraction-replay'
    assert result['status'] == 'complete'
    assert bool(result['source_integrity_issues']) == score_whitespace
    assert before == {str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    assert not (out/'run.json').exists()
    for config in ('full', 'baseline_no_memory'):
        old = json.loads((source/f'{config}.jsonl').read_text())
        new = json.loads((out/f'{config}.jsonl').read_text())
        assert {k:v for k,v in new.items() if k not in {'questions','claims'}} == {k:v for k,v in old.items() if k not in {'questions','claims'}}
    with pytest.raises(ValueError): replay_pair(source, out, btc)


@pytest.mark.parametrize('damage', ['trace', 'scenario', 'scorer', 'report_value', 'missing_manifest'])
def test_paired_replay_rejects_unverified_source(tmp_path, damage):
    from eval_harness.reextract_trace import replay_pair
    source, btc = source_pair(tmp_path)
    if damage == 'trace':
        with (source/'full.jsonl').open('ab') as stream: stream.write(b' ')
    elif damage == 'scenario': (source/'scenarios'/'case.json').write_text('{}')
    elif damage == 'scorer':
        path=source/'btc_score.inputs.json'; data=json.loads(path.read_text()); data['scorer_sha256']='wrong'; path.write_text(json.dumps(data))
    elif damage == 'report_value':
        path=source/'btc_score.json'; data=json.loads(path.read_text()); data['n_scenarios']=100; path.write_text(json.dumps(data))
    else: (source/'full.manifest.json').unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        replay_pair(source, tmp_path/'replay', btc)
    assert not (tmp_path/'replay'/'replay_manifest.json').exists()


def test_policy_replay_uses_live_extractor_without_rewriting_speech():
    from eval_harness.extractor import extract_detailed
    original = row()
    original['agent_text'] = 'Phiên bản 2026-10 thay thế phiên bản 2026-06.'
    replay = reextract_rows([original])[0]
    assert replay['claims'] == extract_detailed(original['agent_text'])['claims']
    assert [c['value'] for c in replay['claims'] if c['field']=='policy_version'] == ['2026-10']
    assert {k:v for k,v in replay.items() if k not in {'claims','questions'}} == {
        k:v for k,v in original.items() if k not in {'claims','questions'}}
