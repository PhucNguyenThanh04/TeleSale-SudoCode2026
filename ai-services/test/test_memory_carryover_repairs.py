"""Facts must survive enrichment completion without resurrecting deleted values."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.mcp_servers.mcp_memory.services.memory import read
from test_operational_memory import Repo, Projection, add_turn

RUN = Path(__file__).resolve().parents[1] / 'eval_harness/results/smoke-repairs-v2/20261112T071219Z-90613d42'


@pytest.mark.parametrize('status', ['pending', 'completed'])
def test_committed_customer_fact_survives_missing_projection_after_enrichment(status):
    repo = Repo()
    prior, current = str(uuid4()), str(uuid4())
    tid = add_turn(repo, prior, 'C1', 'Nhà anh có em bé nhỏ, phòng ngủ 25m2, ngân sách 3 triệu.')
    repo.sessions[prior]['turns'][0].update(memory_status=status, job_id=1)
    result = asyncio.run(read(repo, 'C1', current, projector=Projection()))
    assert result['profile']['has_children']['value'] is True
    assert result['profile']['has_children']['source'] == f'langmem:{prior}:{tid}'
    assert result['profile']['budget_vnd']['value'] == 3000000


def test_new_customer_correction_overrides_completed_fact_without_waiting_for_worker():
    repo = Repo()
    prior, current = str(uuid4()), str(uuid4())
    add_turn(repo, prior, 'C1', 'Nhà anh có em bé nhỏ, ngân sách 3 triệu.')
    repo.sessions[prior]['turns'][0].update(memory_status='completed', job_id=1)
    tid = add_turn(repo, current, 'C1', 'Nhà tôi không có con nhỏ, ngân sách tối đa 5,5 triệu.')
    repo.sessions[current]['turns'][0].update(memory_status='completed', job_id=3)
    result = asyncio.run(read(repo, 'C1', current, projector=Projection()))
    assert result['profile']['has_children']['value'] is False
    assert result['profile']['has_children']['source_turn_id'] == tid
    assert result['profile']['budget_vnd']['value'] == 5500000


def test_deleted_fact_barrier_prevents_completed_evidence_resurrection():
    repo = Repo()
    prior, current = str(uuid4()), str(uuid4())
    add_turn(repo, prior, 'C1', 'Nhà anh có em bé nhỏ.')
    repo.sessions[prior]['turns'][0].update(memory_status='completed', job_id=1)
    class Deleted(Projection):
        async def list_fact_versions(self, customer):
            return [{'schema_version': 1, 'scope_type': 'global', 'scope_id': '',
                     'key': 'has_children', 'revision': 2, 'deleted': True}]
    result = asyncio.run(read(repo, 'C1', current, projector=Deleted()))
    assert 'has_children' not in result['profile']


@pytest.mark.parametrize('other_customer,include_prior', [('C2', True), ('C1', False)])
def test_completed_facts_do_not_leak_to_another_customer_or_baseline(other_customer, include_prior):
    repo = Repo()
    prior = str(uuid4())
    add_turn(repo, prior, 'C1', 'Nhà anh có em bé nhỏ, ngân sách 3 triệu.')
    repo.sessions[prior]['turns'][0].update(memory_status='completed', job_id=1)
    result = asyncio.run(read(repo, other_customer, str(uuid4()),
                             include_prior=include_prior, projector=Projection()))
    assert result['profile'] == {}


def test_valid_source_uuids_survive_context_masking_but_pii_source_does_not():
    from app.agent.harness.context import _split_facts, _mask_context
    prior = '12345678-1234-4234-8234-123456789012'
    tid = '87654321-4321-4432-8432-987654321098'
    source = f'langmem:{prior}:{tid}'
    fact = {'value': 5500000, 'source_kind': 'customer', 'source': source,
            'session_id': prior, 'source_turn_id': tid}
    customer, _ = _split_facts({'budget_vnd': fact})
    assert customer['budget_vnd']['source'] == source
    masked = _mask_context(customer, ('customer_facts',))
    assert masked['budget_vnd']['source'] == source
    customer, _ = _split_facts({'budget_vnd': {**fact, 'source': 'langmem:0912345678:private'}})
    assert 'source' not in customer['budget_vnd']


def test_completed_scoped_projection_is_not_recreated_as_global_room_area():
    repo = Repo()
    prior, current = str(uuid4()), str(uuid4())
    first = add_turn(repo, prior, 'C1', 'Phòng ngủ rộng 25m2.')
    second = add_turn(repo, prior, 'C1', 'Phòng khách rộng 40m2.')
    for index, row in enumerate(repo.sessions[prior]['turns'], 1):
        row.update(memory_status='completed', job_id=index)
    class Scoped(Projection):
        async def list_fact_versions(self, customer):
            return [{'schema_version': 1, 'scope_type': 'room', 'scope_id': room,
                     'key': 'room_area_m2', 'value': area, 'revision': rev,
                     'source_kind': 'customer', 'session_id': prior,
                     'source_turn_id': tid, 'source': f'langmem:{prior}:{tid}'}
                    for room, area, rev, tid in [('bedroom', 25, 1, first), ('living_room', 40, 2, second)]]
    result = asyncio.run(read(repo, 'C1', current, projector=Scoped()))
    assert 'room_area_m2' not in result['profile']
    assert result['scoped_facts']['room']['bedroom']['room_area_m2']['value'] == 25
    assert result['scoped_facts']['room']['living_room']['room_area_m2']['value'] == 40


def test_three_sessions_carry_corrected_customer_facts_through_brief_and_prompt():
    from datetime import datetime, timezone
    from app.agent.harness.context import load_context, prompt_context
    from test_commerce_evidence import state
    repo = Repo()
    prior, returning, later = str(uuid4()), str(uuid4()), str(uuid4())
    add_turn(repo, prior, 'C1', 'Nhà tôi có con nhỏ, phòng 25m2, ngân sách 3 triệu.')
    repo.sessions[prior]['turns'][0].update(memory_status='completed', job_id=1)
    class Memory:
        include_prior = True
        max_episodes = 5
        async def read_context(self, sid, customer):
            return await read(repo, customer, sid, projector=Projection())
    class NoCommerce:
        async def invoke(self, *args):
            raise AssertionError('Customer facts alone must not fabricate a product to refresh.')
    async def context(sid):
        from uuid import UUID
        s = state('Tư vấn tiếp theo nhu cầu đã trao đổi hôm trước nhé.')
        s['request'] = s['request'].model_copy(update={'session_id': UUID(sid), 'channel': 'zalo_oa'})
        s['customer_id'] = 'C1'
        s.update(await load_context(s, Memory(), NoCommerce(), lambda: datetime.now(timezone.utc)))
        return s, prompt_context(s, 6)
    async def run():
        s, ctx = await context(returning)
        assert ctx['customer_facts']['budget_vnd']['value'] == 3000000
        assert ctx['customer_facts']['has_children']['value'] is True
        assert {'budget_vnd', 'room_area_m2', 'has_children'} <= set(s['call_brief']['must_not_ask'])
        tid = add_turn(repo, returning, 'C1', 'Ngân sách tối đa 5,5 triệu. Nhà tôi không có con nhỏ.')
        repo.sessions[returning]['turns'][0].update(memory_status='completed', job_id=2)
        s, ctx = await context(later)
        assert ctx['customer_facts']['budget_vnd']['value'] == 5500000
        assert ctx['customer_facts']['has_children']['value'] is False
        assert ctx['customer_facts']['has_children']['source'] == f'langmem:{returning}:{tid}'
        assert ctx['customer_facts']['room_area_m2']['value'] == 25
        assert {'budget_vnd', 'room_area_m2', 'has_children'} <= set(s['call_brief']['must_not_ask'])
    asyncio.run(run())


def test_latest_t06_remembers_corrected_variant_without_reasking_and_keeps_other_product_separate():
    from datetime import date
    from uuid import UUID
    from app.agent.harness.policy import resolve_product_selection
    from app.agent.harness.context import prompt_context
    from app.mcp_servers.mcp_shared.memory_observations import memory_observations
    from test_commerce_evidence import state
    repo = Repo()
    rows = list(map(json.loads, (RUN / 'full.diagnostics_full.jsonl').read_text().splitlines()))
    prior, other, current = str(uuid4()), str(uuid4()), str(uuid4())
    for sid, scenario in [(prior, 'SC-T06'), (other, 'SC-T17')]:
        for row in [r for r in rows if r['scenario_id'] == scenario and r['call'] == 'call_1']:
            add_turn(repo, sid, 'C1', row['user_text'], row['agent_text'], memory_observations(row['tool_calls']))
        for index, turn in enumerate(repo.sessions[sid]['turns'], 1):
            turn.update(memory_status='completed', job_id=index + (10 if sid == other else 0))
    loaded = asyncio.run(read(repo, 'C1', current, projector=Projection()))
    facts = loaded['scoped_facts']['product']
    assert facts['SKU-SN-TRK']['size']['value'] == 41
    assert facts['SKU-SN-TRK']['color']['value'] == 'xam'
    assert facts['SKU-SN-RUN1']['color']['value'] == 'den'
    query = next(r['user_text'] for r in rows if (r['scenario_id'], r['call'], r['turn']) == ('SC-T06', 'call_2', 1))
    s = state(query)
    s.update(loaded, customer_id='C1')
    s['request'] = s['request'].model_copy(update={'session_id': UUID(current), 'on': date(2026, 10, 21)})
    s['tool_calls'] = [call for sid in (prior, other) for turn in repo.sessions[sid]['turns']
                       for call in turn['tool_observations'] if call['name'] == 'catalog.search']
    selected = resolve_product_selection(s, {'sku': 'SKU-SN-TRK'})
    assert selected.status == 'resolved' and selected.sku == 'SKU-SN-TRK-41-XAM'
    s['safe_text'] = 'Kiểm tra bản size 42 cùng màu giúp anh, chưa đổi đơn nhé.'
    selected = resolve_product_selection(s, {'sku': 'SKU-SN-TRK'})
    assert selected.status == 'resolved' and selected.sku == 'SKU-SN-TRK-42-XAM'
    context = prompt_context(s, 6)
    products = {p['sku']: p for p in context['sales_history']['products']}
    assert products['SKU-SN-TRK']['color']['value'] == 'xam'
    assert products['SKU-SN-RUN1']['color']['value'] == 'den'


def test_latest_t13_prior_child_fact_changes_recommendation_without_repeating_it():
    from datetime import date
    from uuid import UUID
    from app.agent.implementations.business_agent import BusinessTools
    from app.mcp_servers.mcp_shared.consultation_shortlist import build_shortlist, consultation_scope
    from app.mcp_servers.mcp_shared.memory_observations import memory_observations
    from test_commerce_evidence import state
    from test_k0_harness_replay import OfflineCommerce
    rows = list(map(json.loads, (RUN / 'full.diagnostics_full.jsonl').read_text().splitlines()))
    initial = [r for r in rows if r['scenario_id'] == 'SC-T13' and r['call'] == 'call_1']
    query = next(r['user_text'] for r in rows if (r['scenario_id'], r['call'], r['turn']) == ('SC-T13', 'call_2', 1))
    async def run():
        choices = []
        for child_present in (True, False):
            repo = Repo()
            prior, current = str(uuid4()), str(uuid4())
            for row in initial:
                # Counterfactual changes only the stated child fact, not the new
                # request, room, budget, catalog or ranking implementation.
                speech = row['user_text'] if child_present or row['turn'] != 2 else 'Nhà anh không có con nhỏ.'
                add_turn(repo, prior, 'C1', speech, row['agent_text'], memory_observations(row['tool_calls']))
            for index, turn in enumerate(repo.sessions[prior]['turns'], 1):
                turn.update(memory_status='completed', job_id=index)
            s = state(query)
            s.update(await read(repo, 'C1', current, projector=Projection()), customer_id='C1')
            s['request'] = s['request'].model_copy(update={'session_id': UUID(current), 'on': date(2026, 10, 22)})
            gateway = OfflineCommerce()
            # The category is established by the prior product metadata, not by
            # an expected outcome in the scenario.
            await BusinessTools(gateway, s, 5, lambda: None).invoke('catalog.search', {'sku': 'SKU-AP-MINI'})
            await BusinessTools(gateway, s, 5, lambda: None).prepare_consultation()
            shortlist = build_shortlist(s, scope=consultation_scope(s), quoted_only=True)
            assert shortlist.items
            choices.append(shortlist.items[0]['sku'])
            assert not any(name == 'order.create' for name, _ in gateway.calls)
            assert s['profile']['has_children']['value'] is child_present
        assert choices[0] == 'SKU-AP-Y'
        assert choices[1] != choices[0]
    asyncio.run(run())


def test_two_named_rooms_survive_completion_and_returning_question_selects_only_its_area():
    from app.mcp_servers.mcp_shared.consultation import requirements
    from test_commerce_evidence import state
    repo = Repo()
    prior, current = str(uuid4()), str(uuid4())
    add_turn(repo, prior, 'C1', 'Phòng ngủ 25m2.')
    add_turn(repo, prior, 'C1', 'Phòng khách 40m2.')
    for index, turn in enumerate(repo.sessions[prior]['turns'], 1):
        turn.update(memory_status='completed', job_id=index)
    loaded = asyncio.run(read(repo, 'C1', current, projector=Projection()))
    assert 'room_area_m2' not in loaded['profile']
    assert loaded['scoped_facts']['room']['bedroom']['room_area_m2']['value'] == 25
    assert loaded['scoped_facts']['room']['living_room']['room_area_m2']['value'] == 40
    s = state('Tìm lại mẫu phù hợp cho phòng ngủ hôm trước nhé.')
    s.update(loaded, customer_id='C1')
    s['history'] = [{'customer': 'Phòng khách 40m2.', 'agent': 'Dạ.'}]
    assert requirements(s)['room_area_m2'] == 25
    s['safe_text'] = 'Phòng khách hôm trước thì mẫu nào phù hợp?'
    assert requirements(s)['room_area_m2'] == 40


def test_legacy_room_alias_deletion_cannot_be_revived_under_a_new_canonical_scope():
    repo = Repo()
    prior = str(uuid4())
    add_turn(repo, prior, 'C1', 'Phòng ngủ 25m2.')
    repo.sessions[prior]['turns'][0].update(memory_status='completed', job_id=1)
    class DeletedRoom(Projection):
        async def list_fact_versions(self, customer):
            return [{'schema_version': 1, 'scope_type': 'room', 'scope_id': 'phong_ngu',
                     'key': 'room_area_m2', 'revision': 2, 'deleted': True}]
    loaded = asyncio.run(read(repo, 'C1', str(uuid4()), projector=DeletedRoom()))
    assert 'room_area_m2' not in loaded['profile']
    assert not loaded['scoped_facts']['room']
