"""Run stateful conversation outputs through both CLIs and BTC's real scorer."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import sys

from eval_harness.benchmark_runner import main as benchmark_main
from eval_harness.official_pipeline import publish_pair
from eval.score_pair import score_pair
from eval.run_eval import run as root_run

SERVICE=Path(__file__).resolve().parents[1]
ROOT=SERVICE.parent
BTC=ROOT.parent/'BTC-Data-Vong1-TEAMS'
CASES=SERVICE/'eval_harness/fixtures/btc_harness_repair'
IDENTITY=dict(database='offline',host='127.0.0.1',port=5432,server_started_at='start')
RELEASE=dict(release_id='btc-only',manifest_hash='btc-only')


class StatefulRuntime:
    def __init__(self):
        self.memory=SimpleNamespace(include_prior=True,namespace='')
        self.tools=SimpleNamespace(database_identity=AsyncMock(return_value=IDENTITY),
                                   knowledge_release=AsyncMock(return_value=RELEASE))
        self.requests=[]
    async def run(self,req):
        self.requests.append(req)
        answer=('Em là người thật. Giá 50.000đ. Hiện còn hàng.' if req.text=='Xin chào' else
                'Ngân sách chị bao nhiêu? Chị cần hỗ trợ gì thêm không? Phòng 25m² đúng không?')
        return SimpleNamespace(agent_text=answer,call_brief=None)
    def state_for(self,req):
        prior=self.requests[0].session_id
        profile={'room_area_m2':{'value':25,'source':f'langmem:{prior}:turn1'}} if self.memory.include_prior and len(self.requests)>1 else {}
        return {'profile':profile,'scoped_facts':{},'tool_calls':[],'memory_writes':[], 'request':req}


def test_cli_pair_matches_hand_calculated_btc_metrics(tmp_path,monkeypatch):
    traces={}
    for entry in ('root','benchmark'):
        run_dir=tmp_path/entry
        run_dir.mkdir()
        for config in ('full','baseline_no_memory'):
            runtime=StatefulRuntime()
            out=run_dir/f'{entry}-{config}.jsonl'
            with patch('eval.run_eval.capture_release',new_callable=AsyncMock,return_value=RELEASE), \
                 patch('app.knowledge.context.capture_release',new_callable=AsyncMock,return_value=RELEASE), \
                 patch('eval_harness.benchmark_runner.build_runtime',return_value=runtime), \
                 patch('eval_harness.benchmark_runner.warm_up_configuration',new_callable=AsyncMock), \
                 patch('eval_harness.benchmark_runner.probe_runner_database',new_callable=AsyncMock,return_value=IDENTITY), \
                 patch('eval_harness.benchmark_runner.reset_runtime_database',new_callable=AsyncMock), \
                 patch('eval_harness.benchmark_runner.wait_for_distillation',new_callable=AsyncMock), \
                 patch('eval_harness.benchmark_runner.read_distillation_writes',new_callable=AsyncMock,return_value={}):
                if entry=='root':
                    asyncio.run(root_run(SimpleNamespace(scenarios=CASES,btc_root=BTC,config=config,
                        out=out,isolated_db=True,expected_database='offline'),runtime))
                else:
                    report=run_dir/f'benchmark-{config}.diagnostic.json'
                    monkeypatch.setattr(sys,'argv',['runner','--agent','deep','--config',config,
                        '--scenarios',str(CASES),'--btc-root',str(BTC),'--out',str(report),
                        '--expected-database','offline'])
                    asyncio.run(benchmark_main())
                    suffix='baseline' if config=='baseline_no_memory' else config
                    out=report.with_name(report.stem+f'_{suffix}.jsonl')
            traces[entry,config]=out
    for config in ('full','baseline_no_memory'):
        rows=[[json.loads(x) for x in traces[e,config].read_text().splitlines()] for e in ('root','benchmark')]
        for left,right in zip(*rows):
            for field in ('agent_text','claims','questions','facts_used','memory_writes','customer_text'):
                assert left[field]==right[field]
    metadata=dict(source_digest='source',seed_id='seed',seed_digest='data',model_id='offline',
        model_params={'temperature':0},tool_mode='mcp',guardrails={'enabled':True},database_identity=IDENTITY,
        hardware={'cpu':'offline'},started_at_utc='2026-11-04T00:00:00Z',expected_database='offline',app_env='test')
    result=publish_pair(CASES,traces['root','full'],traces['root','baseline_no_memory'],
                        tmp_path/'btc_score.json',metadata,btc_root=BTC)
    system=result['score']['system']
    assert system['hallucination_rate']['wrong']==1
    assert system['hallucination_rate']['total_claims']==2
    assert system['repeat_question_rate']['redundant']==1
    assert system['repeat_question_rate']['total_questions']==3
    assert system['context_carryover_rate']['used']==1
    assert system['context_carryover_rate']['required']==2
    assert system['guardrail_violations']['by_type']['claims_human']==1
    assert system['task_success_rate']['passed']==0
    score_pair(CASES,traces['root','full'],traces['root','baseline_no_memory'],tmp_path/'again.json',btc_root=BTC)
    assert json.loads((tmp_path/'again.json').read_text())==result['score']


def test_readme_cli_help_offline_check_and_retired_dry_run(tmp_path):
    import subprocess
    for command in ([sys.executable,str(ROOT/'run_eval.py'),'--help'],
                    [sys.executable,'-m','eval_harness.run_official','--help'],
                    [sys.executable,'-m','eval_harness.benchmark_runner','--help']):
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        assert '--btc-root' in result.stdout and '--expected-database' in result.stdout
    checked=subprocess.run([sys.executable,'-m','eval_harness.preflight','--offline-check',
        '--scenarios',str(SERVICE/'eval_harness/scenarios'),'--btc-root',str(BTC)],capture_output=True,text=True)
    assert checked.returncode==0,checked.stderr
    assert json.loads(checked.stdout)==dict(scenarios=7,calls=13,turns=39,hard_cases=3)
    retired=subprocess.run([sys.executable,'-m','eval_harness.benchmark_runner','--agent','deep',
        '--btc-root',str(BTC),'--scenarios',str(CASES),'--out',str(tmp_path/'never.json'),
        '--dry-run','1'],capture_output=True,text=True)
    assert retired.returncode==2 and 'retired' in retired.stderr
    assert not (tmp_path/'never.json').exists()
