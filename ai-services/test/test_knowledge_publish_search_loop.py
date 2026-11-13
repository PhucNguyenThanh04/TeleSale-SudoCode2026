"""Real review, hybrid build and policy.search; offline storage/embedding only."""
import asyncio
import pytest
from datetime import date
from pathlib import Path

from fastmcp import Client
from qdrant_client import AsyncQdrantClient

from btc_data import btc_data_dir
from test_knowledge_repo import MemoryRepo
from test_policy_embedding import runtime_config, Backend


@pytest.mark.parametrize('simulated_review', [False, True])
def test_reviewed_faq_reaches_policy_search_only_after_publication(monkeypatch, simulated_review):
    from app.knowledge.policy.source import parse_policy_sources, default_metadata
    from app.knowledge.services.lifecycle import command
    from app.knowledge.services.publish import build_policy_release
    from app.mcp_servers.mcp_knowledge.repos.postgres import PolicyRepository
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    from app.mcp_servers.mcp_knowledge.services.knowledge import PolicySearchService
    from app.mcp_servers.mcp_knowledge.schemas import PolicySearchInput, TrustedPolicyContext
    from app.mcp_servers.mcp_knowledge.tools.handlers import create_server
    from app.mcp_servers.mcp_knowledge.tools.auth import sign_policy_context
    class Repo(MemoryRepo, PolicyRepository):
        pass
    async def run():
        metadata = default_metadata()
        source_dir = btc_data_dir() / 'policy'
        source = next(c for c in parse_policy_sources(source_dir, metadata) if c.chunk_id == 'DT-02')
        repo = Repo([{'chunk_id': source.chunk_id, 'source_hash': source.source_hash,
            'access_level': 'public', 'date_basis': source.date_basis,
            'effective_from': source.effective_from, 'effective_until': source.effective_until,
            'title': 'Điều kiện đổi hàng', 'body': source.content}])
        await repo.put('permissions', 'reviewer', {'permissions': ['knowledge_review']})
        await repo.put('gaps', 'gap', {'id': 'gap', 'category': 'content', 'version': 1, 'status': 'triaged'})
        config = runtime_config(max_tokens=8000, deadline_seconds=10, dependency_timeout_seconds=2)
        from app.configs import get_settings
        settings = get_settings().model_copy(update={'knowledge_policy_config_file': Path('offline-fixture')})
        monkeypatch.setattr('app.configs.get_settings', lambda: settings)
        monkeypatch.setattr('app.mcp_servers.mcp_knowledge.config.load_policy_config', lambda _: config)
        encoder = PolicyEncoder(config, Backend())
        client = AsyncQdrantClient(':memory:')
        index = HybridPolicyIndex(client)
        service = PolicySearchService(repo, encoder, index, config)
        args = dict(source_dir=source_dir, metadata=metadata, actor_id='reviewer')
        try:
            base = await build_policy_release(repo, encoder, index, revision_ids=[], expected_active_id=None, **args)
            await command(repo, 'reviewer', 'activate_release', {'id': base['id'], 'expected_active_id': None})
            question = 'Đổi hàng cần giữ nguyên tem nhãn và hộp không?'
            answer = 'Sản phẩm phải còn nguyên tem, nhãn, hộp, chưa qua sử dụng và có hóa đơn hoặc mã đơn hàng.'
            if simulated_review:
                from eval_harness.knowledge_auto_review import auto_review
                reviewed = await auto_review(repo, repo, {'schema_version': 1, 'reviewed_by': 'domain-expert',
                    'review_note': 'Đối chiếu điều kiện đổi hàng DT-02.', 'cases': [{
                        'id': 'exchange', 'scenario_id': 'LOCAL', 'call': 'call_1', 'turn': 1,
                        'question': question, 'kind': 'faq', 'category': 'content', 'answer': answer,
                        'sources': [{'chunk_id': source.chunk_id, 'source_hash': source.source_hash}],
                        'variations': [question], 'must_say': ['nguyên tem'], 'must_not_say': []}]},
                    [{'scenario_id': 'LOCAL', 'call': 'call_1', 'turn': 1, 'run_id': 'k0', 'config': 'full',
                      'user_text': question, 'agent_text': 'Em chưa có thông tin.', 'tool_calls': [{
                          'name': 'policy.search', 'args': {}, 'result': {'retrieval_status': 'ok',
                          'context': {'on': '2026-11-11', 'order_date': '2026-10-20'}, 'evidence': []}}]}],
                    actor='reviewer', run_id='simulated-experiment')
                revision = await repo.get('revisions', reviewed['approved'][0]['revision_id'])
            else:
                revision = await command(repo, 'reviewer', 'create_revision', {'gap_id': 'gap', 'kind': 'faq',
                    'question': question, 'answer': answer, 'source_ids': ['DT-02'],
                    'source_review_note': 'Đối chiếu điều kiện đổi hàng DT-02.'})
                await command(repo, 'reviewer', 'approve', {'id': revision['id'],
                    'content_hash': revision['content_hash'], 'reason': 'Đã đọc nguồn và test', 'approve_test': True})
            ready = await build_policy_release(repo, encoder, index, revision_ids=[revision['id']],
                                               expected_active_id=base['id'], **args)
            from eval_harness.knowledge_triplet import check_release_extension
            check_release_extension(base, ready, [{'revision_id': revision['id'], 'kind': 'faq'}])
            await service.start()
            async with Client(create_server(service, context_secret='offline-secret')) as mcp:
                async def lookup(pin=None, include=True):
                    request = PolicySearchInput(query=revision['question'], on=date(2026, 11, 11), top_k=10)
                    context = TrustedPolicyContext(request_id='offline', principal='harness', on=request.on,
                        release_id=pin, include_supplements=include, verified_order_date=date(2026, 10, 20),
                        date_source='order.status')
                    result = await mcp.call_tool('policy.search', {**request.model_dump(mode='json'),
                        'trusted_context': sign_policy_context(request, context, 'offline-secret')})
                    return result.data if isinstance(result.data, dict) else result.structured_content
                key = 'KG-' + revision['id']
                before = await lookup()
                assert before['retrieval_status'] == 'ok'
                assert key not in {e['chunk_id'] for e in before['evidence']}
                await command(repo, 'reviewer', 'activate_release', {
                    'id': ready['id'], 'expected_active_id': base['id']})
                after = await lookup()
                assert after['retrieval_status'] == 'ok'
                evidence = next(e for e in after['evidence'] if e['chunk_id'] == key)
                assert revision['answer'] in evidence['content']
                assert 'DT-02' in {e['chunk_id'] for e in after['evidence']}
                for result in (await lookup(base['id']), await lookup(include=False)):
                    assert result['retrieval_status'] == 'ok'
                    assert key not in {e['chunk_id'] for e in result['evidence']}
                assert (await repo.get('gaps', revision['gap_id']))['status'] == 'awaiting_verification'
        finally:
            await encoder.close()
            await client.close()
    asyncio.run(run())
