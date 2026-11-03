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
