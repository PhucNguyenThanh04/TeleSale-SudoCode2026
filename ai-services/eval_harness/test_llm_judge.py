import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from eval_harness import llm_judge as judge
from eval_harness.semantic_eval import bound_evaluation


BTC = Path(__file__).resolve().parents[3] / 'BTC-Data-Vong1-TEAMS'


def fixture(tmp_path, count=1):
    cases = {f'S{i}': {'scenario_id': f'S{i}', 'calls': {'call_1': {
        'customer_turns': ['Xin tư vấn.'], 'success_if': {'tool_called': None},
        'judge_criteria': ['J02_no_fabrication'],
        'semantic_requirements': [{'id': 'correct', 'requirement': 'Không bịa.',
                                   'source_sections': ['PB-01']}]}}} for i in range(count)}
    trace = tmp_path / 'trace.jsonl'
    trace.write_text(''.join(json.dumps({'scenario_id': sid, 'call': 'call_1', 'turn': 1,
        'agent_text': 'Dạ chưa có thông tin.', 'tool_calls': []}) + '\n' for sid in cases))
    return cases, trace


class Stub:
    async def judge(self, prompt):
        assert 'PB-01' in prompt and 'J02_no_fabrication' in prompt
        return {'judgments': [{'criterion_id': cid, 'verdict': 'PASS',
            'evidence': 'Dạ chưa có thông tin.', 'reason': 'Nói rõ giới hạn thông tin.'}
            for cid in ('J02_no_fabrication', 'team:correct')]}


def test_judge_uses_btc_rubric_and_exact_coverage(tmp_path):
    cases, trace = fixture(tmp_path)
    report = asyncio.run(judge.run_judge(cases, trace, btc_root=BTC, model=Stub(), model_info={'model': 'stub'}))
    assert report['inputs'] == bound_evaluation(cases, trace, btc_root=BTC)['inputs']
    assert report['counts'] == {'PASS': 2}
    assert report['human_calibrated'] is False
    criteria = judge.criteria_for(cases['S0']['calls']['call_1'], BTC)
    rows = report['calls'][0]['judgments']
    judge.validate_judgments(rows, criteria, 'Dạ chưa có thông tin.')
    with pytest.raises(ValueError, match='coverage'):
        judge.validate_judgments(rows[:-1], criteria, 'Dạ chưa có thông tin.')
    wrong = deepcopy(rows)
    wrong[0]['evidence'] = 'câu bịa không có'
    with pytest.raises(ValueError, match='evidence'):
        judge.validate_judgments(wrong, criteria, 'Dạ chưa có thông tin.')
    assert judge.validate_judgments([{**r, 'verdict': 'FAIL', 'evidence': ''} for r in rows], criteria, '') is None


def test_human_sampling_binding_and_agreement(tmp_path):
    cases, trace = fixture(tmp_path, count=12)
    report = asyncio.run(judge.run_judge(cases, trace, btc_root=BTC, model=Stub(), model_info={'model': 'stub'}))
    for index, call in enumerate(report['calls']):
        for row in call['judgments']:
            row['verdict'] = 'PASS' if index % 2 else 'FAIL'
    template = judge.human_template(report, count=20, seed=17)
    assert len(template['samples']) == 20
    assert template == judge.human_template(report, count=20, seed=17)
    assert all(s['verdict'] is None and 'llm_verdict' not in s for s in template['samples'])
    assert judge.agreement(report, template)['qualified'] is False
    lookup = {(c['scenario_id'], c['call'], r['criterion_id']): r['verdict']
              for c in report['calls'] for r in c['judgments']}
    template['reviewer'] = 'human-reviewer'
    for sample in template['samples']:
        sample.update(verdict=lookup[tuple(sample[k] for k in ('scenario_id', 'call', 'criterion_id'))],
                      evidence='Dạ chưa có thông tin.')
    result = judge.agreement(report, template)
    assert result['qualified'] is True and result['cohen_kappa'] == 1 and result['agreement_pct'] == 100
    bad = deepcopy(template)
    bad['samples'][1] = bad['samples'][0]
    with pytest.raises(ValueError, match='sample'):
        judge.agreement(report, bad)
    with pytest.raises(ValueError, match='binding'):
        judge.agreement({**report, 'model': {'model': 'changed'}}, template)


def test_supplemental_cannot_pass_uncalibrated_or_stale_judge(tmp_path):
    cases, trace = fixture(tmp_path)
    report = asyncio.run(judge.run_judge(cases, trace, btc_root=BTC, model=Stub(), model_info={'model': 'stub'}))
    supplemental = bound_evaluation(cases, trace, btc_root=BTC)
    result = judge.apply_judgments(supplemental, report, cases, trace, btc_root=BTC)
    assert result['complete'] is False
    assert result['semantic_review']['status'] == 'needs_human_calibration'
    trace.write_text(trace.read_text() + '\n')
    with pytest.raises(ValueError, match='binding'):
        judge.apply_judgments(supplemental, report, cases, trace, btc_root=BTC)


def test_all_one_class_has_no_reliable_kappa():
    assert judge.agreement_values(['PASS'] * 20, ['PASS'] * 20) == {
        'n': 20, 'agreement_pct': 100.0, 'cohen_kappa': None, 'qualified': False}


def test_calibrated_judge_preserves_actual_failures(tmp_path):
    cases, trace = fixture(tmp_path, count=12)
    report = asyncio.run(judge.run_judge(cases, trace, btc_root=BTC, model=Stub(), model_info={'model': 'stub'}))
    report['calls'][0]['judgments'][0].update(verdict='FAIL', evidence='', reason='Thiếu xác minh.')
    human = judge.human_template(report, count=24)
    human['reviewer'] = 'test-fixture-human'
    lookup = {(c['scenario_id'], c['call'], r['criterion_id']): r['verdict']
              for c in report['calls'] for r in c['judgments']}
    for sample in human['samples']:
        sample.update(verdict=lookup[tuple(sample[k] for k in ('scenario_id', 'call', 'criterion_id'))],
                      evidence='Nhãn giả lập chỉ dùng trong unit test.')
    supplemental = bound_evaluation(cases, trace, btc_root=BTC)
    result = judge.apply_judgments(supplemental, report, cases, trace, btc_root=BTC, human=human)
    assert result['semantic_review']['status'] == 'calibrated'
    assert result['counts'] == {'fail': 1, 'pass': 11}
    assert result['complete'] is False
    report['calls'][0]['judgments'][0]['verdict'] = 'PASS'
    report['calls'][0]['judgments'][0]['evidence'] = 'Dạ chưa có thông tin.'
    with pytest.raises(ValueError, match='binding'):
        judge.apply_judgments(supplemental, report, cases, trace, btc_root=BTC, human=human)


def test_live_judge_cli_requires_explicit_opt_in(tmp_path):
    import os
    import subprocess
    import sys
    output = tmp_path / 'judge.json'
    proc = subprocess.run([sys.executable, '-m', 'eval_harness.llm_judge', 'run',
        '--scenarios', str(tmp_path), '--trace', str(tmp_path / 'missing'), '--btc-root', str(BTC),
        '--out', str(output)], capture_output=True, env={**os.environ, 'PYTHONPATH': 'ai-services:.'})
    assert proc.returncode != 0 and b'--allow-model-calls' in proc.stderr
    assert not output.exists()
