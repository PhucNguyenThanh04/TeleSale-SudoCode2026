import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import UUID, uuid4
import pytest

from app.mcp_servers.mcp_memory.services.memory import read


class Repo:
    def __init__(self):
        self.sessions = {}
        self.blocked = False
        self.evidence_reads = []

    @asynccontextmanager
    async def transaction(self):
        yield None

    async def lock_key(self, *args):
        pass

    async def is_erasure_blocked(self, conn, customer):
        return self.blocked

    async def owner(self, conn, session):
        return self.sessions.get(session, {}).get('owner')

    async def recent_turns(self, conn, session, limit):
        return self.sessions.get(session, {}).get('turns', [])[-limit:]

    async def turn_count(self, conn, session):
        return len(self.sessions.get(session, {}).get('turns', []))

    async def recent_customer_sessions(self, conn, customer, limit):
        return [{'session_id': sid, 'on_date': data['turns'][-1]['on_date'], 'channel': data['turns'][-1]['channel']}
                for sid, data in reversed(list(self.sessions.items())) if data['owner'] == customer][:limit]

    async def recent_session_turns(self, conn, session, customer, through_turn_no, limit=None):
        self.evidence_reads.append(session)
        assert self.sessions[session]['owner'] == customer
        rows = self.sessions[session]['turns'][:through_turn_no]
        return deepcopy(rows[-limit:] if limit else rows)

    async def order_links(self, conn, customer):
        return []


class Projection:
    async def list_fact_versions(self, customer):
        return []

    async def list_episode_versions(self, customer):
        return []


def add_turn(repo, session, customer, text, reply='Dạ.', calls=None):
    tid = str(uuid4())
    repo.sessions.setdefault(session, {'owner': customer, 'turns': []})['turns'].append({
        'client_msg_id': tid, 'customer_text': text, 'agent_text': reply,
        'on_date': '2026-11-05', 'channel': 'hotline', 'tool_observations': calls or []})
    return tid


def test_immediate_channel_switch_without_any_projected_episode():
    repo = Repo()
    prior, current = str(uuid4()), str(uuid4())
    tid = add_turn(repo, prior, 'C1', 'Phòng tôi 25 m², ngân sách 5 triệu. Để tôi hỏi chồng.',
        calls=[{'name': 'catalog.search', 'args': {}, 'result': {'items': [
            {'sku': 'SKU-ASTER', 'name': 'Aster', 'variants': []}]}}])
    add_turn(repo, prior, 'C1', 'Tôi chọn Aster để xem giá.')
    result = asyncio.run(read(repo, 'C1', current, projector=Projection()))
    assert result['profile'] == {}
    episode = result['episodes'][0]
    assert episode['session_id'] == prior
    assert episode['committed_turns'][0]['source_turn_id'] == tid
    assert episode['committed_turns'][0]['customer'] == repo.sessions[prior]['turns'][0]['customer_text']
    assert episode['committed_turns'][1]['customer'] == 'Tôi chọn Aster để xem giá.'
    assert episode['topics'] == []
    assert repo.evidence_reads.count(prior) == 1



def test_baseline_sees_current_state_but_no_prior_customer_facts():
    repo = Repo()
    prior, current = str(uuid4()), str(uuid4())
    add_turn(repo, prior, 'C1', 'Phòng tôi 25 m², ngân sách 5 triệu.')
    add_turn(repo, current, 'C1', 'Ngân sách của tôi là 3 triệu.')
    result = asyncio.run(read(repo, 'C1', current, include_prior=False, projector=Projection()))
    assert result['profile'] == {}
    assert result['history'][0]['customer'] == 'Ngân sách của tôi là 3 triệu.'
    assert result['episodes'] == [] and result['prior_session_ids'] == []


def test_later_customer_change_remains_in_ordered_source_turns_before_worker():
    repo = Repo()
    sid = str(uuid4())
    add_turn(repo, sid, 'C1', 'Ngân sách 5 triệu.')
    latest = add_turn(repo, sid, 'C1', 'Tôi đổi ngân sách thành 3 triệu.')
    result = asyncio.run(read(repo, 'C1', sid, projector=Projection()))
    assert result['profile'] == {}
    assert result['history'][-1]['source_turn_id'] == latest
    assert result['history'][-1]['customer'] == 'Tôi đổi ngân sách thành 3 triệu.'


@pytest.mark.parametrize('failure', [
    {'error': 'provider error with private 0912345678'}, {'ok': False}, {'success': False}])
def test_committed_failed_refresh_is_restored_as_barrier_without_private_error(failure):
    from app.mcp_servers.mcp_shared.memory_observations import memory_observations
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    from test_commerce_evidence import state, quote
    repo = Repo()
    sid = str(uuid4())
    quoted = quote()
    add_turn(repo, sid, 'C1', 'Báo giá Aster.', calls=memory_observations([quoted]))
    add_turn(repo, sid, 'C1', 'Kiểm tra lại giá.', calls=memory_observations([
        {**quoted, 'result': failure}]))
    loaded = asyncio.run(read(repo, 'C1', sid, projector=Projection()))
    calls = loaded['session_tool_calls']
    assert len(calls) == 2 and 'error' in calls[-1]['result']
    assert '0912345678' not in str(calls)
    current = state('Giá vẫn vậy chứ?')
    current.update(customer_id='C1', session_tool_calls=calls)
    current['request'] = current['request'].model_copy(update={'session_id': UUID(sid)})
    assert not any(call['name'] == 'pricing.get_quote' for call in build_commerce_evidence(current))


def test_erasure_and_owner_boundaries_cover_operational_views():
    repo = Repo()
    sid = str(uuid4())
    add_turn(repo, sid, 'C1', 'Ngân sách 5 triệu.')
    assert asyncio.run(read(repo, 'OTHER', sid, projector=Projection()))['error'] == 'session_owner_mismatch'
    result = asyncio.run(read(repo, 'OTHER', str(uuid4()), projector=Projection()))
    assert result['profile'] == {} and result['episodes'] == []
    repo.blocked = True
    assert asyncio.run(read(repo, 'C1', str(uuid4()), projector=Projection()))['error'] == 'customer_erasure_in_progress'


def test_pending_long_call_exposes_bounded_history_without_inventing_selection():
    repo = Repo()
    sid = str(uuid4())
    add_turn(repo, sid, 'C1', 'Tôi chọn Aster để xem giá.', calls=[
        {'name': 'catalog.search', 'args': {}, 'result': {'items': [
            {'sku': 'SKU-ASTER', 'name': 'Aster', 'variants': []}]}}])
    for _ in range(16):
        add_turn(repo, sid, 'C1', 'Em nói tiếp nhé.')
    result = asyncio.run(read(repo, 'C1', sid, projector=Projection()))
    assert result['current_episode']['topics'] == []
    assert result['current_episode']['turn_count'] == 17
    assert len(result['current_episode']['committed_turns']) == 12


def test_resolved_blocker_does_not_reappear_while_worker_is_pending():
    repo = Repo()
    sid = str(uuid4())
    add_turn(repo, sid, 'C1', 'Để tôi hỏi chồng.')
    add_turn(repo, sid, 'C1', 'Chồng tôi đồng ý rồi.')
    result = asyncio.run(read(repo, 'C1', sid, projector=Projection()))
    assert 'blocker' not in result['profile']


def test_pending_approval_is_retained_as_source_without_classifying_blocker():
    repo = Repo()
    sid = str(uuid4())
    add_turn(repo, sid, 'C1', 'Để tôi hỏi chồng.')
    add_turn(repo, sid, 'C1', 'Nếu chồng tôi đồng ý thì tôi gọi lại nhé.')
    result = asyncio.run(read(repo, 'C1', sid, projector=Projection()))
    assert result['profile'] == {}
    assert len(result['history']) == 2
    assert result['history'][-1]['customer'] == 'Nếu chồng tôi đồng ý thì tôi gọi lại nhé.'


def test_old_pending_fact_cannot_resurrect_newer_deleted_projection():
    repo = Repo()
    sid = str(uuid4())
    add_turn(repo, sid, 'C1', 'Ngân sách 5 triệu.')
    repo.sessions[sid]['turns'][0].update(job_id=10, memory_status='pending')
    class DeletedProjection(Projection):
        async def list_fact_versions(self, customer):
            return [{'schema_version': 1, 'key': 'budget_vnd', 'scope_type': 'global',
                     'scope_id': '', 'revision': 20, 'deleted': True}]
    result = asyncio.run(read(repo, 'C1', sid, projector=DeletedProjection()))
    assert 'budget_vnd' not in result['profile']
    add_turn(repo, sid, 'C1', 'Ngân sách 3 triệu.')
    repo.sessions[sid]['turns'][-1].update(job_id=30, memory_status='pending')
    result = asyncio.run(read(repo, 'C1', sid, projector=DeletedProjection()))
    assert 'budget_vnd' not in result['profile']
    source = result['history'] or result['episodes'][0]['committed_turns']
    assert source[-1]['customer'] == 'Ngân sách 3 triệu.'


def test_newest_unprojected_session_is_returned_first():
    repo = Repo()
    older, newer, current = str(uuid4()), str(uuid4()), str(uuid4())
    add_turn(repo, older, 'C1', 'Ngân sách 5 triệu.')
    add_turn(repo, newer, 'C1', 'Ngân sách 3 triệu.')
    result = asyncio.run(read(repo, 'C1', current, projector=Projection()))
    assert [episode['session_id'] for episode in result['episodes']] == [newer, older]
    assert 'budget_vnd' not in result['profile']
    source = result['history'] or result['episodes'][0]['committed_turns']
    assert source[-1]['customer'] == 'Ngân sách 3 triệu.'


def test_committed_callback_is_immediately_visible_without_worker_status_field():
    from app.mcp_servers.mcp_shared.memory_observations import memory_observations
    repo = Repo()
    sid = str(uuid4())
    observed = memory_observations([{'name': 'schedule.callback',
        'args': {'customer_phone': '0900000000', 'callback_at': '2026-11-06T09:00', 'note': 'Nhắc khách'},
        'result': {'callback_id': 'CB1', 'callback_at': '2026-11-06T09:00', 'moved_from': None}}])
    add_turn(repo, sid, 'C1', 'Mai 9 giờ gọi lại nhé.', calls=observed)
    result = asyncio.run(read(repo, 'C1', str(uuid4()), projector=Projection()))
    action = result['episodes'][0]['actions_completed'][0]
    assert action['action'] == 'schedule.callback'
    assert action['callback_id'] == 'CB1'
    assert action['callback_at'] == '2026-11-06T09:00'
    assert 'customer_phone' not in str(observed)
