"""Basket purchase permission derived from delivered speech and runtime-owned observations."""
from collections import Counter
from copy import deepcopy
import re

from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence, current_customer_address, successful
from app.mcp_servers.mcp_shared.commerce_rules import _search_text


def _quantities(lines):
    quantities = Counter()
    if not isinstance(lines, list) or not lines:
        return None
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get('sku'), str):
            return None
        qty = line.get('qty', 1)
        if type(qty) is not int or qty < 1:
            return None
        quantities[line['sku']] += qty
    return quantities


def _spoken_quantities(text):
    from app.agent.guardrails.checks import _AREA_NUMBER_WORD, _spoken_integer
    values = re.findall(rf'(?<![\w.,])(\d+|{_AREA_NUMBER_WORD}(?:\s+{_AREA_NUMBER_WORD}){{0,6}})'
                        r'\s*(?:may|chiec|cai|doi|bo|san pham)\b', _search_text(text))
    return {number for value in values
            if (number := int(value) if value.isdigit() else _spoken_integer(value)) is not None}


def current_basket_quote(state):
    quotes = [call for call in build_commerce_evidence(state) if call.get('name') == 'pricing.quote_order']
    return quotes[-1] if quotes else None


def basket_unit_quote(clause, calls):
    """Verifier view for one explicitly referenced unit; never append it to tool traces."""
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
    """A basket total is not a single-product price multiplied by quantity."""
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


def _offer_signature(result):
    return [(unit.get('sku'), unit.get('final_price_vnd'), unit.get('applied_promos', []))
            for unit in result.get('units', [])], result.get('order_promos', []), result.get('total_vnd'), result.get('freeship', False)


def _variants_presented(speech, units, items):
    folded = _search_text(speech)
    for unit in units:
        variant = next((variant for item in items.values() for variant in item.get('variants', [])
                        if variant.get('variant_sku') == unit['sku']), None)
        if variant is None:
            continue
        if re.search(r'(?<![\w-])' + re.escape(_search_text(unit['sku'])) + r'(?![\w-])', folded):
            continue
        terms = [cue + r'\s*' + re.escape(_search_text(str(variant[key]))) + r'(?!\w)'
                 for key, cue in (('size', r'\b(?:size|co|kich co)'), ('color', r'\bmau'))
                 if variant.get(key) is not None]
        if not terms or not all(re.search(term, folded) for term in terms):
            return False
        if len(terms) == 2:
            gap = r'(?:(?!\b(?:size|mau)\b).){0,40}'
            if not any(re.search(first + gap + second, folded)
                       for first, second in (terms, terms[::-1])):
                return False
    return True


def presented_basket_offers(*, customer_id, session_id, committed_turns, tool_calls):
    """A returned tool quote becomes an offer only after verified delivered speech."""
    from app.agent.guardrails.checks import _money_claims
    from app.mcp_servers.mcp_shared.consultation import _mentions
    if not customer_id:
        return []
    visible, latest = [], None
    offered = []
    for turn in committed_turns:
        if turn.get('customer_id') != customer_id or str(turn.get('session_id')) != session_id:
            continue
        tid = str(turn['turn_id'])
        for call in tool_calls:
            if (str(call.get('source_turn_id')) != tid or not successful(call)
                    or call.get('customer_id', customer_id) != customer_id
                    or str(call.get('session_id', session_id)) != session_id):
                continue
            if call.get('name') == 'catalog.search':
                visible.append(call)
            elif call.get('name') == 'pricing.quote_order':
                latest = call
        if latest is None:
            continue
        result = latest['result']
        units = result.get('units', [])
        items = {item['sku']: item for call in visible for item in call['result'].get('items', [])}
        skus = {unit['sku'] for unit in units}
        parents = {sku if sku in items else next((parent for parent, item in items.items()
            if any(v.get('variant_sku') == sku for v in item.get('variants', []))), sku) for sku in skus}
        speech = turn.get('agent_text', '')
        totals = {amount for amount, kind, _ in _money_claims(speech) if kind == 'price'}
        quantities = _spoken_quantities(speech)
        if (units and result.get('total_vnd') in totals and parents <= _mentions(speech, items)
                and (len(units) == 1 or len(units) in quantities)
                and _variants_presented(speech, units, items)
                and basket_money_evidenced(speech, [*visible, latest])):
            offered = [{'customer_id': customer_id, 'session_id': session_id, 'source_turn_id': tid,
                        'quote_source_turn_id': str(latest['source_turn_id']),
                        'lines': deepcopy(latest.get('args', {}).get('lines', [])),
                        'quote': deepcopy(result)}]
    return offered


def basket_purchase_arguments(state):
    from app.mcp_servers.mcp_shared.consultation import customer_order_options
    quote = current_basket_quote(state)
    options = customer_order_options(state)
    if quote is None or options is None:
        return None
    units = quote['result'].get('units', [])
    if not units:
        return None
    return {'lines': [{'sku': unit['sku'], 'qty': 1, 'price_vnd': unit['final_price_vnd']} for unit in units], **options}


def basket_block_reason(state, args, *, require_stock=True):
    from app.agent.guardrails.checks import _money_claims
    from app.mcp_servers.mcp_shared.consultation import _buy, _negated, _mentions, catalog_items, requirements, customer_order_options
    if state.get('identity_status') != 'known':
        return 'identity_required'
    quote = current_basket_quote(state)
    if quote is None:
        return 'current_quote_required'
    result, quoted = quote['result'], quote.get('args', {})
    quantities = _quantities(args.get('lines'))
    units = result.get('units', [])
    if quantities is None or quantities != _quantities(quoted.get('lines')):
        return 'quantity_mismatch'
    if any(type(line.get('price_vnd')) is not int or line['price_vnd'] < 0 for line in args['lines']):
        return 'price_mismatch'
    expected = Counter((unit['sku'], unit['final_price_vnd']) for unit in units)
    proposed = Counter((line['sku'], line['price_vnd']) for line in args['lines'] for _ in range(line.get('qty', 1)))
    if proposed != expected or sum(price * count for (_, price), count in expected.items()) != result.get('total_vnd'):
        return 'price_mismatch'
    if args.get('address') != quoted.get('address') or current_customer_address(state) not in (None, quoted.get('address')):
        return 'current_quote_required'
    options = customer_order_options(state)
    if options is None or args.get('payment', 'COD') != options.get('payment'):
        return 'offer_confirmation_required'
    current = state.get('safe_text', '')
    folded = _search_text(current)
    if (_negated(current) or '?' in current or re.search(r'\bneu\b|can nhac|de hoi|hen|goi lai', folded)
            or not (_buy(current) or re.search(r'\b(?:dong y|chot)\b', folded))):
        return 'purchase_permission_required'
    stated_qty = _spoken_quantities(current)
    if stated_qty and stated_qty != {sum(quantities.values())}:
        return 'quantity_mismatch'
    items = catalog_items(state)
    parents = {sku if sku in items else next((parent for parent, item in items.items()
                if any(v.get('variant_sku') == sku for v in item.get('variants', []))), sku) for sku in quantities}
    if _mentions(current, items) - parents:
        return 'selection_mismatch'
    if any(sku not in items and not any(v.get('variant_sku') == sku for item in items.values()
                                      for v in item.get('variants', [])) for sku in quantities):
        return 'catalog_required'
    from app.agent.harness.policy import resolve_product_selection
    for sku in quantities:
        selection = resolve_product_selection(state, {'sku': sku})
        if selection.status != 'resolved' or selection.sku != sku:
            return 'selection_mismatch'
    # Only a quote actually spoken in committed history can be accepted by "cả hai".
    observations = [*state.get('session_tool_calls', []), *state.get('tool_calls', [])]
    presented_index = None
    heard_turn_ids = set()
    catalog_calls = [call for call in build_commerce_evidence(state) if call.get('name') == 'catalog.search']
    for index, turn in enumerate(state.get('history', [])):
        tid = str(turn.get('source_turn_id', turn.get('turn_id', '')))
        if tid:
            heard_turn_ids.add(tid)
        speech = turn.get('agent', turn.get('agent_text', ''))
        totals = {amount for amount, kind, _ in _money_claims(speech) if kind == 'price'}
        if result.get('total_vnd') not in totals or not parents <= _mentions(speech, items):
            continue
        spoken_qty = _spoken_quantities(speech)
        if sum(quantities.values()) > 1 and sum(quantities.values()) not in spoken_qty:
            continue
        if not _variants_presented(speech, units, items):
            continue
        if any(call.get('name') == 'pricing.quote_order' and successful(call)
               and str(call.get('source_turn_id', '')) in heard_turn_ids
               and call.get('customer_id', state.get('customer_id')) == state.get('customer_id')
               and str(call.get('session_id', state['request'].session_id)) == str(state['request'].session_id)
               and _offer_signature(call['result']) == _offer_signature(result)
               and basket_money_evidenced(speech, [*catalog_calls, call])
               for call in observations):
            presented_index = index
    historical_offer = any(
        episode.get('customer_id') == state.get('customer_id')
        and offer.get('customer_id') == state.get('customer_id')
        and _offer_signature(offer.get('quote', {})) == _offer_signature(result)
        for episode in [*state.get('episodes', []), state.get('current_episode') or {}]
        for offer in episode.get('basket_offers', []))
    if presented_index is None and not historical_offer:
        return 'offer_confirmation_required'
    later = state.get('history', [])[presented_index + 1:] if presented_index is not None else state.get('history', [])
    if any(_negated(turn.get('customer', turn.get('customer_text', ''))) for turn in later):
        return 'offer_confirmation_required'
    needs = requirements(state)
    for sku in parents:
        item = items.get(sku, {})
        attrs = item.get('attributes') or {}
        if needs.get('child_lock_required') and attrs.get('child_safe_lock') is not True:
            return 'product_requirements_not_met'
        if (type(needs.get('room_area_m2')) in (int, float)
                and (item.get('category', '').startswith('gia-dung/may-loc-khong-khi') or 'room_area_m2' in attrs)
                and (type(attrs.get('room_area_m2')) not in (int, float) or attrs['room_area_m2'] < needs['room_area_m2'])):
            return 'product_requirements_not_met'
    codes = {promo.get('promo_code') for unit in units for promo in unit.get('applied_promos', [])}
    codes.update(promo.get('promo_code') for promo in result.get('order_promos', []))
    if needs.get('required_promo_code') and needs['required_promo_code'] not in codes:
        return 'offer_confirmation_required'
    if needs.get('delivery_condition'):
        return 'delivery_confirmation_required'
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    budget = derive_consultation(state).snapshot.budget
    explicit_prices = {amount for amount, kind, _ in _money_claims(current) if kind == 'price'}
    # If the whole basket fits, it also fits a per-item limit; clarification
    # cannot change eligibility. Keep the ambiguity gate when the total exceeds it.
    if (budget.limit_vnd is not None and len(units) > 1 and budget.basis == 'unknown'
            and result['total_vnd'] > budget.limit_vnd):
        return 'budget_basis_required'
    cost = max(unit['final_price_vnd'] for unit in units) if budget.basis == 'unit' else result['total_vnd']
    if budget.limit_vnd is not None and cost > budget.limit_vnd and result['total_vnd'] not in explicit_prices:
        return 'budget_consent_required'
    if require_stock:
        evidence = build_commerce_evidence(state)
        for sku, qty in quantities.items():
            stock = [call for call in evidence if call.get('name') == 'inventory.check'
                     and call.get('args', {}).get('sku') == sku]
            if not stock or stock[-1]['result'].get('in_stock') is not True or stock[-1]['result'].get('qty', 0) < qty:
                return 'current_stock_required'
    return None
