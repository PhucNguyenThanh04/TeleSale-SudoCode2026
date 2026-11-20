import asyncio
import copy
import csv
import json
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dataloader_offline.postgres import import_release
from dataloader_offline.source import PolicyChunk


def synthetic_release():
    variant = dict(variant_sku='V1', size='L', color='blue', price_delta_vnd=10, stock=2, extra='variant')
    product = dict(sku='P1', name='Synthetic product', category='test', brand='Test',
        list_price_vnd=100, stock=3, attributes={'warranty_months':12}, variants=[variant], extra='product')
    customer = dict(customer_id='C1', name='Synthetic buyer', phone='0000000000',
        orders=[dict(order_id='O1', sku='P1', date='2026-10-01', status='delivered', extra='order')],
        sessions=[dict(session_id='S1', date='2026-10-01', channel='phone', outcome='pending', extra='session')], extra='customer')
    return dict(products={'products':[product]}, promotions={'promotions':[
        dict(promo_code='TEST', name='Synthetic', type='percent', start='2026-10-01',
             end='2026-10-31', applies_to=['P1'], conditions={'min_qty':2}, extra='promotion')]},
        inventory={'events':[dict(sku='P1', date='2026-10-01', qty=5, note='synthetic', extra='event')]},
        crm={'customers':[customer, dict(customer_id='C2', name='Synthetic buyer two', phone=customer['phone'])]},
        chunks=[PolicyChunk('XX-01','source.md','Rule','Safe content','public',None,None,'call_date','hash')])


class StatefulWriter:
    def __init__(self, fail_table=None):
        self.rows = {}
        self.fail_table = fail_table

    @asynccontextmanager
    async def transaction(self):
        old = copy.deepcopy(self.rows)
        try:
            yield
        except Exception:
            self.rows = old
            raise

    async def execute(self, sql, *args):
        m = re.search(r'INSERT INTO btc_source\.(\w+)', sql)
        if not m:
            return
        table = m[1]
        if table == self.fail_table:
            raise ConnectionError('synthetic failure')
        key = args[:2] if table=='inventory_events' else args[0]
        self.rows.setdefault(table,{})[key] = args

    async def close(self):
        pass


def test_writer_preserves_json_and_is_idempotent_without_pruning(monkeypatch):
    writer = StatefulWriter()
    async def connect(*args, **kwargs):
        return writer
    monkeypatch.setattr('asyncpg.connect', connect)
    source = synthetic_release()
    async def run():
        await import_release('postgresql://synthetic', source)
        first = copy.deepcopy(writer.rows)
        await import_release('postgresql://synthetic', source)
        assert writer.rows == first
        records = {'products':source['products']['products'], 'variants':source['products']['products'][0]['variants'],
            'promotions':source['promotions']['promotions'], 'inventory_events':source['inventory']['events'],
            'customers':source['crm']['customers'], 'crm_orders':source['crm']['customers'][0]['orders'],
            'crm_sessions':source['crm']['customers'][0]['sessions']}
        for table, expected in records.items():
            args = list(writer.rows[table].values())
            assert len(args) == len(expected)
            for row in expected:
                assert any(json.dumps(row,ensure_ascii=False) in values for values in args)
        source['products']['products'][0]['extra'] = 'updated'
        source['crm']['customers'] = source['crm']['customers'][:1]
        await import_release('postgresql://synthetic', source)
        assert 'C2' in writer.rows['customers']
        assert writer.rows['products']['P1'] != first['products']['P1']
    asyncio.run(run())


def test_writer_failure_exits_the_transaction_without_success(monkeypatch):
    writer = StatefulWriter(fail_table='crm_sessions')
    async def connect(*args, **kwargs):
        return writer
    monkeypatch.setattr('asyncpg.connect', connect)
    with pytest.raises(ConnectionError):
        asyncio.run(import_release('postgresql://synthetic', synthetic_release()))
    assert writer.rows == {}


def test_products_csv_is_a_projection_of_products_json():
    from btc_data import btc_data_dir
    root=btc_data_dir()/'catalog'
    products={p['sku']:p for p in json.loads((root/'products.json').read_text())['products']}
    with (root/'products.csv').open() as f:rows=list(csv.DictReader(f))
    assert len(rows)==len(products) and {r['sku'] for r in rows}==set(products)
    for row in rows:
        product=products[row['sku']]
        assert all(row[k]==str(product[k]) for k in ['name','category','brand','list_price_vnd','stock'])
        assert int(row['n_variants'])==len(product.get('variants',[]))
        assert json.loads(row['attributes'])==product['attributes']


@pytest.mark.parametrize('group,id_key',[('orders','order_id'),('sessions','session_id')])
def test_duplicate_nested_crm_keys_cannot_overwrite_another_customer(tmp_path,group,id_key):
    from dataloader_offline.source import read_release
    source=synthetic_release()
    source['crm']['customers'][1][group]=copy.deepcopy(source['crm']['customers'][0][group])
    root=tmp_path/'btc';(root/'catalog').mkdir(parents=True);(root/'policy').mkdir()
    for key,name in [('products','products.json'),('promotions','promotions.json'),('inventory','inventory_timeline.json'),('crm','crm_seed.json')]:
        if key!='crm':source[key]['reference_date']='2026-10-15'
        (root/'catalog'/name).write_text(json.dumps(source[key]))
    (root/'policy/source.md').write_text('## [XX-01] Rule\nSynthetic')
    meta=tmp_path/'meta.json';meta.write_text(json.dumps({'documents':{'source.md':dict(
        access='public',version='v1',date_basis='on',effective_from=None,effective_until=None)}}))
    with pytest.raises(ValueError,match='Duplicate CRM'):
        read_release(root,meta)
