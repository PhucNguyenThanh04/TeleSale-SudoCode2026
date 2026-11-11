"""Pure, sourced consultation scope and ranking; never grants customer consent."""
from copy import deepcopy
from dataclasses import dataclass
import math
import re
from uuid import UUID

from app.mcp_servers.mcp_shared.commerce_rules import _search_text
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
from app.mcp_servers.mcp_shared.consultation import (
    _mentions, _restore, _requirement_changes, catalog_items, current_quote, customer_order_options,
    derive_consultation, requested_quantity, requirements, successful,
)


@dataclass
class Shortlist:
    items: list[dict]
    missing_fields: list[str]
    scope_known: bool


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def consultation_active(state):
    decision = derive_consultation(state)
    if decision.next_action == 'pause':
        return False
    text = _search_text(state.get('safe_text', ''))
    return decision.purchase_intent or bool(re.search(
        r'gia|khuyen mai|uu dai|ship|cod|bao nhieu|tu van|goi y|phu hop|ngan sach|muc chi|'
        r'\d\s*m2\b|dien tich|be nho|con nho|tre em|khoa tre|chi (?:toi da|khoang|tam)|doi (?:mau|loai|sang)|chuyen sang|chon mau', text))


def consultation_scope(state: dict) -> dict:
    """Freeze established scope before a new broad lookup can pollute candidates."""
    items = catalog_items(state)
    decision = derive_consultation(state)
    text = state.get('safe_text', '')
    mentioned = _mentions(text, items)
    captured = state.get('consultation_scope')
    reconsider = (not decision.snapshot.selected_sku and bool(
        _requirement_changes(text) or re.search(r'ngan sach|muc chi|toi da|chi (?:khoang|tam)', _search_text(text))))
    if _type_change(text) and not mentioned:
        for call in reversed(state.get('tool_calls', [])):
            args = call.get('args', {})
            query = args.get('query')
            if (call.get('name') != 'catalog.search' or not successful(call)
                    or not _specific_query(query) or _search_text(query) not in _search_text(text)):
                continue
            found = [p for p in call.get('result', {}).get('items', []) if isinstance(p, dict) and p.get('sku')]
            categories = {p.get('category') for p in found} - {None, ''}
            category = args.get('category') or (next(iter(categories)) if len(categories) == 1 else None)
            if found and category:
                return {'skus': sorted(p['sku'] for p in found), 'category': category, 'known': True}
        return {'skus': [], 'known': False}
    if (captured and captured.get('known') and not mentioned
            and not (reconsider and captured.get('focus_sku'))):
        return deepcopy(captured)
    if mentioned:
        categories = {items[sku].get('category') for sku in mentioned if sku in items} - {None, ''}
        return {'skus': sorted(mentioned), 'category': next(iter(categories)) if len(categories) == 1 else None,
                'focus_sku': decision.focus_sku if decision.focus_sku in mentioned else None,
                'known': True}
    if decision.focus_sku and not reconsider:
        return {'skus': [decision.focus_sku], 'focus_sku': decision.focus_sku, 'known': True}
    prior = _restore(state)
    # Only admitted prior candidates, not the derive result overwritten by this turn's search.
    if prior.candidates and prior.source_refs.get('candidates'):
        return {'skus': sorted(prior.candidates), 'known': True}
    evidence = build_commerce_evidence(state)
    prior_calls = state.get('session_tool_calls', [])
    catalogs = [c for c in evidence if c.get('name') == 'catalog.search' and successful(c)]
    prior_catalogs = [c for c in catalogs if c in prior_calls]
    for call in reversed(prior_catalogs or catalogs):
        found = [i for i in call.get('result', {}).get('items', []) if isinstance(i, dict) and i.get('sku')]
        args = call.get('args', {})
        categories = {i.get('category') for i in found} - {None, ''}
        category = args.get('category') or (next(iter(categories)) if len(categories) == 1 else None)
        if found and (category or args.get('sku') or args.get('min_room_area_m2') is not None
                      or args.get('max_price_vnd') is not None or _specific_query(args.get('query'))):
            return {'skus': sorted(i['sku'] for i in found), 'category': category, 'known': True}
    # Historical advice can bound a metadata read, never establish selection or
    # turn an old price into current evidence. The store binds facts to the owner.
    if state.get('identity_status') == 'known' and state.get('customer_id'):
        remembered = []
        for sku, facts in state.get('scoped_facts', {}).get('product', {}).items():
            fact = facts.get('product_advised', {})
            source = fact.get('source', '')
            if (fact.get('status', 'active') != 'active' or fact.get('value') != sku
                    or not isinstance(source, str) or not source.startswith('langmem:')):
                continue
            try:
                session, turn = source.split(':')[-2:]
                UUID(session)
                UUID(turn)
            except (ValueError, TypeError):
                continue
            remembered.append(sku)
        if len(remembered) == 1:
            return {'skus': remembered, 'known': True}
    return {'skus': [], 'known': False}


def _type_change(text):
    folded = _search_text(text)
    return bool(re.search(r'\b(?:doi (?:sang|loai)|chuyen sang)\b', folded)
                and not re.search(r'\bdoi sang (?:size|mau|co)\b', folded))


def shortlist_requirements(state):
    turns = [t.get('customer', t.get('customer_text', '')) for t in state.get('history', [])]
    turns.append(state.get('safe_text', ''))
    switches = [i for i, text in enumerate(turns) if _type_change(text)]
    if not switches:
        return requirements(state)
    result = {}
    for text in turns[switches[-1]:]:
        result.update(_requirement_changes(text))
    return result


def _specific_query(value):
    if not isinstance(value, str) or not value.strip():
        return False
    return not re.search(r'\b(?:alo|hom truoc|lan truoc|xin chao)\b', _search_text(value))


def prefers_child_safety(state):
    if shortlist_requirements(state).get('child_lock_required') is False:
        return False
    return (state.get('profile', {}).get('has_children', {}).get('value') is True or
            any(re.search(r'\b(?:con nho|be nho|tre nho|tre em|em be)\b',
                          _search_text(t.get('customer', t.get('customer_text', ''))))
                for t in [*state.get('history', []), {'customer': state.get('safe_text', '')}]))


def _quote(state, sku, qty):
    if state.get('request') is not None:
        offer = current_quote(state, sku, qty)
        return offer.price_vnd if offer is not None else None
    matches = [c for c in build_commerce_evidence(state) if c.get('name') == 'pricing.get_quote'
               and c.get('args', {}).get('sku') == sku and c.get('args', {}).get('qty', 1) == qty]
    if matches and successful(matches[-1]):
        value = matches[-1]['result'].get('final_price_vnd')
        return value if type(value) is int else None
    return None


def build_shortlist(state: dict, *, scope: dict, quoted_only: bool = False) -> Shortlist:
    """Rank current compatible metadata; indicative prices do not establish affordability."""
    from app.agent.harness.policy import resolve_product_selection
    decision = derive_consultation(state)
    needs = shortlist_requirements(state)
    budget = decision.snapshot.budget
    qty = requested_quantity(state) or (decision.snapshot.accepted_offer.qty if decision.snapshot.accepted_offer else 1)
    missing = set()
    if qty > 1 and budget.limit_vnd is not None and budget.basis == 'unknown':
        missing.add('budget_basis')
    if not scope.get('known'):
        return Shortlist([], ['product_scope'], False)
    focus = scope.get('focus_sku')
    allowed = set(scope.get('skus', []))
    category = scope.get('category')
    # A sourced category permits new products in that category; absent category keeps the admitted SKU set.
    soft_child = prefers_child_safety(state)
    ranked = []
    for item in catalog_items(state).values():
        sku = item['sku']
        variants = {v.get('variant_sku') for v in item.get('variants', []) if isinstance(v, dict)}
        if focus:
            if focus not in {sku, *variants}:
                continue
        elif category:
            if item.get('category') != category:
                continue
        elif sku not in allowed:
            continue
        if item.get('discontinued') is True or item.get('attributes', {}).get('discontinued') is True or item.get('status') == 'discontinued':
            continue
        attrs = item.get('attributes') or {}
        area = needs.get('room_area_m2')
        if _number(area):
            capacity = attrs.get('room_area_m2')
            if not _number(capacity):
                missing.add('room_area_m2')
                continue
            if capacity < area:
                continue
        if needs.get('child_lock_required') is True and attrs.get('child_safe_lock') is not True:
            if type(attrs.get('child_safe_lock')) is not bool:
                missing.add('child_lock_required')
            continue
        selection = resolve_product_selection(state, {'sku': focus or sku})
        if selection.status != 'resolved':
            missing.update(selection.missing_fields or ('variant',))
            continue
        resolved = selection.sku
        read_args = {'sku': resolved, 'qty': qty}
        options = customer_order_options(state) or {}
        if options.get('address'):
            read_args['address'] = options['address']
        compatible = build_commerce_evidence(state, args=read_args)
        stock = next((c['result'] for c in compatible if c.get('name') == 'inventory.check'), None)
        if stock is not None and (stock.get('in_stock') is False or
                type(stock.get('qty')) is int and stock['qty'] < qty):
            continue
        quote = _quote(state, resolved, qty)
        if not any(c.get('name') == 'pricing.get_quote' for c in compatible):
            quote = None
        if quoted_only and quote is None:
            continue
        price = quote if quote is not None else item.get('list_price_vnd')
        price = price if type(price) is int and price >= 0 else None
        cost = price * (qty if budget.basis == 'total' else 1) if price is not None else None
        if budget.limit_vnd is None or 'budget_basis' in missing:
            affordability = 0 if price is not None else 1
        else:
            affordability = 1 if cost is None else 0 if cost <= budget.limit_vnd else 2
        preference = int(soft_child and attrs.get('child_safe_lock') is not True)
        # Household safety comes before the desired spend; purchase still needs budget consent.
        rank = (preference, affordability, price if price is not None else math.inf, resolved)
        ranked.append((rank, {**deepcopy(item), 'resolved_sku': resolved,
                              'quoted_price_vnd': quote, 'quote_qty': qty}))
    return Shortlist([item for _, item in sorted(ranked, key=lambda pair: pair[0])],
                     sorted(missing), True)
