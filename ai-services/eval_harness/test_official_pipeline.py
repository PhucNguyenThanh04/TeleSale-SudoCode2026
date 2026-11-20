
import json
import hashlib
from pathlib import Path

import pytest

from eval_harness.official_pipeline import publish_pair


ROOT = Path(__file__).resolve().parents[2]
BTC = ROOT.parent / "BTC-Data-Vong1-TEAMS"


def _case(tmp_path):
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    (scenarios / "case.json").write_text(json.dumps({
        "scenario_id": "LOCAL-01", "calls": {"call_1": {
            "customer_turns": ["Xin chào"]}}}), encoding="utf-8")
    identity = {"database": "telesale", "host": "localhost", "port": 5432}
    paths = {}
    for config in ("full", "baseline_no_memory"):
        path = tmp_path / f"{config}.jsonl"
        row = {"run_id": f"run-{config}", "config": config,
               "scenario_id": "LOCAL-01", "call": "call_1", "turn": 1,
               "customer_text": "Xin chào", "agent_text": "Dạ chào anh/chị",
               "questions": [], "claims": [], "tool_calls": [],
               "latency": {"ttft_ms": 4, "total_ms": 4}}
        path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        path.with_suffix(".report.json").write_text(json.dumps({
            "run_id": row["run_id"], "config": config,
            "database_identity": identity}), encoding="utf-8")
        paths[config] = path
    metadata = dict(source_digest="source", seed_id="seed-7", seed_digest="seed-hash",
                    model_id="model-A", model_params={"temperature": 0},
                    tool_mode="mcp", guardrails={"enabled": True},
                    database_identity=identity, hardware={"cpu": "test"},
                    started_at_utc="2026-11-01T00:00:00Z",
                    expected_database="telesale", app_env="test")
    return scenarios, paths, metadata


def test_publish_pair_matches_btc_and_writes_manifests(tmp_path):
    scenarios, paths, metadata = _case(tmp_path)
    result = publish_pair(scenarios, paths["full"], paths["baseline_no_memory"],
                          tmp_path / "score.json", metadata, btc_root=BTC)
    assert result["score"]["n_scenarios"] == 1
    assert result["manifests"]["full"]["trace_rows"] == 1
    assert (tmp_path / "full.manifest.json").is_file()
    assert (tmp_path / "baseline_no_memory.manifest.json").is_file()


def test_voice_latency_fields_and_metadata_preserve_btc_compatibility(tmp_path):
    from eval_harness.benchmark_runner import CONVERSATION_MEASUREMENT
    scenarios, paths, metadata = _case(tmp_path)
    metadata['model_params']['conversation_measurement'] = CONVERSATION_MEASUREMENT
    for path in paths.values():
        row = json.loads(path.read_text())
        row['latency'].update(response_ms=4, prepare_ms=2, memory_finalize_ms=7, ttft_is_proxy=True)
        path.write_text(json.dumps(row) + '\n')
    result = publish_pair(scenarios, paths['full'], paths['baseline_no_memory'],
                          tmp_path / 'score.json', metadata, btc_root=BTC)
    assert result['status'] == 'validated'
    for manifest in result['manifests'].values():
        assert manifest['model_params']['conversation_measurement'] == CONVERSATION_MEASUREMENT
    assert result['score']['system']['latency']['total']['p50_ms'] == 4


def test_published_score_bytes_match_provenance(tmp_path):
    scenarios, paths, metadata = _case(tmp_path)
    score = tmp_path / 'score.json'
    publish_pair(scenarios, paths['full'], paths['baseline_no_memory'], score, metadata, btc_root=BTC)
    digest = hashlib.sha256(score.read_bytes()).hexdigest()
    assert json.loads(score.with_suffix('.inputs.json').read_text())['score_sha256'] == digest
    from eval.trace_audit import build_manifest, audit_pair
    rebuilt = {}
    for config, trace in paths.items():
        manifest = json.loads((tmp_path / f'{config}.manifest.json').read_text())
        assert manifest['scorer_report_sha256'] == digest
        rebuilt[config] = build_manifest(trace_path=trace, scenarios_dir=scenarios,
            config=config, scorer_report_path=score, btc_root=BTC, **metadata)
        assert rebuilt[config] == manifest
    assert audit_pair(rebuilt['full'], rebuilt['baseline_no_memory']) == []


@pytest.mark.parametrize('filename', ['full.manifest.json', 'baseline_no_memory.manifest.json', 'score.inputs.json'])
def test_existing_publication_is_never_overwritten(tmp_path, filename):
    scenarios, paths, metadata = _case(tmp_path)
    existing = tmp_path / filename
    existing.write_bytes(b'previous artifact')
    with pytest.raises(ValueError, match='existing'):
        publish_pair(scenarios, paths['full'], paths['baseline_no_memory'],
                     tmp_path / 'score.json', metadata, btc_root=BTC)
    assert existing.read_bytes() == b'previous artifact'


def test_final_score_tampering_cannot_return_success(tmp_path, monkeypatch):
    import eval_harness.official_pipeline as pipeline
    scenarios, paths, metadata = _case(tmp_path)
    original = getattr(pipeline, 'atomic_bytes', None)
    assert original is not None, 'publication requires a byte-preserving writer'
    def corrupt(path, payload):
        original(path, payload + b' ')
    monkeypatch.setattr(pipeline, 'atomic_bytes', corrupt)
    with pytest.raises(ValueError, match='provenance'):
        pipeline.publish_pair(scenarios, paths['full'], paths['baseline_no_memory'],
                              tmp_path / 'score.json', metadata, btc_root=BTC)


def test_atomic_bytes_replace_failure_leaves_no_final_file(tmp_path, monkeypatch):
    import eval_harness.official_pipeline as pipeline
    writer = getattr(pipeline, 'atomic_bytes', None)
    assert writer is not None
    def fail(*args):
        raise OSError('synthetic replace failure')
    monkeypatch.setattr(Path, 'replace', fail)
    with pytest.raises(OSError):
        writer(tmp_path / 'final.json', b'{"a":1}')
    assert not list(tmp_path.iterdir())


def test_invalid_trace_never_publishes_score(tmp_path):
    scenarios, paths, metadata = _case(tmp_path)
    paths["full"].write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Trace audit failed"):
        publish_pair(scenarios, paths["full"], paths["baseline_no_memory"],
                     tmp_path / "score.json", metadata, btc_root=BTC)
    assert not (tmp_path / "score.json").exists()


@pytest.mark.parametrize("field", [
    {"memory_error": "job_failed"}, {"agent_text": "[ERROR: RuntimeError]"}])
def test_operational_failure_never_publishes_score(tmp_path, field):
    scenarios, paths, metadata = _case(tmp_path)
    row = json.loads(paths["full"].read_text())
    paths["full"].write_text(json.dumps({**row, **field}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Trace audit failed"):
        publish_pair(scenarios, paths["full"], paths["baseline_no_memory"],
                     tmp_path / "score.json", metadata, btc_root=BTC)
    assert not (tmp_path / "score.json").exists()


def test_redaction_invalid_never_publishes_official_score(tmp_path):
    scenarios, paths, metadata = _case(tmp_path)
    issue = dict(code='redaction_affects_scoring',type='pii_violation',path='agent_text',
                 scenario_id='X',call='call_1',turn=1)
    result = publish_pair(scenarios, paths['full'], paths['baseline_no_memory'],
        tmp_path/'btc_score.json', metadata, btc_root=BTC, safety_issues=[issue])
    assert result['status']=='invalid'
    assert not (tmp_path/'btc_score.json').exists()
    assert json.loads((tmp_path/'full.manifest.json').read_text())['safety_issues']==[issue]


def test_publisher_requires_complete_bound_diagnostics_when_requested(tmp_path):
    from eval_harness.extraction_report import write_extraction_sidecar, verify_extraction_report, sha256
    scenarios, paths, metadata = _case(tmp_path)
    sides = {c: tmp_path / f'{c}.extraction.jsonl' for c in paths}
    for config, trace in paths.items(): write_extraction_sidecar(trace, sides[config])
    result = publish_pair(scenarios, paths['full'], paths['baseline_no_memory'], tmp_path/'score.json',
        metadata, btc_root=BTC, extraction_sidecars=sides)
    report = verify_extraction_report(tmp_path / result['extraction_report']['path'])
    assert result['extraction_report']['sha256'] == sha256(tmp_path/'extraction_report.json')
    assert result['extraction_status'] == report['extraction_status']


def test_tampered_sidecar_never_returns_validated(tmp_path):
    from eval_harness.extraction_report import write_extraction_sidecar
    scenarios, paths, metadata = _case(tmp_path)
    sides = {c: tmp_path / f'{c}.extraction.jsonl' for c in paths}
    for config, trace in paths.items(): write_extraction_sidecar(trace, sides[config])
    sides['full'].write_text('')
    with pytest.raises(ValueError):
        publish_pair(scenarios, paths['full'], paths['baseline_no_memory'], tmp_path/'score.json',
            metadata, btc_root=BTC, extraction_sidecars=sides)


def test_score_changed_while_publishing_summary_fails_final_check(tmp_path, monkeypatch):
    import eval_harness.official_pipeline as pipeline
    from eval_harness.extraction_report import write_extraction_sidecar
    scenarios, paths, metadata = _case(tmp_path)
    sides={c:tmp_path/f'{c}.extraction.jsonl' for c in paths}
    for c,t in paths.items(): write_extraction_sidecar(t, sides[c])
    original=pipeline.atomic_json
    def inject(path, value):
        original(path, value)
        if path.name == 'extraction_report.json':
            with (tmp_path/'score.json').open('ab') as stream: stream.write(b' ')
    monkeypatch.setattr(pipeline,'atomic_json',inject)
    with pytest.raises(ValueError):
        pipeline.publish_pair(scenarios,paths['full'],paths['baseline_no_memory'],tmp_path/'score.json',
            metadata,btc_root=BTC,extraction_sidecars=sides)


def _turn_sidecars(paths):
    from types import SimpleNamespace
    from eval_harness.turn_diagnostics import TurnDiagnostics
    for config,trace in paths.items():
        collector=TurnDiagnostics()
        for line in trace.read_text().splitlines():
            row=json.loads(line)
            collector.observe(SimpleNamespace(session_id='now'),None,{},row,[])
        refs=collector.write(trace)
        path=trace.with_suffix('.report.json')
        report=json.loads(path.read_text());report['turn_diagnostics']=refs;path.write_text(json.dumps(report))


def test_publisher_binds_required_turn_diagnostics(tmp_path):
    scenarios,paths,metadata=_case(tmp_path)
    _turn_sidecars(paths)
    result=publish_pair(scenarios,paths['full'],paths['baseline_no_memory'],tmp_path/'score.json',metadata,
        btc_root=BTC,require_turn_diagnostics=True)
    assert set(result['turn_diagnostics'])==set(paths)
    for config,trace in paths.items():
        from eval_harness.turn_diagnostics import verify_turn_diagnostics
        assert verify_turn_diagnostics(trace,result['turn_diagnostics'][config])==result['turn_diagnostics'][config]


@pytest.mark.parametrize('damage',['missing','tamper','late_tamper'])
def test_required_turn_diagnostics_failure_cannot_publish_validated(tmp_path,monkeypatch,damage):
    import eval_harness.official_pipeline as pipeline
    scenarios,paths,metadata=_case(tmp_path)
    _turn_sidecars(paths)
    target=paths['full'].with_suffix('.events.json')
    if damage=='missing': target.unlink()
    elif damage=='tamper': target.write_text('[]')
    else:
        original=pipeline.atomic_bytes
        def corrupt(path,payload):
            original(path,payload)
            if path.name=='score.json': target.write_text('[]')
        monkeypatch.setattr(pipeline,'atomic_bytes',corrupt)
    with pytest.raises(ValueError):
        pipeline.publish_pair(scenarios,paths['full'],paths['baseline_no_memory'],tmp_path/'score.json',metadata,
            btc_root=BTC,require_turn_diagnostics=True)


def test_optional_decision_reference_is_in_both_manifests_without_changing_btc_score(tmp_path):
    scenarios, paths, metadata = _case(tmp_path)
    from eval_harness.turn_diagnostics import TurnDiagnostics, merge_decisions
    from app.mcp_servers.mcp_shared.decision_diagnostics import capture_decisions, emit
    for trace in paths.values():
        row = json.loads(trace.read_text())
        collector = TurnDiagnostics()
        with capture_decisions() as capture:
            emit('gate_result', status='blocked', reason='identity_required')
        collector.observe_decisions(row, capture)
        collector.write_decisions(trace)
    ref = merge_decisions(paths, tmp_path / 'decision_diagnostics.jsonl')
    result = publish_pair(scenarios, paths['full'], paths['baseline_no_memory'],
        tmp_path / 'score.json', metadata, btc_root=BTC, decision_diagnostics=ref)
    assert result['status'] == 'validated' and result['score']['n_scenarios'] == 1
    for manifest in result['manifests'].values():
        assert manifest['decision_diagnostics'] == ref
    assert 'decision_diagnostics' not in (tmp_path / 'score.json').read_text()


def test_execution_health_is_derived_and_does_not_change_btc_score(tmp_path):
    from types import SimpleNamespace
    from eval_harness.turn_diagnostics import TurnDiagnostics
    scenarios, paths, metadata = _case(tmp_path)
    for config, trace in paths.items():
        row = json.loads(trace.read_text())
        status = 'failed' if config == 'full' else 'succeeded'
        events = [{'step': 'execution', 'event': 'phase_result', 'phase': 'model_invocation',
                   'invocation': 'initial', 'status': status},
                  {'step': 'execution', 'event': 'phase_result', 'phase': 'postprocess', 'status': 'succeeded'}]
        collector = TurnDiagnostics()
        collector.observe(SimpleNamespace(session_id='test'), None, {}, row, events)
        refs = collector.write(trace)
        report = json.loads(trace.with_suffix('.report.json').read_text())
        report['turn_diagnostics'] = refs
        trace.with_suffix('.report.json').write_text(json.dumps(report))
    result = publish_pair(scenarios, paths['full'], paths['baseline_no_memory'],
        tmp_path/'score.json', metadata, btc_root=BTC, require_turn_diagnostics=True)
    assert result['status'] == 'validated'
    assert result['execution_health'] == 'degraded'
    assert result['manifests']['full']['execution_health'] == 'degraded'
    assert result['manifests']['baseline_no_memory']['execution_health'] == 'healthy'
