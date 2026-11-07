"""Conservative explanations of BTC mismatches; never changes claims or scores."""
from copy import deepcopy

from app.agent.guardrails.checks import check_answer
from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus


def explain_claim_mismatch(row: dict, field: str, value, *, on: str) -> dict:
    unresolved = {'status': 'unresolved'}
    claims = [c for c in row.get('claims', []) if c.get('field') == field and c.get('value') == value]
    if len(claims) != 1 or field not in {'price_vnd', 'promo_active'}:
        return unresolved
    text = claims[0].get('text')
    if not text:
        return unresolved
    calls = row.get('tool_calls', [])
    named = resolve_claim_skus(text, calls)
    quotes = [c for c in calls if c.get('name') == 'pricing.get_quote'
              and (not named or c.get('args', {}).get('sku') in named)]
    # Repeated identical reads are harmless; competing quotes are ambiguous.
    distinct = []
    for quote in quotes:
        normalized = {**quote, 'args': {'qty': 1, **quote.get('args', {})}}
        if normalized not in distinct:
            distinct.append(normalized)
    if len(distinct) != 1 or len(named) > 1:
        return unresolved
    quote = distinct[0]
    args, result = quote.get('args', {}), quote.get('result', {})
    sku = args.get('sku')
    if (not sku or args.get('on') != on or result.get('sku') != sku or
            'error' in result or result.get('ok') is False or result.get('success') is False):
        return unresolved
    if field == 'price_vnd':
        supported = (type(value) is int and result.get('final_price_vnd') == value and
                     check_answer(text, [quote], row.get('user_text', ''), focus_sku=sku)[1] is None)
    else:
        if value is not True:
            return unresolved
        # An expired applied-promo receipt cannot support a current benefit.
        current = deepcopy(quote)
        current['result']['applied_promos'] = [p for p in result.get('applied_promos', [])
            if not p.get('valid_until') or p['valid_until'] >= on]
        supported = bool(current['result']['applied_promos'] or result.get('freeship')) and \
            check_answer(text, [current], row.get('user_text', ''), focus_sku=sku)[1] is None
    return {'status': 'supported_by_quote', 'sku': sku} if supported else unresolved
