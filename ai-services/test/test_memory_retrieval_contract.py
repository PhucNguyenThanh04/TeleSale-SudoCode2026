import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agent.harness.context import load_context, prompt_context, _split_facts, _open_episode_items
from app.agent.memory.store import MCPMemoryStore
from app.mcp_servers.mcp_memory.schemas import ReadInput
from app.mcp_servers.mcp_memory.services.memory import read
from test_deep_memory import turn
from test_mcp_memory import TurnRepo


class Repo(TurnRepo):
    async def order_links(self, *_):
        return []


def episode(index, *, sku=None, summary=None, **extra):
    return {'schema_version': 1, 'session_id': f'prior-{index}',
            'on': f'2026-10-{10 + index:02d}', 'summary': summary or f'Phiên {index}',
            'status': 'active', 'topics': [{'scope_type': 'product',
                'scope_id': sku or f'SKU-OTHER-{index}', 'items': []}], **extra}


class RetrievalContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        blocker = patch('socket.socket.connect', side_effect=AssertionError('offline memory regression'))
        blocker.start()
        self.addCleanup(blocker.stop)

    async def test_older_matching_episode_is_selected_before_limit(self):
        projection = AsyncMock()
        projection.list_fact_versions.return_value = []
        projection.list_episode_versions.return_value = [episode(i, sku='SKU-TARGET' if i == 0 else None)
                                                         for i in range(7)]
        result = await read(Repo(), 'C1', str(uuid4()), max_episodes=2,
                            query='Mẫu SKU-TARGET hôm trước', projector=projection)
        assert result['episodes'][0]['session_id'] == 'prior-0'
        assert len(result['episodes']) == 2
        assert len(result['prior_session_ids']) == 7

    async def test_query_by_customer_words_can_find_old_episode_without_sku(self):
        projection = AsyncMock()
        projection.list_fact_versions.return_value = []
        projection.list_episode_versions.return_value = [episode(0, summary='Hỏi máy lọc phòng ngủ')]
        projection.list_episode_versions.return_value += [episode(i) for i in range(1, 7)]
        result = await read(Repo(), 'C1', str(uuid4()), max_episodes=1,
                            query='May loc phong ngu hom truoc', projector=projection)
        assert result['episodes'][0]['session_id'] == 'prior-0'

    async def test_query_cannot_reintroduce_inactive_or_unfinished_revisions(self):
        repo, projection = Repo(), AsyncMock()
        repo.completed_job_revisions = AsyncMock(return_value={1})
        projection.list_fact_versions.return_value = []
        projection.list_episode_versions.return_value = [
            episode(0, sku='SKU-TARGET', revision=1, status='inactive'),
            episode(1, sku='SKU-TARGET', revision=2), episode(2, revision=1)]
        result = await read(repo, 'C1', str(uuid4()), max_episodes=2,
                            query='SKU-TARGET', projector=projection)
        assert [ep['session_id'] for ep in result['episodes']] == ['prior-2']

    async def test_mcp_store_sends_masked_query_and_rejects_malformed_response(self):
        gateway = AsyncMock()
        gateway.invoke.return_value = {'history': [], 'profile': {}, 'episodes': []}
        store = MCPMemoryStore(gateway)
        result = await store.read_context(str(uuid4()), 'C1', query='máy cũ, gọi 0912345678')
        assert 'error' not in result
        args = gateway.invoke.call_args.args[1]
        assert '0912345678' not in args['query'] and 'máy cũ' in args['query']
        gateway.invoke.return_value = {'history': [], 'profile': [], 'episodes': []}
        assert (await store.read_context(str(uuid4()), 'C1'))['error'] == 'invalid_tool_result'

    async def test_harness_passes_query_to_capable_store_and_preserves_legacy_store(self):
        request = turn('Mẫu máy hôm trước')
        state = {'request': request, 'safe_text': request.text, 'customer_id': 'C1',
                 'identity_status': 'known', 'tool_calls': []}
        memory = AsyncMock()
        memory.supports_retrieval_query = True
        memory.include_prior = True
        memory.max_episodes = 5
        memory.read_context.return_value = {'history': [], 'profile': {}, 'episodes': []}
        await load_context(state, memory, AsyncMock(), lambda: datetime.now(timezone.utc))
        memory.read_context.assert_awaited_once_with(str(request.session_id), 'C1', query=request.text)
        memory.supports_retrieval_query = False
        memory.read_context.reset_mock()
        await load_context(state, memory, AsyncMock(), lambda: datetime.now(timezone.utc))
        memory.read_context.assert_awaited_once_with(str(request.session_id), 'C1')

    async def test_harness_fails_closed_on_invalid_memory_envelope(self):
        request = turn('Tôi gọi lại')
        memory = AsyncMock()
        memory.supports_retrieval_query = False
        memory.read_context.return_value = {'history': [], 'profile': [], 'episodes': []}
        result = await load_context({'request': request, 'safe_text': request.text,
            'customer_id': 'C1', 'tool_calls': []}, memory, AsyncMock(), lambda: datetime.now(timezone.utc))
        assert result['tool_failed'] and result['memory_failure'] == 'memory.read'

    def test_fact_evidence_reaches_prompt_and_pii_is_masked(self):
        tid, sid = str(uuid4()), str(uuid4())
        fact = {'value': 5_000_000, 'source_kind': 'customer', 'on': '2026-10-15',
                'evidence_quote': 'Ngân sách 5 triệu, gọi 0912345678',
                'source_turn_id': tid, 'session_id': sid}
        customer, _ = _split_facts({'budget_vnd': fact})
        assert customer['budget_vnd']['source_turn_id'] == tid
        assert customer['budget_vnd']['session_id'] == sid
        assert '0912345678' not in customer['budget_vnd']['evidence_quote']
        request = turn('Nhắc lại ngân sách giúp tôi')
        context = prompt_context({'request': request, 'safe_text': request.text,
            'identity_status': 'known', 'profile': {'budget_vnd': fact}}, 6)
        assert context['customer_facts']['budget_vnd']['source_turn_id'] == tid

    def test_read_schema_retains_query_and_rejects_oversized_query(self):
        from pydantic import ValidationError
        assert ReadInput(session_id=uuid4(), query='máy cũ').model_dump()['query'] == 'máy cũ'
        with pytest.raises(ValidationError):
            ReadInput(session_id=uuid4(), query='x' * 8001)

    async def test_recall_and_source_evidence_cross_the_real_handler_and_context(self):
        from app.mcp_servers.mcp_memory.tools.handlers import _invoke
        repo, projection = Repo(), AsyncMock()
        repo.dsn = 'offline'
        tid = '11111111-1111-4111-8111-111111111111'
        sid = str(uuid4())
        projection.list_fact_versions.return_value = [{
            'schema_version': 1, 'key': 'budget_vnd', 'value': 5_000_000,
            'source_kind': 'customer', 'source_turn_id': tid, 'session_id': sid,
            'on': '2026-10-15', 'evidence_quote': 'Ngân sách 5 triệu, gọi 0912345678'}]
        projection.list_episode_versions.return_value = [episode(i, sku='SKU-TARGET' if i == 0 else None)
                                                         for i in range(7)]
        class Gateway:
            async def invoke(self, name, args):
                return await _invoke(repo, name, args)
        request = turn('Mẫu SKU-TARGET hôm trước')
        state = {'request': request, 'safe_text': request.text, 'customer_id': 'C1',
                 'identity_status': 'known', 'tool_calls': []}
        with patch('app.mcp_servers.mcp_memory.tools.handlers.LangMemProjection', return_value=projection):
            result = await load_context(state, MCPMemoryStore(Gateway(), max_episodes=2),
                                        AsyncMock(), lambda: datetime.now(timezone.utc))
        assert not result.get('tool_failed', False)
        assert result['episodes'][0]['session_id'] == 'prior-0'
        context = prompt_context({**state, **result}, 6)
        fact = context['customer_facts']['budget_vnd']
        assert fact['source_turn_id'] == tid and fact['session_id'] == sid
        assert '0912345678' not in fact['evidence_quote']
        assert fact['on'] == '2026-10-15'

    async def test_include_prior_false_does_not_return_prior_ids_or_episodes(self):
        projection = AsyncMock()
        projection.list_fact_versions.return_value = []
        projection.list_episode_versions.return_value = [episode(0, sku='SKU-TARGET')]
        result = await read(Repo(), 'C1', str(uuid4()), include_prior=False,
                            query='SKU-TARGET', projector=projection)
        assert result['episodes'] == []
        assert result['prior_session_ids'] == []

    async def test_selected_old_episode_keeps_resolution_from_an_unselected_session(self):
        projection = AsyncMock()
        projection.list_fact_versions.return_value = []
        older = episode(0, sku='SKU-TARGET')
        older['topics'][0]['items'] = [{'kind': 'blocker', 'status': 'open',
                                       'item_id': 'b-1', 'text': 'cần hỏi vợ'}]
        newer = episode(6, resolved_prior_items=[{'item_id': 'b-1',
                                                  'evidence_quote': 'vợ đồng ý rồi'}])
        projection.list_episode_versions.return_value = [older, newer]
        result = await read(Repo(), 'C1', str(uuid4()), max_episodes=1,
                            query='SKU-TARGET', projector=projection)
        assert result['episodes'][0]['session_id'] == 'prior-0'
        assert _open_episode_items(result['episodes'], 'blocker') == []
        assert older['topics'][0]['items'][0]['status'] == 'open'

    async def test_query_does_not_bypass_session_owner_or_erasure_barrier(self):
        repo, projection = Repo(), AsyncMock()
        session = str(uuid4())
        repo.rows[session] = [{'customer_id': 'C2'}]
        result = await read(repo, 'C1', session, query='SKU-TARGET', projector=projection)
        assert result == {'error': 'session_owner_mismatch'}
        repo.is_erasure_blocked = AsyncMock(return_value=True)
        result = await read(repo, 'C1', session, query='SKU-TARGET', projector=projection)
        assert result == {'error': 'customer_erasure_in_progress'}
        projection.list_episode_versions.assert_not_called()

    def test_response_schema_rejects_missing_required_envelope_fields(self):
        from app.mcp_servers.mcp_memory.schemas import validate_read_response
        for invalid in ({}, {'profile': {}}, {'history': [], 'profile': {} , 'schema_version': 2}):
            assert validate_read_response(invalid) == {'error': 'invalid_tool_result'}
        legacy = {'history': [{'customer': 'Xin chào'}], 'profile': {}, 'custom_meta': 'kept'}
        assert validate_read_response(legacy) == legacy
