"""Data-driven tool checks against unmodified BTC data and November oracle."""
import asyncio
from datetime import date, timedelta
from itertools import combinations_with_replacement

from app.mcp_servers.mcp_shared import commerce_rules
from app.mcp_servers.mcp_catalog.services import catalog
from app.mcp_servers.mcp_catalog.repos.postgres import CatalogRepo
from test_november_pricing import reference, OrderRepo


def test_all_source_crm_identifiers_match_official_lookup(reference):
    class Repo:
        async def rows(self, session, table):
            assert table == 'customers'
            return reference.CRM
        async def runtime_orders(self, session, customer_id):
            return []
    async def run():
        repo = Repo()
        for customer in reference.CRM:
            for key in ('phone', 'zalo_id', 'fb_id'):
                if customer.get(key):
                    args = {key: customer[key]}
                    assert await catalog.get_customer(repo, None, args) == reference.crm_get_customer(**args)
        assert await catalog.get_customer(repo, None, {'phone': '0999999999'}) == {'found': False}
    asyncio.run(run())


def test_all_mcp_tool_surfaces_and_model_visibility():
    from fastmcp import Client
    from app.agent.implementations.tool_names import MODEL_TOOL_NAMES
    from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
    from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
    from app.mcp_servers.mcp_memory.tools.handlers import create_server as memory_server
    from app.mcp_servers.mcp_knowledge.tools.handlers import create_server as knowledge_server
    class KnowledgeService:
        ready = True
        async def close(self):
            pass
    groups = [
        (catalog_server(object()), {'crm.get_customer', 'catalog.search', 'inventory.check',
                                  'pricing.get_quote', 'pricing.quote_order', 'eval.database_identity'}),
        (order_server(object()), {'order.create', 'order.status', 'order.update',
                                'schedule.callback', 'handoff.transfer', 'eval.database_identity'}),
        (memory_server(object()), {'memory.read', 'memory.write', 'memory.turn_status', 'eval.database_identity'}),
        (knowledge_server(KnowledgeService(), context_secret='offline-test'),
         {'policy.search', 'eval.knowledge_release', 'eval.database_identity'}),
    ]
    async def run():
        exposed = set()
        for server, expected in groups:
            async with Client(server) as client:
                definitions = await client.list_tools()
                assert {tool.name for tool in definitions} == expected
                exposed.update(expected)
                for tool in definitions:
                    schema = tool.input_schema
                    assert set(schema.get('required', [])) <= set(schema.get('properties', {}))
        assert set(MODEL_TOOL_NAMES) == exposed - {'crm.get_customer', 'memory.read',
            'memory.write', 'memory.turn_status', 'eval.database_identity', 'eval.knowledge_release'}
    asyncio.run(run())


def test_all_labeled_rag_references_have_safe_source_coverage():
    import json
    from btc_data import btc_data_dir
    from app.knowledge.policy.source import parse_policy_sources, default_metadata, HEADING
    root = btc_data_dir()
    questions = json.loads((root / 'rag/qa_labeled.json').read_text())['questions']
    raw = {heading[0] for path in (root / 'policy').glob('*.md')
           for heading in HEADING.findall(path.read_text())}
    served = {chunk.chunk_id for chunk in parse_policy_sources(root / 'policy', default_metadata())}
    excluded = {'NB-04', *{f'NQ-0{i}' for i in range(1, 6)}}
    assert len(questions) == 60
    for question in questions:
        references = set(question['relevant_chunk_ids'])
        assert references <= raw, question['qid']
        assert references <= served | excluded, question['qid']
        if question['type'] not in {'restricted', 'unanswerable'}:
            assert references <= served, question['qid']


def boundary_dates(reference):
    dates = {reference.REF}
    for promo in reference.PROMOS:
        for key in ('start', 'end'):
            day = date.fromisoformat(promo[key])
            dates.update((day + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1))
    for event in reference.INV:
        dates.update((event['date'], (date.fromisoformat(event['date']) - timedelta(days=1)).isoformat()))
    return sorted(dates)


def test_every_source_sku_inventory_and_price_at_data_boundaries(reference):
    skus = [p['sku'] for p in reference.PRODUCTS] + [v['variant_sku']
            for p in reference.PRODUCTS for v in p['variants']]
    owner = next(c for c in reference.CRM if any(o['sku']=='SKU-AP-X-2024' for o in c.get('orders', [])))
    for sku in skus:
        for on in boundary_dates(reference):
            assert commerce_rules._inventory(reference.PRODUCTS, reference.INV, sku, on) == reference.inventory_check(sku, on)
            for phone, address in [(None, None), (owner['phone'], 'Hồ Chí Minh')]:
                args = dict(sku=sku, on=on, customer_phone=phone, address=address)
                expected = reference.pricing_get_quote(**args)
                expected.pop('_internal_price_floor_vnd', None)  # Never serve internal costs.
                owned = {o['sku'] for o in owner['orders'] if o.get('status')=='delivered'} if phone else set()
                assert commerce_rules.quote(reference.PRODUCTS, reference.PROMOS, args, owned) == expected, args


def test_catalog_exact_skus_and_structured_filters_match_source(reference):
    skus = [p['sku'] for p in reference.PRODUCTS] + [v['variant_sku']
            for p in reference.PRODUCTS for v in p['variants']]
    filters = [{'sku': sku} for sku in skus]
    filters += [{'category': category, 'max_price_vnd': price,
                 'include_discontinued': discontinued}
                for category in {p['category'] for p in reference.PRODUCTS}
                for price in (1000000, 5500000, 10000000) for discontinued in (False, True)]
    for args in filters:
        assert commerce_rules._catalog(reference.PRODUCTS, args) == reference.catalog_search(**args), args


def test_callback_calendar_matches_official_tool_on_source_boundaries(reference):
    from app.mcp_servers.mcp_order.services.order import callback
    class Repo:
        def __init__(self): self.count = 0
        async def insert_callback(self, session, phone, moment, note):
            self.count += 1
            return self.count
    async def run():
        repo = Repo()
        for moment in ('2026-10-20T07:30', '2026-10-20T10:00', '2026-10-20T21:30',
                       '2026-10-25T08:00', '2026-10-25T09:00', '2026-10-25T18:00',
                       '2026-10-26T10:00', '2026-11-11T07:00', '2027-01-01T10:00',
                       '2026-10-20T10:00+07:00'):
            args = {'customer_phone': reference.CRM[0]['phone'], 'callback_at': moment}
            assert await callback(repo, None, args, args['customer_phone']) == reference.schedule_callback(**args)
    asyncio.run(run())


def test_basket_quotes_match_complete_november_result(reference):
    air = [p['sku'] for p in reference.PRODUCTS if p['category'].startswith('gia-dung/may-loc-khong-khi')
           and not p['attributes'].get('discontinued')]
    owner = next(c for c in reference.CRM if any(o['sku']=='SKU-AP-X-2024' for o in c.get('orders', [])))
    for a, b in combinations_with_replacement(air, 2):
        for on in ('2026-10-15', '2026-10-22', '2026-10-23', '2026-11-02'):
            for phone in (None, owner['phone']):
                args = dict(lines=[{'sku': a, 'qty': 1}, {'sku': b, 'qty': 1}], on=on, customer_phone=phone)
                owned = {o['sku'] for o in owner['orders'] if o.get('status')=='delivered'} if phone else set()
                assert commerce_rules.quote_order(reference.PRODUCTS, reference.PROMOS, args, owned) == reference.pricing_quote_order(**args), args


def test_catalog_identity_phone_fallback_matches_order_for_real_btc_customers(reference):
    class Result:
        def __init__(self, rows): self.rows = rows
        def __iter__(self): return iter(self.rows)
    class Row:
        def __init__(self, row): self._mapping = row
    class Session:
        async def execute(self, statement, params):
            sql = str(statement)
            field = next(key for key in ('phone', 'zalo_id', 'fb_id') if f'WHERE {key}=' in sql)
            return Result([Row({'customer_id': c['customer_id'], 'phone': c['phone']})
                           for c in reference.CRM if c.get(field) == params['identity']])
    async def run():
        repo = object.__new__(CatalogRepo)
        for customer in reference.CRM:
            for channel in ('hotline', 'zalo_oa', 'chat_fanpage'):
                actual = await repo.identity_matches(Session(), channel, customer['phone'])
                expected = [{'customer_id': c['customer_id'], 'phone': c['phone']}
                            for c in reference.CRM if c['phone']==customer['phone']]
                assert actual == expected, (customer['customer_id'], channel)
        assert await repo.identity_matches(Session(), 'zalo_oa', 'unknown-zalo') == []
    asyncio.run(run())


def test_runtime_order_lookup_keeps_btc_payment_and_promotions_without_exposing_address(reference):
    import json
    import sqlite3
    from types import SimpleNamespace
    from app.mcp_servers.mcp_order.repos.postgres import OrderRepo as PostgresOrderRepo
    phone = reference.CRM[0]['phone']
    quote = reference.pricing_get_quote('SKU-XM-4P', on='2026-10-20')
    receipt = reference.order_create(phone, sku='SKU-XM-4P', price_vnd=quote['final_price_vnd'],
                                     payment='momo', on='2026-10-20')
    order = reference._ORDERS[receipt['order_id']]
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute("ATTACH DATABASE ':memory:' AS runtime")
    conn.execute('''CREATE TABLE runtime.tool_orders (
        order_id TEXT,customer_id TEXT,customer_phone TEXT,sku TEXT,qty INTEGER,
        price_vnd INTEGER,total_vnd INTEGER,lines TEXT,created_on TEXT,status TEXT,
        payment TEXT,promos TEXT,address TEXT)''')
    conn.execute('INSERT INTO runtime.tool_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (order['order_id'], 'C001', phone, order['sku'], order['qty'], order['price_vnd'],
         order['total_vnd'], json.dumps(order['lines']), order['created_on'], order['status'],
         order['payment'], json.dumps(order['promos']), 'private delivery address'))
    class Session:
        async def execute(self, sql, params):
            return [SimpleNamespace(_mapping=dict(row)) for row in conn.execute(str(sql), params)]
    async def run():
        for cls in (CatalogRepo, PostgresOrderRepo):
            repo = object.__new__(cls)
            args = (None,) if cls is PostgresOrderRepo else ()
            rows = await repo.runtime_orders(Session(), 'C001', *args)
            assert rows[0]['payment'] == order['payment']
            assert json.loads(rows[0]['promos']) == order['promos']
            assert 'address' not in rows[0]
            assert await repo.runtime_orders(Session(), 'C-FOREIGN', *args) == []
    try:
        asyncio.run(run())
    finally:
        conn.close()


def test_callback_reports_an_hour_only_move_instead_of_silently_changing_time():
    from app.mcp_servers.mcp_order.services.order import callback
    class Repo:
        async def insert_callback(self, session, phone, moment, note):
            self.moment = moment
            return 1
    async def run():
        repo = Repo()
        original = '2026-10-20T07:30'
        result = await callback(repo, None, {'customer_phone': '0984726714',
            'callback_at': original}, '0984726714')
        assert result['callback_at'] == '2026-10-20T08:00'
        assert result['moved_from'] == original
        assert repo.moment.utcoffset() == timedelta(hours=7)
    asyncio.run(run())


def test_concurrent_exchanges_do_not_both_receive_the_first_exchange_fee(reference):
    from contextlib import asynccontextmanager
    from app.mcp_servers.mcp_order.services.order import invoke
    phone = reference.CRM[0]['phone']
    receipt = reference.order_create(phone, sku='SKU-JK-WND-M-NAVY', qty=1,
        price_vnd=690000, payment='COD', on='2026-10-15')
    class Repo(OrderRepo):
        def __init__(self):
            super().__init__(reference)
            self.updates, self.held = [], set()
            self.lock = asyncio.Lock()
        @asynccontextmanager
        async def transaction(self):
            session = object()
            try:
                yield session
            finally:
                if session in self.held:
                    self.held.remove(session)
                    self.lock.release()
        async def lock_customer(self, session, phone):
            await self.lock.acquire()
            self.held.add(session)
        async def order_owned(self, session, order_id, customer_id):
            return order_id == receipt['order_id'] and customer_id == 'C001'
        async def runtime_orders(self, session, customer_id, order_id):
            return [reference._ORDERS[receipt['order_id']]]
        async def exchange_count(self, session, order_id):
            count = len(self.updates)
            await asyncio.sleep(0)  # Both requests can otherwise read zero before either insert.
            return count
        async def insert_update(self, session, order_id, action, result):
            self.updates.append(result)
    async def run():
        repo = Repo()
        args = dict(order_id=receipt['order_id'], action='exchange_size',
                    new_variant_sku='SKU-JK-WND-L-NAVY', on='2026-10-20')
        results = await asyncio.gather(invoke(repo, 'order.update', args), invoke(repo, 'order.update', args))
        assert sorted(r['fee_vnd'] for r in results) == [0, 60000]
    asyncio.run(run())
