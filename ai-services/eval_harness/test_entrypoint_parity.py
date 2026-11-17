from eval_harness.test_support import VoiceLifecycleStub
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from eval_harness.benchmark_runner import run_configuration


class Runtime(VoiceLifecycleStub):
    def __init__(self):
        self.memory = SimpleNamespace(include_prior=True, namespace='')
        self.requests = []
    async def run(self, request):
        self.requests.append(request)
        return SimpleNamespace(agent_text='Giá 50.000đ.', call_brief={'latency_ms':12})
    def state_for(self, request):
        return dict(tool_calls=[{'id':'call-x','name':'catalog.search','args':{'query':'máy'},'result':{}}],
                    profile={}, scoped_facts={})


def test_shared_runner_persists_accepted_writes_in_both_modes(tmp_path):
    scenarios={'NEW':{'calls':{'call_1':{'customer_turns':['một'], 'customer_turns_asr':['mot']},
                             'call_2':{'customer_turns':['hai'], 'days_later':2}}}}
    for config in ('full','baseline_no_memory'):
        runtime=Runtime()
        async def accepted(ids):
            return {i:[{'key':'size','value':0,'op':'set'}] for i in ids}
        out=tmp_path/f'{config}.jsonl'
        result=asyncio.run(run_configuration(scenarios=scenarios,config=config,runtime=runtime,
            run_id='test',out=out,wait_for_jobs=AsyncMock(),capture_writes=accepted))
        rows=[json.loads(x) for x in out.read_text().splitlines()]
        from eval_harness.extraction_report import make_extraction_row
        from eval_harness.extractor import extract_detailed
        side = tmp_path/('full.extraction.jsonl' if config == 'full' else 'baseline.extraction.jsonl')
        details = [json.loads(line) for line in side.read_text().splitlines()]
        assert details == [make_extraction_row(row, extract_detailed(row['agent_text'])) for row in rows]
        assert len(rows)==2 and rows[0]['memory_writes'][0]['value']==0
        assert rows[0]['customer_text']=='mot' and rows[0]['customer_input_mode']=='asr_transcript'
        assert rows[0].get('call_brief_latency_ms') is None
        assert rows[1]['call_brief_latency_ms']==12
        assert runtime.requests[0].session_id != runtime.requests[1].session_id
        assert runtime.requests[1].on.isoformat()=='2026-10-17'
        assert runtime.memory.include_prior == (config=='full')
        assert runtime.memory.namespace==''
        assert result['coverage']['turns']==2


def test_failure_retains_safe_redaction_evidence(tmp_path):
    import pytest
    runtime=Runtime()
    async def pii(request):
        return SimpleNamespace(agent_text='STK 123456789012',call_brief=None)
    runtime.run=pii
    issues=[]
    scenarios={'X':{'calls':{'call_1':{'customer_turns':['chào']}}}}
    with pytest.raises(RuntimeError):
        asyncio.run(run_configuration(scenarios=scenarios,config='full',runtime=runtime,
            run_id='r',out=tmp_path/'partial.jsonl',wait_for_jobs=AsyncMock(side_effect=TimeoutError()),
            capture_writes=AsyncMock(return_value={}),safety_issues=issues))
    assert issues[0]['code']=='redaction_affects_scoring'
    assert '123456789012' not in (tmp_path/'partial.jsonl').read_text()


def test_shared_runner_records_zero_event_and_runtime_failure_turns(tmp_path):
    from app.agent.harness.observability import log_event
    from eval_harness.turn_diagnostics import verify_turn_diagnostics
    import pytest
    class Failing(Runtime):
        async def run(self, request):
            if request.text=='lỗi':
                raise TimeoutError('private 0912345678')
            log_event({},'run_agent','model_failed',error_type='TimeoutError')
            return await super().run(request)
    out=tmp_path/'trace.jsonl'
    with pytest.raises(RuntimeError):
        asyncio.run(run_configuration(scenarios={'X':{'calls':{'call_1':{'customer_turns':['chào','lỗi']}}}},
            config='full',runtime=Failing(),run_id='r',out=out,delivery_mode='voice',wait_for_jobs=AsyncMock(),capture_writes=AsyncMock(return_value={})))
    refs=verify_turn_diagnostics(out)
    assert refs['rows']==2
    rows=json.loads(out.with_suffix('.events.json').read_text())
    assert rows[0]['model']['status']=='failed'
    assert rows[1]['runtime_error']=='TimeoutError'
    assert '0912345678' not in out.with_suffix('.events.json').read_text()
