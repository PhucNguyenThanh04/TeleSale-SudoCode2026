import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

from app.mcp_servers.mcp_memory.distiller_worker import process_one


def test_worker_rebuilds_a_full_old_summary_using_the_current_canonical_state():
    async def run():
        repo, projector = AsyncMock(), AsyncMock()

        @asynccontextmanager
        async def transaction():
            yield object()

        repo.transaction = transaction
        session, tid = str(uuid4()), str(uuid4())
        text = 'Tôi đổi sang mua mẫu mới cho phòng làm việc'
        delta = {'topic_updates': [{'scope_type': 'global', 'scope_id': '',
            'customer_goal': text, 'narrative_evidence_quotes': {'customer_goal': text}}]}
        repo.claim_distillation.return_value = {'job_id': 1, 'customer_id': 'C1',
            'session_id': session, 'source_turn_id': tid, 'attempts': 1,
            'accepted_proposals': {'facts': [], 'delta': delta, 'outcome': 'khac'}}
        repo.distillation_turn.return_value = {'customer_text': text, 'agent_text': '',
            'channel': 'hotline', 'on_date': '2026-10-15'}
        repo.is_erasure_blocked.return_value = False
        repo.distillation_claim_current.return_value = True
        projector.list_fact_versions.return_value = []
        projector.put_facts.return_value = []
        projector.list_episode_versions.return_value = [{'schema_version': 1, 'revision': 0,
            'session_id': session, 'status': 'active', 'on': '2026-10-14',
            'summary': 'Thông tin đã thay thế ' + 'x' * 800,
            'topics': [], 'resolved_prior_items': []}]
        assert await process_one(repo, AsyncMock(), projector)
        summary = projector.put_episode.await_args.args[2]['summary']
        assert text in summary
        assert 'Thông tin đã thay thế' not in summary
        assert len(summary) <= 800
    asyncio.run(run())
def test_verified_recent_action_is_present_in_current_summary():
    from app.mcp_servers.mcp_memory.services.episode_summary import build_episode_summary
    summary = build_episode_summary([], [], 800, episode_state={
        'topics': [], 'actions_completed': [{'action': 'schedule.callback',
            'callback_id': 'CB1', 'callback_at': '2026-10-15T10:00+07:00'}]})
    assert 'CB1' in summary and '2026-10-15T10:00+07:00' in summary
