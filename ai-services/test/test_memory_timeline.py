import asyncio
from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.mcp_servers.mcp_memory.services.timeline import read_timeline


class Repo:
    def __init__(self):
        self.blocked = False
        self.owner_id = 'C1'
        self.sessions = []
        self.completed = {1, 3}
        self.locks = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def lock_key(self, conn, key):
        self.locks.append(key)

    async def is_erasure_blocked(self, conn, customer):
        return self.blocked

    async def owner(self, conn, session):
        return self.owner_id

    async def timeline_sessions(self, conn, customer, on):
        assert customer == 'C1'
        return self.sessions

    async def completed_job_revisions(self, conn, customer, revisions):
        return self.completed & set(revisions)


def projection(versions=()):
    result = AsyncMock()
    result.list_episode_versions.return_value = list(versions)
    return result


def episode(session, on, summary, revision=1, **changes):
    return {'schema_version': 1, 'session_id': session, 'on': on, 'summary': summary,
            'channel': 'hotline', 'outcome': 'hen_goi_lai', 'revision': revision, **changes}


def test_chronological_history_paginates_beyond_retrieval_top_five_and_merges_sources():
    async def run():
        repo = Repo()
        repo.sessions = [{'session_id': f'session-{n}', 'on_date': date(2026, 10, n),
                          'channel': 'zalo_oa' if n == 8 else 'hotline', 'memory_status': 'completed'}
                         for n in range(1, 9)]
        versions = [episode(f'session-{n}', f'2026-10-{n:02}', f'Tư vấn mẫu {n}') for n in range(1, 9)]
        versions += [episode('session-8', '2026-10-08', 'PARTIAL_UNREVIEWED', revision=2),
                     episode('session-5', '2026-10-05', 'DELETED', revision=3, deleted=True),
                     episode('future', '2026-12-01', 'FUTURE')]
        crm = [{'session_id': 'crm-only', 'date': '2026-09-10', 'channel': 'chat_fanpage',
                'summary': 'Khách cần hỏi người nhà', 'outcome': 'hen_goi_lai'},
               {'session_id': 'session-5', 'date': '2026-10-05', 'channel': 'hotline',
                'summary': 'MUST_NOT_RESURRECT', 'outcome': 'khac'}]
        pages = [await read_timeline(repo, 'C1', str(uuid4()), '2026-10-08', offset=n,
                                    limit=3, crm_sessions=crm, projector=projection(versions))
                 for n in (0, 3, 6)]
        assert [p['total'] for p in pages] == [8, 8, 8]
        assert [p['next_offset'] for p in pages] == [3, 6, None]
        items = [item for page in pages for item in page['items']]
        assert [item['session_id'] for item in items] == [
            'session-8', 'session-7', 'session-6', 'session-4', 'session-3', 'session-2', 'session-1', 'crm-only']
        assert items[0]['channel'] == 'zalo_oa'
        assert items[0]['summary'] == 'Tư vấn mẫu 8'
        assert 'PARTIAL_UNREVIEWED' not in str(pages)
        assert 'MUST_NOT_RESURRECT' not in str(pages)
        assert 'FUTURE' not in str(pages)
        assert repo.locks[:2] == ['erasure:C1', 'langmem:C1']
    asyncio.run(run())


def test_pending_session_is_visible_without_exposing_transcript_or_proposals():
    async def run():
        repo = Repo()
        repo.sessions = [{'session_id': 'new', 'on_date': date(2026,10,8), 'channel': 'hotline',
                          'memory_status': 'pending', 'customer_text': 'PRIVATE_TRANSCRIPT'}]
        versions = [episode('new', '2026-10-08', 'PARTIAL', revision=2)]
        result = await read_timeline(repo, 'C1', str(uuid4()), '2026-10-08', projector=projection(versions))
        assert result['items'][0]['summary_status'] == 'pending'
        assert result['items'][0]['summary'] == 'Chưa có bản tóm tắt được xác minh.'
        assert 'PRIVATE_TRANSCRIPT' not in str(result) and 'PARTIAL' not in str(result)
        repo.sessions[0]['memory_status'] = 'completed'
        repo.completed.add(2)
        refreshed = await read_timeline(repo, 'C1', str(uuid4()), '2026-10-08', projector=projection(versions))
        assert refreshed['items'][0]['summary'] == 'PARTIAL'
        assert refreshed['items'][0]['summary_status'] == 'ready'
    asyncio.run(run())


def test_default_outcome_of_last_turn_does_not_erase_verified_session_result():
    async def run():
        repo = Repo()
        repo.sessions = [{'session_id': 'ordered', 'on_date': date(2026,10,8),
                          'channel': 'hotline', 'memory_status': 'completed', 'outcome': 'khac'}]
        versions = [episode('ordered', '2026-10-08', 'Đã đặt hàng', outcome='chot_don')]
        result = await read_timeline(repo, 'C1', str(uuid4()), '2026-10-08', projector=projection(versions))
        assert result['items'][0]['outcome'] == 'chot_don'
    asyncio.run(run())


def test_ownership_and_erasure_fail_closed_before_projection_or_crm_merge():
    async def run():
        repo, store = Repo(), projection()
        repo.owner_id = 'OTHER'
        assert (await read_timeline(repo, 'C1', str(uuid4()), '2026-10-08', projector=store))['error'] == 'session_owner_mismatch'
        repo.owner_id, repo.blocked = 'C1', True
        assert (await read_timeline(repo, 'C1', str(uuid4()), '2026-10-08', projector=store))['error'] == 'customer_erasure_in_progress'
        store.list_episode_versions.assert_not_awaited()
        repo.owner_id, repo.blocked = None, False
        result = await read_timeline(repo, None, str(uuid4()), '2026-10-08', projector=store)
        assert result['status'] == 'not_applicable' and result['items'] == []
    asyncio.run(run())


def test_public_summaries_are_masked_and_same_day_order_is_stable():
    async def run():
        versions = [episode('a', '2026-10-08', 'Gọi lại 0901234567'),
                    episode('b', '2026-10-08', 'Khách cần hỏi người nhà')]
        result = await read_timeline(Repo(), 'C1', str(uuid4()), '2026-10-08', projector=projection(versions))
        assert [r['session_id'] for r in result['items']] == ['b', 'a']
        assert '0901234567' not in str(result)
        assert set(result['items'][0]) == {'session_id', 'on', 'channel', 'summary', 'outcome', 'summary_status'}
    asyncio.run(run())


def test_asof_date_does_not_attach_future_summary_to_an_older_committed_session():
    async def run():
        repo = Repo()
        repo.sessions = [{'session_id': 'same-session', 'on_date': date(2026,10,8),
                          'channel': 'hotline', 'memory_status': 'completed'}]
        versions = [episode('same-session', '2026-10-08', 'Tư vấn trước đó'),
                    episode('same-session', '2026-10-09', 'FUTURE_SECRET', revision=3)]
        result = await read_timeline(repo, 'C1', str(uuid4()), '2026-10-08', projector=projection(versions))
        assert result['items'][0]['summary'] == 'Tư vấn trước đó'
        assert 'FUTURE_SECRET' not in str(result)
        versions[-1]['deleted'] = True
        deleted = await read_timeline(repo, 'C1', str(uuid4()), '2026-10-08', projector=projection(versions))
        assert deleted['items'] == []  # deletion cannot be bypassed by an earlier business date
        versions[0]['deleted'], versions[-1]['deleted'] = True, False
        past_deleted = await read_timeline(repo, 'C1', str(uuid4()), '2026-10-08', projector=projection(versions))
        assert past_deleted['items'] == []  # a future version cannot reactivate history at an earlier date
    asyncio.run(run())


def test_future_crm_summary_cannot_be_attached_to_older_runtime_metadata():
    async def run():
        repo = Repo()
        repo.sessions = [{'session_id': 'same', 'on_date': date(2026,10,8),
                          'channel': 'hotline', 'memory_status': 'pending'}]
        crm = [{'session_id': 'same', 'date': '2026-10-09', 'channel': 'hotline',
                'summary': 'FUTURE_CRM_SECRET', 'outcome': 'chot_don'}]
        result = await read_timeline(repo, 'C1', str(uuid4()), '2026-10-08',
                                     crm_sessions=crm, projector=projection())
        assert result['items'][0]['summary'] == 'Chưa có bản tóm tắt được xác minh.'
        assert 'FUTURE_CRM_SECRET' not in str(result)
    asyncio.run(run())


def test_memory_mcp_adapter_uses_customer_scope_and_rejects_invalid_page(monkeypatch):
    from app.agent.mcp.gateway import MCPGateway
    from app.agent.memory.store import MCPMemoryStore
    from app.mcp_servers.mcp_memory.tools.handlers import create_server
    repo = Repo()
    repo.dsn = 'postgresql://offline'
    monkeypatch.setattr('app.mcp_servers.mcp_memory.tools.handlers.LangMemProjection', lambda _: projection())
    async def run():
        store = MCPMemoryStore(MCPGateway(None, None, create_server(repo)))
        crm = [{'session_id': 'trusted-crm', 'date': '2026-10-07', 'channel': 'zalo_oa',
                'summary': 'Khách cần hỏi người nhà', 'outcome': 'hen_goi_lai'}]
        page = await store.read_timeline(str(uuid4()), 'C1', '2026-10-08', crm_sessions=crm)
        assert page['status'] == 'available'
        assert page['items'][0]['session_id'] == 'trusted-crm' and page['items'][0]['channel'] == 'zalo_oa'
        bad = await store.read_timeline(str(uuid4()), 'C1', '2026-10-08', limit=21)
        assert bad['error'] == 'invalid_args'
    asyncio.run(run())


def test_postgres_metadata_query_is_customer_and_date_scoped_without_relevance_limit():
    from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo
    async def run():
        conn = AsyncMock()
        conn.fetch.return_value = []
        await MemoryRepo('postgresql://offline').timeline_sessions(conn, 'C1', date(2026,10,8))
        sql, customer, on = conn.fetch.await_args.args
        assert customer == 'C1' and on == date(2026,10,8)
        assert 't.customer_id=$1' in sql and 't.on_date<=$2' in sql
        assert 'j.customer_id=t.customer_id' in sql
        assert 'LIMIT 5' not in sql and 'customer_text' not in sql
    asyncio.run(run())
