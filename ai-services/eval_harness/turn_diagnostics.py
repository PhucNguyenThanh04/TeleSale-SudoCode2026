import hashlib
import json
import re
from pathlib import Path

from app.agent.guardrails.checks import FALLBACK
from app.agent.harness.observability import (DIAGNOSTIC_REASONS, DIAGNOSTIC_ERRORS,
                                            safe_diagnostic_event)
from eval.stage_evidence import stage_evidence
from eval_harness.official_pipeline import atomic_json

IDENTITY = ('run_id', 'config', 'scenario_id', 'call', 'turn')
DECISION_CHECKPOINTS = frozenset({'context_loaded', 'context_masked', 'consultation_before',
    'continuation', 'final_verified', 'final_commit', 'memory_read', 'memory_commit',
    'worker_admission', 'worker_projection'})
TOOLS = frozenset({'crm.get_customer','catalog.search','inventory.check','pricing.get_quote','pricing.quote_order',
    'order.create','order.update','order.status','policy.search','handoff.transfer','schedule.callback'})
TOOL_ERRORS = frozenset({'tool_error','unknown_sku','invalid_tool_result','precondition_or_arguments',
    'knowledge_unavailable','timeout','unavailable','overloaded','other_error'})
RETRIEVAL_STATUS = frozenset({'ok','empty','unavailable','timeout','overloaded'})


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _text_sha(row):
    return hashlib.sha256(row['agent_text'].encode()).hexdigest()


def _check(item):
    reason = item.get('reason')
    return {'reason':reason if isinstance(reason,str) and reason in DIAGNOSTIC_REASONS else 'unknown_reason'}


def _classify(events, checks):
    models = [e for e in events if e['event']=='model_failed']
    execution = [e for e in events if e.get('step') == 'execution']
    invocations = [e for e in execution if e.get('phase') == 'model_invocation']
    if execution:
        models = [e for e in invocations if e.get('status') == 'failed']
    grounding = [e for e in events if e['event']=='grounding_checked' and 'accepted' in e]
    outcomes = [e['event'] for e in events if e['event'] in {'recovery_succeeded', 'recovery_exhausted', 'recovery_fallback'}]
    return {
        'model': {'status':('failed' if models else 'succeeded' if invocations and all(e.get('status') == 'succeeded' for e in invocations) else 'not_attempted' if invocations and all(e.get('status') == 'not_attempted' for e in invocations) else 'unknown'),
                  **({'error_type':models[-1].get('error_type','other_error')} if models else {}),
                  **({'error_code': models[-1]['error_code']} if models and models[-1].get('error_code')
                     not in {None, 'unknown'} else {})},
        'grounding': {'status':('accepted' if grounding[-1]['accepted'] else 'rejected') if grounding else 'unknown',
                      **({'reason':grounding[-1]['reason']} if grounding and 'reason' in grounding[-1] else {})},
        'verifier_rejected': bool(checks),
        'recovery': {'status':('succeeded' if outcomes[-1]=='recovery_succeeded' else 'fallback' if outcomes[-1]=='recovery_fallback' else 'failed') if outcomes else 'unknown',
                     'attempts':sum(e['event']=='recovery_attempted' for e in events)},
    }


def _tool_failures(calls):
    failures=[]
    for call in calls:
        result=call.get('result')
        if not isinstance(result,dict):
            continue
        status=result.get('retrieval_status')
        failed=bool(result.get('error')) or result.get('ok') is False or result.get('success') is False or status in {'unavailable','timeout','overloaded'}
        if not failed:
            continue
        code=result.get('error')
        failures.append({'name':call['name'] if call.get('name') in TOOLS else 'other_tool',
            'error_code':code if isinstance(code,str) and code in TOOL_ERRORS else 'other_error',
            **({'retrieval_status':status} if status in RETRIEVAL_STATUS else {})})
    return failures


def _validate_stage(detail):
    def keys(value):
        return isinstance(value,list) and all(isinstance(k,str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}",k) for k in value)
    def count(value):
        return type(value) is int and value>=0
    if any(not keys(detail[k]) for k in ('profile_keys','prior_fact_keys','call_brief_fields')):
        raise ValueError('Unsafe stage key list')
    if (detail['identity_status'] not in {'known','unknown','ambiguous'} or
        any(detail[k] not in {'ok','failed','unknown'} for k in ('memory_read_status','memory_write_status')) or
        not count(detail['prior_episode_count']) or not count(detail['memory_write_count']) or
        type(detail['call_brief_present']) is not bool):
        raise ValueError('Unsafe stage status')
    counts=detail['call_brief_counts']
    if not isinstance(counts,dict) or set(counts)-{'must_not_ask','open_blockers','open_questions','stale_warnings'} or any(not count(v) for v in counts.values()):
        raise ValueError('Unsafe stage counts')
    scopes=detail['scoped_fact_keys']
    if not isinstance(scopes,dict) or set(scopes)!={'product','room'}:
        raise ValueError('Unsafe scope structure')
    for kind,groups in scopes.items():
        if not isinstance(groups,dict):
            raise ValueError('Unsafe scope labels')
        for label,value in groups.items():
            if (label!='[redacted_scope]' and (kind=='room' or not re.fullmatch(r'SKU-[A-Z0-9-]{1,80}',label))) or not keys(value):
                raise ValueError('Unsafe scope label/keys')
    if not isinstance(detail['business_tools'],list):
        raise ValueError('Unsafe stage tools')
    for tool in detail['business_tools']:
        if (not isinstance(tool,dict) or set(tool)!={'name','status'} or
            not isinstance(tool['name'],str) or not re.fullmatch(r'[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*',tool['name']) or
            tool['status'] not in {'unknown','success','failed'}):
            raise ValueError('Unsafe stage tool payload')


class TurnDiagnostics:
    def __init__(self):
        self.stages=[]
        self.events=[]
        self.decisions=[]
        self.decision_turns=[]
        self.decision_aliases={}

    def observe(self, request, response, state, row, events=(), *, runtime_error=None):
        identity={key:row[key] for key in IDENTITY}
        state={**state, 'request':request, 'tool_calls':[
            *state.get('prepared_tool_calls', []), *state.get('tool_calls', [])]}
        stage=stage_evidence(state,response,**identity)
        stage['agent_text_sha256']=_text_sha(row)
        self.stages.append(stage)
        checks=[_check(item) for item in state.get('verifier_events',[]) if isinstance(item,dict)]
        safe_events=[item for e in events if (item:=safe_diagnostic_event(e.get('step'),e.get('event'),e)) is not None]
        record={**identity, 'agent_text_sha256':_text_sha(row), 'checks':checks,
                'runtime_events':safe_events, 'tool_failures':_tool_failures(state.get('tool_calls',[])),
                'fallback_observed':row['agent_text']==FALLBACK,
                'runtime_error':runtime_error if runtime_error in DIAGNOSTIC_ERRORS else 'other_error' if runtime_error else None,
                **_classify(safe_events,checks)}
        self.events.append(record)

    def observe_decisions(self, row, capture):
        from app.mcp_servers.mcp_shared.decision_diagnostics import valid_event, normalize_aliases
        identity = {key: row[key] for key in IDENTITY}
        captured = capture.events if capture is not None else []
        safe = [normalize_aliases(event, self.decision_aliases) for event in captured if valid_event(event)]
        for index, event in enumerate(safe, 1):
            self.decisions.append({**identity, 'kind': 'event',
                'event_id': ':'.join(str(identity[k]) for k in IDENTITY) + f':{index}',
                'agent_text_sha256': _text_sha(row), **event})
        components = {e['component'] for e in safe}
        checkpoints = {e['event'] for e in safe}
        self.decision_turns.append({**identity,
            'missing_components': sorted({'runtime', 'memory', 'worker'} - components),
            'missing_checkpoints': sorted(DECISION_CHECKPOINTS - checkpoints),
            'truncated': capture.truncated if capture else False,
            'errors': (capture.errors if capture else 0) + len(captured) - len(safe)})

    def write_decisions(self, trace):
        from eval_harness.official_pipeline import atomic_bytes
        trace = Path(trace)
        out = trace.with_suffix('.decisions.jsonl')
        if out.exists():
            raise ValueError('Refusing existing decision diagnostics')
        rows = [json.loads(line) for line in trace.read_text().splitlines()]
        config = rows[0]['config'] if rows else 'unknown'
        records = [{'kind': 'metadata', 'schema_version': 1,
                    'traces': {config: {'path': trace.name, 'sha256': _sha(trace)}}},
                   *self.decisions, _decision_summary(rows, self.decision_turns)]
        atomic_bytes(out, ('\n'.join(json.dumps(r, ensure_ascii=False) for r in records) + '\n').encode())
        return _verify_decision_file(out, {config: trace})

    def write(self, trace: Path) -> dict:
        paths=[trace.with_suffix('.stages.json'),trace.with_suffix('.events.json')]
        if any(p.exists() for p in paths):
            raise ValueError('Refusing existing turn diagnostics')
        rows=[json.loads(line) for line in trace.read_text().splitlines()]
        if len(rows)!=len(self.stages) or len(rows)!=len(self.events):
            raise ValueError('Turn diagnostics coverage mismatch')
        for row,stage in zip(rows,self.stages):
            if 'memory_writes' in row:
                stage['memory_write_count']=len(row['memory_writes'])
            if row.get('memory_error'):
                stage['memory_write_status']='failed'
        atomic_json(paths[0],self.stages)
        atomic_json(paths[1],self.events)
        return verify_turn_diagnostics(trace)


def verify_turn_diagnostics(trace: Path, expected: dict | None = None) -> dict:
    trace=Path(trace)
    try:
        raw=trace.read_bytes()
        rows=[json.loads(line) for line in raw.decode().splitlines()]
        bindings={'trace_sha256':hashlib.sha256(raw).hexdigest(), 'rows':len(rows)}
        for kind in ('stages','events'):
            path=trace.with_suffix(f'.{kind}.json')
            contents=path.read_bytes()
            details=json.loads(contents)
            if not isinstance(details,list) or len(details)!=len(rows):
                raise ValueError('Turn diagnostics coverage mismatch')
            seen=set()
            for row,detail in zip(rows,details):
                identity=tuple(row[k] for k in IDENTITY)
                if identity in seen or any(detail.get(k)!=row[k] for k in IDENTITY) or detail.get('agent_text_sha256')!=_text_sha(row):
                    raise ValueError('Turn diagnostics identity/hash mismatch')
                seen.add(identity)
                if kind=='events':
                    keys=set(IDENTITY)|{'agent_text_sha256','checks','runtime_events','tool_failures',
                        'fallback_observed','runtime_error','model','grounding','verifier_rejected','recovery'}
                    if set(detail)!=keys or any(_check(c)!=c for c in detail['checks']):
                        raise ValueError('Unsafe verifier diagnostics')
                    if any(safe_diagnostic_event(e.get('step'),e.get('event'),e)!=e for e in detail['runtime_events']):
                        raise ValueError('Unsafe runtime diagnostics')
                    if any(detail[k]!=v for k,v in _classify(detail['runtime_events'],detail['checks']).items()):
                        raise ValueError('Unsupported fallback classification')
                    if detail['runtime_error'] is not None and detail['runtime_error'] not in DIAGNOSTIC_ERRORS:
                        raise ValueError('Unsafe runtime error')
                    if detail['fallback_observed'] is not (row['agent_text']==FALLBACK):
                        raise ValueError('Fallback speech binding mismatch')
                    for failure in detail['tool_failures']:
                        if (set(failure)-{'name','error_code','retrieval_status'} or failure.get('name') not in TOOLS|{'other_tool'}
                            or failure.get('error_code') not in TOOL_ERRORS or ('retrieval_status' in failure and failure['retrieval_status'] not in RETRIEVAL_STATUS)):
                            raise ValueError('Unsafe tool failure')
                else:
                    template=stage_evidence({},None,**{k:row[k] for k in IDENTITY})
                    if set(detail)!=set(template)|{'agent_text_sha256'}:
                        raise ValueError('Unsafe stage diagnostics')
                    _validate_stage(detail)
            bindings[kind]={'path':path.name,'sha256':hashlib.sha256(contents).hexdigest()}
        if expected is not None and expected!=bindings:
            raise ValueError('Turn diagnostics provenance mismatch')
        if trace.read_bytes()!=raw:
            raise ValueError('Trace changed during diagnostic audit')
        return bindings
    except (OSError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Missing or invalid turn diagnostics') from exc


def verify_report_turn_diagnostics(trace: Path) -> dict:
    try:
        report=json.loads(Path(trace).with_suffix('.report.json').read_text())
        refs=report['turn_diagnostics']
    except (OSError, KeyError, TypeError) as exc:
        raise ValueError('Runner report lacks turn diagnostics') from exc
    verified = verify_turn_diagnostics(trace,refs)
    if 'execution_health' in report and report['execution_health'] != trace_execution_health(trace):
        raise ValueError('Execution health does not match evidence')
    return verified


def _decision_summary(rows, turns):
    return {'kind': 'summary', 'rows': len(rows), 'observed_turns': len(turns),
            'coverage_complete': len(rows) == len(turns), 'turns': turns,
            'complete': len(rows) == len(turns) and all(not t['missing_components'] and
                not t['missing_checkpoints'] and not t['truncated'] and not t['errors'] for t in turns)}


def _verify_decision_file(path, traces, expected=None):
    from app.mcp_servers.mcp_shared.decision_diagnostics import valid_event
    path = Path(path)
    raw = path.read_bytes()
    records = [json.loads(line) for line in raw.decode().splitlines()]
    bindings = {config: {'path': Path(trace).name, 'sha256': _sha(trace)} for config, trace in traces.items()}
    if not records or records[0] != {'kind': 'metadata', 'schema_version': 1, 'traces': bindings}:
        raise ValueError('Decision diagnostics trace mismatch')
    rows = [json.loads(line) for trace in traces.values() for line in Path(trace).read_text().splitlines()]
    row_map = {tuple(row[k] for k in IDENTITY): row for row in rows}
    summaries = records[-1].get('turns', [])
    if records[-1].get('kind') != 'summary' or records[-1] != _decision_summary(rows, summaries):
        raise ValueError('Invalid decision summary')
    identities = [tuple(t[k] for k in IDENTITY) for t in summaries]
    if len(set(identities)) != len(identities) or set(identities) != set(row_map):
        raise ValueError('Decision coverage mismatch')
    for event in records[1:-1]:
        ident = tuple(event[k] for k in IDENTITY)
        row = row_map.get(ident)
        if row is None or event.get('agent_text_sha256') != _text_sha(row):
            raise ValueError('Decision identity/text mismatch')
        payload = {k: v for k, v in event.items() if k not in set(IDENTITY) | {'kind', 'event_id', 'agent_text_sha256'}}
        if event.get('kind') != 'event' or not valid_event(payload):
            raise ValueError('Unsafe decision event')
    for turn in summaries:
        if (set(turn) != set(IDENTITY) | {'missing_components', 'missing_checkpoints', 'truncated', 'errors'}
                or type(turn['truncated']) is not bool or type(turn['errors']) is not int or turn['errors'] < 0):
            raise ValueError('Unsafe decision summary')
        observed = [e for e in records[1:-1] if all(e[k] == turn[k] for k in IDENTITY)]
        components = {e['component'] for e in observed}
        checkpoints = {e['event'] for e in observed}
        if (turn['missing_components'] != sorted({'runtime', 'memory', 'worker'} - components)
                or turn['missing_checkpoints'] != sorted(DECISION_CHECKPOINTS - checkpoints)):
            raise ValueError('Unsupported decision coverage')
    ids = [e.get('event_id') for e in records[1:-1]]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate decision event')
    ref = {'path': path.name, 'sha256': hashlib.sha256(raw).hexdigest(), 'traces': bindings,
           'complete': records[-1]['complete']}
    if expected is not None and ref != expected:
        raise ValueError('Decision diagnostics checksum mismatch')
    return ref


def verify_decisions(trace, expected):
    return _verify_decision_file(Path(trace).parent / expected['path'],
                                 {next(iter(expected['traces'])): trace}, expected)


def merge_decisions(traces, out):
    from eval_harness.official_pipeline import atomic_bytes
    out = Path(out)
    if out.exists():
        raise ValueError('Refusing existing decision diagnostics')
    events, summaries, rows = [], [], []
    for config, trace in traces.items():
        part = Path(trace).with_suffix('.decisions.jsonl')
        _verify_decision_file(part, {config: trace})
        records = [json.loads(line) for line in part.read_text().splitlines()]
        events.extend(records[1:-1])
        summaries.extend(records[-1]['turns'])
        rows.extend(json.loads(line) for line in Path(trace).read_text().splitlines())
    records = [{'kind': 'metadata', 'schema_version': 1,
                'traces': {c: {'path': Path(p).name, 'sha256': _sha(p)} for c, p in traces.items()}},
               *events, _decision_summary(rows, summaries)]
    atomic_bytes(out, ('\n'.join(json.dumps(r, ensure_ascii=False) for r in records) + '\n').encode())
    return _verify_decision_file(out, traces)


def trace_execution_health(trace: Path) -> str:
    from app.agent.harness.execution_diagnostics import execution_health
    trace = Path(trace)
    verify_turn_diagnostics(trace)
    return execution_health(json.loads(trace.with_suffix('.events.json').read_text()))
