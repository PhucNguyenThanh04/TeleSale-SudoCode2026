import asyncio
from copy import deepcopy

import pytest

from app.mcp_servers.mcp_catalog.services import catalog
from test_catalog_evidence import evidence, product, rules


class Repo:
    def __init__(self):
        self.products = [product()]
        self.evidence = [evidence() | {'body': evidence()['body'].replace('Lock |', 'Lock | Output (dB) |').replace('---|---|---|---|', '---|---|---|---|---|').replace('| no |', '| no | 21–45 |')}]

    async def rows(self, session, table):
        return {'products': self.products, 'policy_chunks': self.evidence}[table]


@pytest.fixture
def repo(monkeypatch):
    from app.mcp_servers.mcp_shared import catalog_evidence
    monkeypatch.setattr(catalog_evidence, 'load_rules', rules)
    return Repo()


def details(repo, sku='LAB-DEVICE'):
    return asyncio.run(catalog.get_details(repo, None, {'sku': sku}))


def test_details_include_exact_row_properties_resolved_fields_and_source_hashes(repo):
    original = deepcopy(repo.products)
    repo.evidence[0]['body'] += '\n| DIFFERENT | 99 | 99 | yes | 90–99 |'
    result = details(repo)
    assert result['total'] == 1 and result['requested_sku'] == 'LAB-DEVICE'
    item = result['items'][0]
    assert item['attributes']['stages'] == 4 and item['attributes']['warranty_months'] == 12
    props = {p['name']: p for p in item['specifications']}
    assert props['Output (dB)']['value'] == '21–45'
    assert props['Warranty months']['value'] == 12
    assert props['Modules']['value'] == 4
    assert props['Lock']['value'] is False
    assert props['Output (dB)']['sources'][0]['source_hash'] == evidence()['source_hash']
    assert '90–99' not in str(result)
    assert repo.products == original


def test_variant_details_keep_parent_specs_and_exact_variant_context(repo):
    repo.products[0]['variants'] = [{'variant_sku': 'LAB-DEVICE-L', 'size': 'L', 'color': 'navy', 'price_delta_vnd': 12000}]
    result = details(repo, 'LAB-DEVICE-L')
    assert result['requested_sku'] == 'LAB-DEVICE-L'
    item = result['items'][0]
    assert item['sku'] == 'LAB-DEVICE' and item['selected_variant']['variant_sku'] == 'LAB-DEVICE-L'
    assert any(p['name'] == 'Output (dB)' for p in item['specifications'])


def test_unparseable_mapped_spec_uses_catalog_provenance_instead_of_claiming_technical_support(repo):
    repo.products[0]['attributes']['stages'] = 7
    repo.evidence[0]['body'] = repo.evidence[0]['body'].replace('| 4 |', '| seven |')
    prop = next(p for p in details(repo)['items'][0]['specifications'] if p['name'] == 'Modules')
    assert prop['value'] == 7 and prop['sources'][0]['source'] == 'catalog'


def test_detail_price_column_keeps_catalog_authority(repo, monkeypatch):
    from app.mcp_servers.mcp_shared import catalog_evidence
    config = rules()
    config['fields']['list_price_vnd'] = {'headers': ['Price'], 'type': 'integer', 'minimum': 0, 'authority': 'catalog'}
    monkeypatch.setattr(catalog_evidence, 'load_rules', lambda: config)
    repo.evidence = [evidence() | {'body': '| Item | Price |\n|---|---|\n| LAB-DEVICE | 999 |'}]
    prop = details(repo)['items'][0]['specifications'][0]
    assert prop['value'] == 131000 and prop['sources'][0]['source'] == 'catalog'


def test_details_cover_actual_public_tables_prose_and_size_bindings(monkeypatch):
    from app.mcp_servers.mcp_shared import catalog_evidence
    from dataloader_offline.source import read_release
    from btc_data import btc_data_dir
    loaded = read_release(btc_data_dir())
    source = Repo()
    source.products = loaded['products']['products']
    source.evidence = [dict(chunk_id=c.chunk_id, document_id=c.document_id, body=c.body,
        access_level=c.access_level, source_hash=c.content_hash) for c in loaded['chunks']]
    policy = catalog_evidence.load_rules()
    products = {p['sku'] for p in source.products}
    chunks = {r['chunk_id']: r for r in source.evidence}
    for binding in policy['section_bindings']:
        assert set(binding['skus']) <= products
        assert all(chunks[key]['access_level'] == 'public' and chunks[key]['document_id'] in policy['documents']
                   for key in binding['section_ids'])
    air = details(source, 'SKU-AP-Y')['items'][0]
    props = {p['name']: p['value'] for p in air['specifications']}
    assert props['CADR (m³/h)'] == '300' and props['Độ ồn min–max (dB)'] == '23–50'
    assert props['App'] == 'Có (AirPure Home)'
    shoe = details(source, 'SKU-SN-RUN2-43-DEN')['items'][0]
    assert {r['chunk_id'] for r in shoe['technical_evidence']} == {'SP-SN-01', 'SP-SN-02'}
    assert shoe['selected_variant']['size'] == 43
    assert 'stock' not in shoe['selected_variant']
    assert details(source, 'SKU-FAN-DC1')['items'][0]['technical_evidence'][0]['chunk_id'] == 'SP-FAN-01'
    assert details(source, 'SKU-MB-PUMP1')['items'][0]['technical_evidence'][0]['chunk_id'] == 'SP-MB-01'
    assert details(source, 'SKU-MB-BAG')['items'][0]['technical_data_status'] == 'not_available'
    old = details(source, 'SKU-AP-X-2024')['items'][0]
    assert old['specifications'] == [] and {r['chunk_id'] for r in old['technical_evidence']} == {'SP-AIR-03'}


def test_conflicting_unmapped_specs_do_not_choose_a_favorable_value(repo):
    repo.evidence.append(repo.evidence[0] | {'chunk_id': 'LAB-TWO', 'body': repo.evidence[0]['body'].replace('21–45', '32–60')})
    prop = next(p for p in details(repo)['items'][0]['specifications'] if p['name'] == 'Output (dB)')
    assert prop['status'] == 'unresolved' and prop['value'] is None
    assert {row['value'] for row in prop['observations']} == {'21–45', '32–60'}


@pytest.mark.parametrize('change', [{'access_level': 'restricted'}, {'document_id': 'unapproved.md'}, {'body': '| Item | Output |\n|---|---|\n| LAB-DEVICE | 12 | extra |'}])
def test_private_unapproved_and_malformed_tables_supply_no_specs(repo, change):
    repo.evidence = [repo.evidence[0] | change]
    item = details(repo)['items'][0]
    assert item['specifications'] == [] and item['technical_data_status'] == 'not_available'
    assert item['technical_evidence'] == []


def test_unknown_sku_fails_and_known_product_without_specs_remains_useful(repo):
    assert details(repo, 'UNKNOWN')['error'] == 'unknown_sku'
    repo.evidence = []
    item = details(repo)['items'][0]
    assert item['name'] == product()['name'] and item['technical_data_status'] == 'not_available'
    assert item['attributes']['warranty_months'] == 12


def test_reviewed_prose_and_size_bindings_preserve_context_and_do_not_guess_models(repo, monkeypatch):
    from app.mcp_servers.mcp_shared import catalog_evidence
    config = rules() | {'section_bindings': [{'skus': ['LAB-DEVICE'], 'section_ids': ['LAB-SIZE']} ]}
    monkeypatch.setattr(catalog_evidence, 'load_rules', lambda: config)
    repo.evidence = [evidence(chunk_id='LAB-SIZE') | {'body': '## Size guide\n| Size | Length |\n|---|---|\n| L | 28 |\nOther model uses a different battery.'},
                     evidence(chunk_id='PRIVATE') | {'access_level': 'restricted', 'body': 'Secret'}]
    item = details(repo)['items'][0]
    assert item['technical_data_status'] == 'available'
    assert item['technical_evidence'][0]['scope'] == 'section_context'
    assert 'Other model' in item['technical_evidence'][0]['content']
    assert item['technical_evidence'][0]['chunk_id'] == 'LAB-SIZE'
    repo.products.append(product('LAB-DEVICE-OLD'))
    old = details(repo, 'LAB-DEVICE-OLD')['items'][0]
    assert old['technical_data_status'] == 'not_available' and old['technical_evidence'] == []
