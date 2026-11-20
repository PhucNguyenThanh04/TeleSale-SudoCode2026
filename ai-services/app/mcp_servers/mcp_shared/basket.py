from copy import deepcopy
import re

from app.mcp_servers.mcp_shared.commerce_evidence import successful
from app.mcp_servers.mcp_shared.commerce_rules import _search_text


def basket_unit_quote(clause, calls):
    from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
    quotes = [call for call in calls if call.get('name') == 'pricing.quote_order' and successful(call)]
    if len(quotes) != 1:
        return None
    call = quotes[0]
    units = call['result'].get('units', [])
    mentioned = resolve_claim_skus(clause, calls)
    units = [unit for unit in units if not mentioned or unit['sku'] in mentioned]
    match = re.search(r'\bmay\s+(?:thu\s+)?(\d+|mot|hai|ba|bon|nam)\b', _search_text(clause))
    if match:
        position = int(match[1]) if match[1].isdigit() else {'mot': 1, 'hai': 2, 'ba': 3, 'bon': 4, 'nam': 5}[match[1]]
        units = [unit for unit in units if unit.get('unit') == position]
    if len(units) != 1:
        return None
    unit = units[0]
    return {'name': 'pricing.get_quote', 'args': {'sku': unit['sku'], 'on': call.get('args', {}).get('on')},
            'result': {'sku': unit['sku'], 'list_price_vnd': unit['list_price_vnd'],
                       'final_price_vnd': unit['final_price_vnd'],
                       'applied_promos': deepcopy(unit.get('applied_promos', [])),
                       'freeship': call['result'].get('freeship', False)}}


def basket_money_evidenced(text, calls):
    from app.agent.guardrails.checks import _money_claims
    from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
    quotes = [call for call in calls if call.get('name') == 'pricing.quote_order' and successful(call)]
    if len(quotes) != 1:
        return False
    result = quotes[0]['result']
    units = result.get('units', [])
    if not units or sum(unit.get('final_price_vnd', 0) for unit in units) != result.get('total_vnd'):
        return False
    skus = {unit['sku'] for unit in units}
    found = False
    for clause in re.split(r'[;!?\n]|\.(?!\d)', text):
        claims = _money_claims(clause)
        if not claims:
            continue
        found = True
        mentioned = resolve_claim_skus(clause, calls)
        if mentioned and not mentioned <= skus:
            return False
        if re.search(r'\btong\b|ca don|ca gio', _search_text(clause)):
            if any(kind != 'price' or amount != result['total_vnd'] for amount, kind, _ in claims):
                return False
        else:
            quoted_unit = basket_unit_quote(clause, calls)
            if quoted_unit is None:
                return False
            unit = quoted_unit['result']
            for amount, kind, negative in claims:
                expected = (unit['list_price_vnd'] - unit['final_price_vnd']) if kind == 'discount' else unit['final_price_vnd']
                if amount != expected or kind == 'discount' and negative:
                    return False
    return found
