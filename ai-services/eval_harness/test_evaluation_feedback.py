"""Evaluations enter the existing feedback queue with source hashes and review gates."""
import asyncio
import json
from pathlib import Path

from eval_harness.test_official_pipeline import _case, BTC
from eval_harness.official_pipeline import publish_pair


def failed_run(tmp_path):
    scenarios, traces, metadata = _case(tmp_path)
    path = scenarios / 'case.json'
    case = json.loads(path.read_text())
    case['calls']['call_1']['success_if'] = {'must_say_any': ['not in reply']}
    path.write_text(json.dumps(case))
    result = publish_pair(scenarios, traces['full'], traces['baseline_no_memory'],
                          tmp_path / 'btc_score.json', metadata, btc_root=BTC)
    (tmp_path / 'run.json').write_text(json.dumps({'status': result['status'],
        'run_id': 'fixture', 'score': 'btc_score.json',
        'traces': {key: path.name for key, path in traces.items()},
        'manifests': {key: key + '.manifest.json' for key in traces}}))


def test_score_failure_export_is_repeatable_and_does_not_change_saved_run(tmp_path):
    from eval_harness.evaluation_feedback import build_feedback
    failed_run(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    events = build_feedback(tmp_path, btc_root=BTC)
    assert len(events) == 1
    assert events == build_feedback(tmp_path, btc_root=BTC)
    assert events[0]['event']['source'] == 'evaluation_result'
    assert events[0]['event']['signal'] == 'execution_unverified'
    from eval.score_pair import _sha
    assert events[0]['event']['score_sha256'] == _sha(tmp_path / 'btc_score.json')
    assert {p: p.read_bytes() for p in before} == before


def test_unhealthy_execution_feedback_is_technical_and_never_drafts_policy(tmp_path, monkeypatch):
    from eval_harness.evaluation_feedback import build_feedback
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'test'))
    from test_knowledge_repo import MemoryRepo
    from test_knowledge_revisions import SOURCE
    from app.knowledge.events.ingest import record_event
    from app.knowledge.events.worker import process_one

    failed_run(tmp_path)
    event = build_feedback(tmp_path, btc_root=BTC)[0]
    repo = MemoryRepo([{**SOURCE, 'title': 'Xin chào', 'body': 'Xin chào'}])

    async def run():
        a = await record_event(repo, **event)
        b = await record_event(repo, **event)
        assert a['id'] == b['id']
        await process_one(repo, 'offline-worker')
        gaps = await repo.rows('gaps')
        assert len(gaps) == 1
        assert gaps[0]['category'] == 'technical'
        assert await repo.rows('revisions') == []

    asyncio.run(run())


def test_score_hash_is_preserved_as_typed_provenance_even_when_all_digits():
    from app.knowledge.events.evidence import snapshot
    event = snapshot({'source': 'evaluation_result', 'question': 'Chào', 'score_sha256': '0' * 64})
    assert event['score_sha256'] == '0' * 64
