import asyncio
from copy import deepcopy

import pytest

from app.mcp_servers.mcp_catalog.schemas import SearchInput
from app.mcp_servers.mcp_shared.commerce_rules import _catalog


def product(sku='LAB-DEVICE', **attrs):
    return {'sku': sku, 'name': 'Studio controller', 'brand': 'Luma', 'category': 'devices',
        'list_price_vnd': 131000, 'stock': 9, 'variants': [], 'attributes': {
            'stages': 0, 'features': 'Zigbee coordinator, quiet fan', 'child_safe_lock': False,
            'warranty_months': 12, **attrs}}


def rules():
    return {'documents': ['lab-spec.md'], 'sku_headers': ['Item'], 'fields': {
        'stages': {'headers': ['Modules'], 'type': 'integer', 'minimum': 1, 'authority': 'technical_spec'},
        'warranty_months': {'headers': ['Warranty months'], 'type': 'integer', 'minimum': 0, 'authority': 'catalog'},
        'child_safe_lock': {'headers': ['Lock'], 'type': 'boolean', 'values': {'yes': True, 'no': False}, 'authority': 'technical_spec'}}}


def evidence(modules='4', *, chunk_id='LAB-ONE', document_id='lab-spec.md', access_level='public'):
    return {'chunk_id': chunk_id, 'document_id': document_id, 'access_level': access_level,
        'source_hash': '1234567890' + 'abcdef' * 9, 'body':
        f'| Item | Modules | Warranty months | Lock |\n|---|---|---|---|\n| LAB-DEVICE | {modules} | 24 | no |'}


def test_attribute_text_is_searchable_without_a_product_name():
    result = _catalog([product()], {'query': 'Zigbee coordinator'})
    assert result['total'] == 1 and result['items'][0]['sku'] == 'LAB-DEVICE'


@pytest.mark.parametrize('filters,expected', [
    ({'child_safe_lock': False}, 1), ({'child_safe_lock': 0}, 0),
    ({'warranty_months': 12}, 1), ({'warranty_months': True}, 0),
    ({'features': 'zigbee COORDINATOR'}, 1), ({'features': 'Wi-Fi'}, 0),
    ({'not_provided': False}, 0),
])
def test_attribute_filters_preserve_types_and_unknown_is_not_false(filters, expected):
    args = SearchInput.model_validate({'attribute_filters': filters}).model_dump(exclude_none=True)
    assert args['attribute_filters'] == filters
    assert _catalog([product()], args)['total'] == expected


def test_resolved_technical_conflict_has_provenance_and_does_not_modify_raw_catalog():
    from app.mcp_servers.mcp_shared.catalog_evidence import enrich_products
    original = product()
    copy = deepcopy(original)
    result = enrich_products([original], [evidence()], rules=rules())[0]
    assert original == copy
    assert result['attributes']['stages'] == 4
    assert result['attributes']['warranty_months'] == 12
    conflicts = {item['field']: item for item in result['attribute_conflicts']}
    assert conflicts['stages']['catalog_value'] == 0
    assert conflicts['stages']['resolved_value'] == 4
    assert conflicts['stages']['resolution'] == 'technical_spec'
    assert conflicts['warranty_months']['resolution'] == 'catalog'
    assert result['attribute_sources']['stages'][0]['chunk_id'] == 'LAB-ONE'
    assert result['list_price_vnd'] == original['list_price_vnd']


def test_conflicting_technical_sources_remain_unresolved():
    from app.mcp_servers.mcp_shared.catalog_evidence import enrich_products
    result = enrich_products([product(stages=7)], [evidence('4'), evidence('5', chunk_id='LAB-TWO')], rules=rules())[0]
    assert 'stages' not in result['attributes']
    conflict = next(item for item in result['attribute_conflicts'] if item['field'] == 'stages')
    assert conflict['resolution'] == 'unresolved' and {e['value'] for e in conflict['evidence']} == {4, 5}


def test_catalog_warranty_priority_survives_multiple_conflicting_specs():
    from app.mcp_servers.mcp_shared.catalog_evidence import enrich_products
    other = evidence(chunk_id='LAB-TWO')
    other['body'] = other['body'].replace('| 24 |', '| 36 |')
    result = enrich_products([product()], [evidence(), other], rules=rules())[0]
    assert result['attributes']['warranty_months'] == 12
    conflict = next(item for item in result['attribute_conflicts'] if item['field'] == 'warranty_months')
    assert conflict['resolution'] == 'catalog' and conflict['resolved_value'] == 12


@pytest.mark.parametrize('row', [evidence(document_id='unapproved.md'), evidence(access_level='restricted'), evidence('four')])
def test_unapproved_private_or_unparseable_evidence_cannot_replace_a_valid_attribute(row):
    from app.mcp_servers.mcp_shared.catalog_evidence import enrich_products
    result = enrich_products([product(stages=7)], [row], rules=rules())[0]
    assert result['attributes']['stages'] == 7


def test_invalid_catalog_value_is_not_presented_as_verified_when_no_resolution_exists():
    from app.mcp_servers.mcp_shared.catalog_evidence import enrich_products
    result = enrich_products([product()], [], rules=rules())[0]
    assert 'stages' not in result['attributes']
    assert result['attribute_conflicts'][0]['resolution'] == 'unresolved'


def test_equal_numeric_values_do_not_report_a_source_conflict():
    from app.mcp_servers.mcp_shared.catalog_evidence import enrich_products
    config = {'documents': ['lab-spec.md'], 'sku_headers': ['Item'], 'fields': {
        'room_area_m2': {'headers': ['Area'], 'type': 'upper_bound', 'minimum': 1, 'authority': 'technical_spec'}}}
    row = evidence() | {'body': '| Item | Area |\n|---|---|\n| LAB-DEVICE | ≤ 25 m² |'}
    result = enrich_products([product(room_area_m2=25)], [row], rules=config)[0]
    assert result['attributes']['room_area_m2'] == 25
    assert not result.get('attribute_conflicts')


def test_model_catalog_tool_and_memory_preserve_filters_and_resolved_evidence(monkeypatch):
    from app.mcp_servers.mcp_shared import catalog_evidence
    from app.mcp_servers.mcp_shared.memory_observations import memory_observations
    from app.mcp_servers.mcp_catalog.tools.handlers import create_server
    from app.agent.mcp.gateway import MCPGateway
    from app.agent.implementations.business_agent import BusinessTools
    from test_write_authorization import OrderRepo, NOW, current

    class Repo(OrderRepo):
        async def rows(self, session, table):
            if table == 'products':
                return [product()]
            if table == 'policy_chunks':
                return [evidence()]
            return await super().rows(session, table)

    async def run():
        monkeypatch.setattr(catalog_evidence, 'load_rules', rules)
        state = current('Tìm bộ điều khiển có giao thức và thuộc tính đã nêu.')
        gateway = MCPGateway(create_server(Repo()), None, None)
        tools = BusinessTools(gateway, state, 8, lambda: NOW)
        tool = next(t for t in tools.langchain_tools() if t.name == 'catalog_search')
        result = await tool.ainvoke({'query': 'Zigbee', 'attribute_filters': {'stages': 4, 'child_safe_lock': False}})
        assert result['total'] == 1
        assert result['items'][0]['attributes']['stages'] == 4
        assert result['items'][0]['attribute_sources']['stages'][0]['source_hash'] == evidence()['source_hash']
        saved = memory_observations(state['tool_calls'])[0]
        assert saved['args']['attribute_filters']['stages'] == 4
        assert saved['result']['items'][0]['attribute_conflicts']
        assert saved['result']['items'][0]['attribute_sources']['stages'][0]['source_hash'] == evidence()['source_hash']
        assert saved['result']['items'][0]['attributes']['features'] == product()['attributes']['features']
    asyncio.run(run())
