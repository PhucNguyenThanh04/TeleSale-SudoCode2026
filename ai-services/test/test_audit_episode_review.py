import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta


def resolution():
    return {'topic_updates': [{'scope_type': 'global', 'scope_id': '', 'resolve_items': [
        {'item_id': 'waiting-for-spouse', 'evidence_quote': 'Tôi vẫn chưa hỏi được ý kiến chồng'}]}]}


def test_a_literal_quote_cannot_resolve_a_prior_item_without_independent_review():
    with pytest.raises(ValueError, match='review'):
        apply_episode_delta({}, resolution(), source_turn_id=str(uuid4()),
            customer_text='Tôi vẫn chưa hỏi được ý kiến chồng', agent_text='',
            prior_open_items={'waiting-for-spouse': ('global', '')})


def test_episode_reviewer_receives_original_item_and_the_complete_current_turn():
    from app.agent.memory.episode_review import review_episode_resolutions
    seen = {}

    async def review(messages):
        seen.update(json.loads(messages[-1].content))
        return {'decisions': [{'item_id': 'waiting-for-spouse', 'resolved': False,
                               'reason': 'not_resolved'}]}

    model = SimpleNamespace(with_structured_output=lambda *a, **k: SimpleNamespace(ainvoke=review))
    items = [{'item_id': 'waiting-for-spouse', 'scope_type': 'global', 'scope_id': '',
              'kind': 'blocker', 'text': 'Cần hỏi ý kiến chồng trước khi chọn máy'}]
    turn = {'customer_text': 'Tôi vẫn chưa hỏi được ý kiến chồng', 'agent_text': 'Dạ'}
    assert asyncio.run(review_episode_resolutions(model, resolution(), turn, items)) == frozenset()
    assert seen['open_items'] == items and seen['turn'] == turn
    assert seen['proposals'][0]['evidence_quote'] == turn['customer_text']


def test_supported_review_cannot_resolve_a_different_item_or_skip_source_checks():
    delta = resolution()
    with pytest.raises(ValueError):
        apply_episode_delta({}, delta, source_turn_id=str(uuid4()),
            customer_text='Tôi vẫn chưa hỏi được ý kiến chồng', agent_text='',
            prior_open_items={'waiting-for-spouse': ('global', '')},
            reviewed_resolution_ids=frozenset({'different-item'}))


def test_reviewer_failure_cannot_create_resolution_authority():
    from app.agent.memory.episode_review import EpisodeReviewUnavailable, review_episode_resolutions

    async def fail(messages):
        raise TimeoutError('offline')

    model = SimpleNamespace(with_structured_output=lambda *a, **k: SimpleNamespace(ainvoke=fail))
    with pytest.raises(EpisodeReviewUnavailable):
        asyncio.run(review_episode_resolutions(model, resolution(), {'customer_text': 'Chưa hỏi chồng'}, []))


def test_unambiguous_supported_review_returns_only_the_proposed_item_id():
    from app.agent.memory.episode_review import review_episode_resolutions

    async def supported(messages):
        return {'decisions': [{'item_id': 'waiting-for-spouse', 'resolved': True, 'reason': 'supported'}]}

    model = SimpleNamespace(with_structured_output=lambda *a, **k: SimpleNamespace(ainvoke=supported))
    delta = resolution()
    delta['topic_updates'][0]['resolve_items'][0]['evidence_quote'] = 'Chồng tôi đồng ý rồi'
    ids = asyncio.run(review_episode_resolutions(model, delta,
        {'customer_text': 'Chồng tôi đồng ý rồi'}, [{'item_id': 'waiting-for-spouse'}]))
    assert ids == frozenset({'waiting-for-spouse'})


@pytest.mark.parametrize('decision', [None, False, True])
def test_worker_applies_only_independently_reviewed_resolutions(decision):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock
    from app.mcp_servers.mcp_memory.distiller_worker import process_one

    async def run():
        repo, projector = AsyncMock(), AsyncMock()

        @asynccontextmanager
        async def transaction():
            yield object()

        repo.transaction = transaction
        session, tid = str(uuid4()), str(uuid4())
        delta = resolution()
        text = 'Chồng tôi đồng ý rồi' if decision else 'Tôi vẫn chưa hỏi được ý kiến chồng'
        delta['topic_updates'][0]['resolve_items'][0]['evidence_quote'] = text
        repo.claim_distillation.return_value = {'job_id': 1, 'customer_id': 'C1',
            'session_id': session, 'source_turn_id': tid, 'attempts': 1,
            'accepted_proposals': {'facts': [], 'delta': delta, 'outcome': 'khac'}}
        repo.distillation_turn.return_value = {'customer_text': text,
            'agent_text': '', 'channel': 'hotline', 'on_date': '2026-10-15'}
        repo.is_erasure_blocked.return_value = False
        repo.distillation_claim_current.return_value = True
        projector.list_fact_versions.return_value = []
        projector.put_facts.return_value = []
        projector.list_episode_versions.return_value = [{'schema_version': 1, 'revision': 0,
            'session_id': str(uuid4()), 'status': 'active', 'on': '2026-10-14',
            'topics': [{'scope_type': 'global', 'scope_id': '', 'items': [
                {'item_id': 'waiting-for-spouse', 'text': 'Cần hỏi ý kiến chồng',
                 'kind': 'blocker', 'status': 'open'}]}], 'resolved_prior_items': []}]
        reviewer = None if decision is None else AsyncMock(return_value=(
            frozenset({'waiting-for-spouse'}) if decision else frozenset()))
        assert await process_one(repo, AsyncMock(), projector, episode_reviewer=reviewer)
        assert repo.finish_distillation.await_args.args[2] == 'completed'
        written = projector.put_episode.await_args.args[2]
        assert bool(written['resolved_prior_items']) is bool(decision)
        if reviewer is not None:
            assert reviewer.await_args.args[2][0]['text'] == 'Cần hỏi ý kiến chồng'
    asyncio.run(run())
