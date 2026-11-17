import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval_harness.knowledge_rollback import rehearse


def btc_data_dir():
    root = Path(__file__).resolve().parents[2]
    for path in (root.parent/'BTC-Data-Vong1-TEAMS', root/'BTC-Data-Vong1-TEAMS'):
        if (path/'policy').is_dir():
            return path
    raise FileNotFoundError('BTC policy fixtures unavailable')


def test_rehearsal_proves_publication_rollback_audit_and_immutable_pins(monkeypatch):
    import app.configs
    def forbidden_settings():
        raise AssertionError('Rehearsal must not load .env or developer credentials')
    monkeypatch.setattr(app.configs, 'get_settings', forbidden_settings)
    report = asyncio.run(rehearse(btc_data_dir()))
    assert app.configs.get_settings is forbidden_settings
    assert report['kind'] == 'offline_knowledge_rollback_rehearsal'
    assert report['review_mode'] == 'simulated_not_human'
    assert report['storage'] == 'in_memory'
    assert report['embedding'] == 'constant_fixture_not_cloudflare'
    assert report['checks'] and all(report['checks'].values())
    for name in ('unapproved_build_rejected', 'draft_not_visible', 'k1_visible', 'pinned_k0_unchanged',
                 'stale_rollback_rejected', 'unauthorized_rollback_rejected',
                 'rollback_restores_k0', 'rollback_audited', 'pinned_k1_preserved',
                 'corpus_unchanged', 'gap_not_auto_resolved'):
        assert report['checks'][name]
    k0, k1 = report['releases']['k0'], report['releases']['k1']
    searches = report['searches']
    key = 'KG-' + report['revision']['id']
    assert searches['k0']['context']['knowledge_release_id'] == k0['release_id']
    assert searches['k1']['context']['knowledge_release_id'] == k1['release_id']
    assert key in {e['chunk_id'] for e in searches['k1']['evidence']}
    assert key not in {e['chunk_id'] for e in searches['rolled_back']['evidence']}
    assert key in {e['chunk_id'] for e in searches['pinned_k1_after_rollback']['evidence']}
    rollbacks = [a for a in report['audit'] if a['action'] == 'rollback_release']
    assert len(rollbacks) == 1
    assert rollbacks[0]['previous_release_id'] == k1['release_id']
    assert rollbacks[0]['release_id'] == k0['release_id']
    assert report['revision']['status'] == 'approved'
    assert report['regression_case']['approved'] is True
    assert report['source_digest_before'] == report['source_digest_after']
    from app.knowledge.schemas import digest
    assert report['runtime_config_hash'] == digest(report['runtime_config'])
    assert report['llm_answer_evaluated'] is False


def test_cli_rehearsal_creates_artifacts_and_refuses_overwrite(tmp_path):
    out = tmp_path/'rollback'
    args = [sys.executable, '-m', 'eval_harness.knowledge_rollback', '--btc-root',
            str(btc_data_dir()), '--out', str(out)]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads((out/'report.json').read_text())
    assert all(report['checks'].values())
    assert 'simulated_not_human' in (out/'report.md').read_text()
    original = (out/'report.json').read_bytes()
    assert subprocess.run(args, capture_output=True).returncode != 0
    assert (out/'report.json').read_bytes() == original


def test_failed_rehearsal_does_not_publish_passed_report(monkeypatch, tmp_path):
    from eval_harness import knowledge_rollback
    async def failed(_):
        return {'checks': {'rollback_restores_k0': False}}
    monkeypatch.setattr(knowledge_rollback, 'rehearse', failed)
    out = tmp_path/'failed'
    monkeypatch.setattr(sys, 'argv', ['rollback', '--btc-root', str(btc_data_dir()), '--out', str(out)])
    with pytest.raises(SystemExit) as exc:
        knowledge_rollback.main()
    assert exc.value.code != 0
    assert not out.exists()


def test_missing_btc_policy_fails_without_creating_output(tmp_path):
    args = [sys.executable, '-m', 'eval_harness.knowledge_rollback', '--btc-root',
            str(tmp_path/'missing'), '--out', str(tmp_path/'out')]
    assert subprocess.run(args, capture_output=True).returncode != 0
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('inside', [True, False])
def test_output_cannot_write_into_btc_package(monkeypatch, tmp_path, inside):
    from eval_harness import knowledge_rollback
    async def forbidden(_):
        raise AssertionError('Reject output location before starting rehearsal')
    monkeypatch.setattr(knowledge_rollback, 'rehearse', forbidden)
    root = tmp_path/'btc'
    out = root/'new-output' if inside else root
    monkeypatch.setattr(sys, 'argv', ['rollback', '--btc-root', str(root), '--out', str(out)])
    with pytest.raises(SystemExit) as exc:
        knowledge_rollback.main()
    assert exc.value.code == 2
    assert not out.exists()
