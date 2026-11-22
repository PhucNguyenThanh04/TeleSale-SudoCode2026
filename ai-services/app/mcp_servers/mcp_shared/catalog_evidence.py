import hashlib
import json
import math
import re
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from app.mcp_servers.mcp_shared.commerce_rules import _catalog, _search_text


@lru_cache(maxsize=1)
def load_rules():
    return json.loads(Path(__file__).with_name('catalog-evidence.json').read_text())


def _valid(value, rule):
    if rule['type'] == 'boolean':
        return type(value) is bool
    return (type(value) in {int, float} and math.isfinite(value)
            and (rule['type'] != 'integer' or type(value) is int)
            and value >= rule.get('minimum', 0))


def _parse(cell, rule):
    cell = cell.strip(' *`')
    if rule['type'] == 'boolean':
        return next((value for key, value in rule['values'].items() if _search_text(key) == _search_text(cell)), None)
    pattern = r'\d+' if rule['type'] == 'integer' else r'(?:≤|<=)?\s*(\d+(?:[.,]\d+)?)\s*(?:m²|m2)?'
    match = re.fullmatch(pattern, cell)
    if match is None:
        return None
    value = int(cell) if rule['type'] == 'integer' else float(match[1].replace(',', '.'))
    return value if _valid(value, rule) else None


def _table_rows(rows, rules):
    sku_headers = {_search_text(value) for value in rules['sku_headers']}
    for row in rows:
        if row.get('access_level') != 'public' or row.get('document_id') not in rules['documents']:
            continue
        headers = None
        for line in row.get('body', '').splitlines():
            if not line.strip().startswith('|'):
                headers = None
                continue
            cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
            if any(_search_text(cell) in sku_headers for cell in cells):
                headers = cells
                continue
            if not headers or len(cells) != len(headers) or all(not cell.strip('-: ') for cell in cells):
                continue
            sku = cells[next(i for i, label in enumerate(headers) if _search_text(label) in sku_headers)]
            yield sku, [(label, value.strip(' *`')) for label, value in zip(headers, cells)
                        if _search_text(label) not in sku_headers], row


def _source(row):
    return {key: row[key] for key in ('chunk_id', 'document_id', 'source_hash')}


def _technical_rows(rows, rules):
    facts = defaultdict(lambda: defaultdict(list))
    for sku, properties, row in _table_rows(rows, rules):
        for field, rule in rules['fields'].items():
            for label, cell in properties:
                if _search_text(label) not in {_search_text(value) for value in rule['headers']}:
                    continue
                value = _parse(cell, rule)
                if value is not None:
                    facts[sku][field].append({'value': value, **_source(row)})
    return facts


def enrich_products(products, evidence, *, rules=None):
    rules = load_rules() if rules is None else rules
    facts = _technical_rows(evidence, rules)
    result = []
    for raw in products:
        item = deepcopy(raw)
        sources, conflicts = {}, []
        catalog_hash = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        for field, rule in rules['fields'].items():
            if field not in raw['attributes']:
                continue
            original = raw['attributes'][field]
            entries = facts[raw['sku']].get(field, [])
            values = {(type(entry['value']), entry['value']) for entry in entries}
            valid = _valid(original, rule)
            catalog_source = {'source': 'catalog', 'sku': raw['sku'], 'source_hash': catalog_hash, 'value': original}
            authority = ('catalog' if field in {'warranty_months', 'stock', 'price_vnd', 'list_price_vnd'}
                         else rule['authority'])
            if not entries and valid:
                continue
            if (len(values) > 1 and authority != 'catalog'
                    or not entries and not valid or authority == 'catalog' and not valid):
                item['attributes'].pop(field, None)
                conflicts.append({'field': field, 'catalog_value': original,
                                  'resolution': 'unresolved', 'evidence': entries})
                continue
            value = entries[0]['value']
            resolved = original if authority == 'catalog' else value
            item['attributes'][field] = resolved
            sources[field] = [catalog_source] if authority == 'catalog' else entries
            if not valid or any(original != entry['value'] for entry in entries):
                conflicts.append({'field': field, 'catalog_value': original,
                    'resolved_value': resolved, 'resolution': authority, 'evidence': entries})
        if sources:
            item['attribute_sources'] = sources
        if conflicts:
            item['attribute_conflicts'] = conflicts
        result.append(item)
    return result


def product_details(product, evidence, requested_sku, *, selected_variant=None):
    rules = load_rules()
    enriched = enrich_products([product], evidence, rules=rules)[0]
    item = _catalog([enriched], {'sku': product['sku']})['items'][0]
    item['brand'] = product.get('brand')
    item['selected_variant'] = ({key: deepcopy(selected_variant[key])
        for key in ('variant_sku', 'size', 'color', 'price_delta_vnd') if key in selected_variant}
        if selected_variant else None)
    groups = {}
    table_chunks = set()
    for sku, properties, row in _table_rows(evidence, rules):
        if sku not in {product['sku'], requested_sku}:
            continue
        table_chunks.add(row['chunk_id'])
        for label, value in properties:
            if not value or value in {'-', '—'}:
                continue
            key = _search_text(label)
            prop = groups.setdefault(key, {'name': label, 'observations': []})
            prop['observations'].append({'value': value, 'scope_sku': sku, **_source(row)})
    specifications = []
    for label, prop in groups.items():
        observations = prop['observations']
        values = {entry['value'] for entry in observations}
        field = next((field for field, rule in rules['fields'].items()
                      if label in {_search_text(header) for header in rule['headers']}), None)
        prop.update(value=next(iter(values)) if len(values) == 1 else None,
                    status='supported' if len(values) == 1 else 'unresolved',
                    sources=[_source(entry) for entry in observations])
        catalog_record = (product if field in {'list_price_vnd', 'price_vnd', 'stock'}
                          else product['attributes'])
        if field in catalog_record:
            prop['attribute'] = field
            if catalog_record is product:
                value = catalog_record[field] if _valid(catalog_record[field], rules['fields'][field]) else None
            else:
                value = enriched['attributes'].get(field)
            prop['value'] = value
            prop['status'] = 'resolved' if value is not None else 'unresolved'
            catalog_source = {
                'source': 'catalog', 'sku': product['sku'], 'value': catalog_record[field],
                'source_hash': hashlib.sha256(json.dumps(product, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
            prop['sources'] = enriched.get('attribute_sources', {}).get(field,
                [catalog_source] if value is not None else [*prop['sources'], catalog_source])
        specifications.append(prop)
    sections = {section for binding in rules.get('section_bindings', [])
                if product['sku'] in binding['skus'] for section in binding['section_ids']}
    contextual = [{**_source(row), 'content': row['body'], 'scope': 'section_context'}
                  for row in evidence if row.get('access_level') == 'public'
                  and row.get('document_id') in rules['documents']
                  and row.get('chunk_id') in sections - table_chunks]
    item.update(specifications=specifications, technical_evidence=contextual,
                technical_data_status='available' if specifications or contextual else 'not_available')
    return item
