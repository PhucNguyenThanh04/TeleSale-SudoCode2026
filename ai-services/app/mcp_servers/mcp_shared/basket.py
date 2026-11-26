from copy import deepcopy
import re

from app.mcp_servers.mcp_shared.commerce_evidence import successful
from app.mcp_servers.mcp_shared.commerce_rules import _search_text


def basket_unit_quote(clause, calls, *, focus_sku=None):
    from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
    quotes = [call for call in calls if call.get('name') == 'pricing.quote_order' and successful(call)]
    if len(quotes) != 1:
        return None
    call = quotes[0]
    units = call['result'].get('units', [])
    mentioned = resolve_claim_skus(clause, calls, focus_sku=focus_sku)
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


def _unit_prices_and_discounts(units, *, include_list_price: bool = False):
    prices, discounts = set(), set()
    for unit in units:
        if type(unit.get('final_price_vnd')) is int:
            prices.add(unit['final_price_vnd'])
        if include_list_price and type(unit.get('list_price_vnd')) is int:
            prices.add(unit['list_price_vnd'])
        if all(type(unit.get(key)) is int for key in ('list_price_vnd', 'final_price_vnd')):
            diff = unit['list_price_vnd'] - unit['final_price_vnd']
            if diff >= 0:
                discounts.add(diff)
        for promo in unit.get('applied_promos') or []:
            if isinstance(promo, dict) and type(promo.get('discount_vnd')) is int:
                discounts.add(promo['discount_vnd'])
    return prices, discounts


def basket_money_evidenced(text, calls):
    from app.agent.guardrails.checks import _money_claims
    from app.agent.guardrails.claims import commercial_clauses
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
    for clause in commercial_clauses(text):
        claims = _money_claims(clause)
        if not claims:
            continue
        found = True
        mentioned = resolve_claim_skus(clause, calls)
        if mentioned and not mentioned <= skus:
            return False
        folded_clause = _search_text(clause)
        include_list = 'niem yet' in folded_clause
        if re.search(r'\btong\b|ca don|ca gio', folded_clause):
            all_unit_prices, all_unit_discounts = _unit_prices_and_discounts(units, include_list_price=include_list)
            price_claims = [amount for amount, kind, _ in claims if kind == 'price']
            if not any(amount == result['total_vnd'] for amount in price_claims):
                return False
            allowed_prices = all_unit_prices | {result['total_vnd']}
            for amount, kind, negative in claims:
                if kind == 'discount':
                    if amount not in all_unit_discounts or (negative and amount > 0):
                        return False
                elif amount not in allowed_prices:
                    return False
        else:
            quoted_unit = basket_unit_quote(clause, calls)
            if quoted_unit is not None:
                target_units = [quoted_unit['result']]
            else:
                target_units = [u for u in units if not mentioned or u['sku'] in mentioned]
                if not target_units or (not mentioned and len(skus) > 1):
                    return False
            prices, discounts = _unit_prices_and_discounts(target_units, include_list_price=include_list)
            for amount, kind, negative in claims:
                if kind == 'discount':
                    if amount not in discounts or (negative and amount > 0):
                        return False
                elif amount not in prices:
                    return False
    return found
