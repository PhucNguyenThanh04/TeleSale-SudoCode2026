import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import pytest

from eval_harness.seed_memory import SeedMemoryLoader


class Repo:
    def __init__(self):
        self.turns = []
        self.operations = {}
        self.erased = False

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def lock_key(self, *args):
        pass

    async def is_erasure_blocked(self, *args):
        return self.erased

    async def claim_operation(self, conn, key, digest):
        if key in self.operations:
            previous, result = self.operations[key]
            return result if previous == digest else {'error': 'operation_key_conflict'}
        self.operations[key] = (digest, None)

    async def finish_operation(self, conn, key, value):
        self.operations[key] = (self.operations[key][0], value)

    async def insert_turn(self, conn, sid, number, customer, channel, on, text, agent, tid, *args, **kwargs):
        self.turns.append({'session_id': sid, 'customer_id': customer, 'number': number,
            'on': on.isoformat(), 'text': text, 'source_turn_id': tid, **kwargs})


class Projection:
    def __init__(self):
        self.facts = {}
        self.episodes = {}

    async def list_facts(self, customer):
        return [deepcopy(f) for (cid, _), f in self.facts.items() if cid == customer]

    async def put_facts(self, customer, sid, tid, on, facts, revision=0):
        from app.mcp_servers.mcp_memory.repos.langmem_projection import _safe
        for fact in facts:
            self.facts[customer, fact['key']] = _safe({**fact, 'session_id': sid,
                'source_turn_id': tid, 'on': on, 'revision': revision})

    async def put_episode(self, customer, sid, canonical, revision=0):
        self.episodes[customer, sid] = canonical


def session(sid, on, value, as_of=None):
    return {'session_id': sid, 'date': on, 'channel': 'phone', 'summary': 'Khách đã cung cấp ngân sách.',
            'outcome': 'hen_goi_lai', 'facts': [{'field': 'budget_vnd', 'value': value, 'as_of': as_of or on}]}


def test_seed_uses_newest_fact_date_and_persists_real_sessions_idempotently():
    async def run():
        repo, projection = Repo(), Projection()
        extract = AsyncMock()
        loader = SeedMemoryLoader(repo, projection, extract)
        history = [session('B', '2026-09-18', 3000000, '2026-08-10'), session('A', '2026-09-17', 5000000)]
        result = await loader('S', 'C1', history)
        assert projection.facts['C1', 'budget_vnd']['value'] == 5000000
        assert projection.facts['C1', 'budget_vnd']['on'] == '2026-09-17'
        assert len(repo.turns) == len(projection.episodes) == 2
        assert all('facts' not in s and s['channel'] == 'hotline' for s in result)
        assert await loader('S', 'C1', history) == result
        assert len(repo.turns) == 2
        extract.assert_not_awaited()
        await loader('S', 'C2', history)
        assert {t['customer_id'] for t in repo.turns} == {'C1', 'C2'}
        assert len({t['session_id'] for t in repo.turns}) == 4
    asyncio.run(run())


def test_summary_only_runs_existing_extractor_and_admits_evidence():
    async def run():
        from app.schemas.langmem import ProfileFactCandidate
        async def extract(turns, existing):
            payload = json.loads(turns[0]['content'])
            assert '012345678901' not in turns[0]['content']
            return [ProfileFactCandidate(key='budget_vnd', value=5000000, source_kind='customer',
                source_turn_id=payload['source_turn_id'], observed_on=payload['on'],
                evidence_quote='Ngân sách của tôi là 5 triệu đồng.')], None
        repo, projection = Repo(), Projection()
        extract = AsyncMock(side_effect=extract)
        loader = SeedMemoryLoader(repo, projection, extract)
        history = [{'session_id': 'old', 'date': '2026-09-17', 'channel': 'phone',
            'summary': 'Ngân sách của tôi là 5 triệu đồng. CCCD 012345678901.'}]
        await loader('S', 'C1', history)
        await loader('S', 'C1', history)
        assert extract.await_count == 1
        assert projection.facts['C1', 'budget_vnd']['value'] == 5000000
        assert '012345678901' not in str(repo.turns) + str(projection.episodes)
    asyncio.run(run())


def test_seed_cannot_override_live_memory_or_resurrect_erased_customer():
    async def run():
        repo, projection = Repo(), Projection()
        projection.facts['C1', 'budget_vnd'] = {'key': 'budget_vnd', 'value': 6000000, 'on': '2026-09-18', 'revision': 10}
        loader = SeedMemoryLoader(repo, projection, AsyncMock())
        await loader('S', 'C1', [session('A', '2026-09-19', 5000000)])
        assert projection.facts['C1', 'budget_vnd']['value'] == 6000000
        repo.erased = True
        with pytest.raises(RuntimeError, match='erased'):
            await loader('S2', 'C1', [session('A', '2026-09-19', 5000000)])
        assert len(repo.turns) == 1
    asyncio.run(run())


def test_seed_conflicts_and_private_delivery_keep_date_and_identity():
    async def run():
        repo, projection = Repo(), Projection()
        loader = SeedMemoryLoader(repo, projection, AsyncMock())
        with pytest.raises(ValueError, match='fact_conflict'):
            await loader('S', 'C1', [session('A', '2026-09-17', 1), session('B', '2026-09-18', 2, '2026-09-17')])
        assert repo.turns == []
        history = [session('A', '2026-09-17', 5000000)]
        history[0]['facts'] += [{'field': 'address', 'value': '12 đường X', 'as_of': '2026-02-01'},
                                {'field': 'interest_sku', 'value': 'SKU-AP-X', 'as_of': '2026-09-17'}]
        await loader('S', 'C1', history)
        assert repo.turns[0]['private_delivery']['address'] == '12 đường X'
        assert repo.turns[0]['private_delivery']['source_on'] == repo.turns[0]['on'] == '2026-02-01'
        assert repo.turns[-1]['on'] == '2026-09-17'
        assert projection.facts['C1', 'product_advised']['value'] == 'SKU-AP-X'
        assert '12 đường X' not in str(projection.facts)
    asyncio.run(run())


def test_seed_is_materialized_before_first_customer_turn_in_each_configuration():
    from datetime import date
    from types import SimpleNamespace
    from eval_harness.benchmark_runner import run_scenario_stream
    from eval_harness.seed_history import SeedHistoryGateway
    from eval_harness.test_support import VoiceLifecycleStub
    async def run():
        for baseline in (False, True):
            materialize = AsyncMock(return_value=[{'session_id': 'persisted', 'date': '2026-09-17',
                'channel': 'hotline', 'summary': 'Đã hỏi ngân sách.'}])
            inner = SimpleNamespace(invoke=AsyncMock(return_value={'found': True, 'customer_id': 'C1', 'sessions': []}))
            class Runtime(VoiceLifecycleStub):
                tools = SeedHistoryGateway(inner, materialize=materialize)
                memory = SimpleNamespace(include_prior=not baseline)
                async def run(self, request):
                    assert materialize.await_count == 1
                    assert self.memory.include_prior is not baseline
                    return SimpleNamespace(agent_text='Dạ.', call_brief=None)
                def state_for(self, request):
                    return {}
            scenario = {'customer_phone': '0900000000', 'calls': {'call_1': {
                'customer_turns': ['Chào'], 'call_date': '2026-10-15',
                'seed_history': [session('A', '2026-09-17', 5000000)]}}}
            trace = await run_scenario_stream(Runtime(), {'S': scenario}, is_baseline=baseline)
            assert len(trace['S', 'call_1']) == 1
    asyncio.run(run())


def test_summary_imports_literal_historical_quote_without_inventing_order_ownership():
    async def run():
        from app.schemas.langmem import ProfileFactCandidate
        summary = 'Khách hỏi SKU-AP-X, giá 4.890.000đ; chưa tạo đơn.'
        async def extract(turns, existing):
            payload = json.loads(turns[0]['content'])
            return [ProfileFactCandidate(key=key, value=value, source_kind='tool', source_tool='pricing.get_quote',
                source_turn_id=payload['source_turn_id'], observed_on=payload['on'], evidence_quote=summary)
                for key, value in [('product_advised', 'SKU-AP-X'), ('price_quoted_vnd', 4890000), ('order_id', 'ODFAKE')]], None
        repo, projection = Repo(), Projection()
        loader = SeedMemoryLoader(repo, projection, extract)
        await loader('S', 'C1', [{'session_id': 'A', 'channel': 'phone', 'date': '2026-09-17', 'summary': summary}])
        assert projection.facts['C1', 'price_quoted_vnd']['value'] == 4890000
        assert projection.facts['C1', 'product_advised']['value'] == 'SKU-AP-X'
        assert ('C1', 'order_id') not in projection.facts
    asyncio.run(run())


def test_explicit_contact_is_masked_even_without_address_markers_in_summary():
    async def run():
        repo, projection = Repo(), Projection()
        address = '12 Nguyễn Trãi, Hà Nội'
        history = [{'session_id': 'A', 'date': '2026-09-17', 'channel': 'phone',
                    'summary': 'Khách xác nhận nơi nhận ' + address,
                    'facts': [{'field': 'address', 'value': address}]}]
        result = await SeedMemoryLoader(repo, projection, AsyncMock())('S', 'C1', history)
        assert address not in result[0]['summary'] + str(projection.episodes)
        assert repo.turns[0]['private_delivery']['address'] == address
        assert address not in repo.turns[0]['private_delivery']['source_customer_text']
        assert history[0]['summary'].endswith(address)
    asyncio.run(run())


def test_seed_loader_factory_uses_declared_config_without_connecting_to_services():
    from app.configs import Settings
    from eval_harness.seed_memory import build_seed_loader
    from eval_harness.test_official_pipeline import BTC
    settings = Settings(_env_file=None, llm_api_key='offline', llm_model='offline-model',
                        langmem_model='offline-memory-model', database_url='postgresql://offline:offline@127.0.0.1/offline')
    loader = build_seed_loader(settings, BTC)
    assert len(loader.catalog) == 40
    assert loader.repo.pool is None
    assert loader.projector.fact_namespace('C1') != loader.projector.fact_namespace('C2')
