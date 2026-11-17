"""Canonical, bounded offer view derived from committed speech and observations."""
from copy import deepcopy
import json
import re
from app.schemas.consultation import PresentedOffer, SourceRef, ObservationRef, OfferComponentSource
from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
from app.mcp_servers.mcp_shared.commerce_rules import _search_text


def _benefit_key(term):
    return json.dumps({k: v for k, v in term.items() if k != 'promo_code'}, sort_keys=True)


def merge_presented_offer(previous: PresentedOffer | None, incoming: PresentedOffer) -> PresentedOffer:
    if previous is None:
        return incoming.model_copy(deep=True)
    merged = previous.model_copy(deep=True)
    if incoming.price_vnd is not None:
        merged.price_vnd = incoming.price_vnd
    for key, source in incoming.sources.items():
        if key.startswith('term:'):
            term = incoming.promo_terms[int(key.split(':')[1])]
            existing = next((i for i, old in enumerate(merged.promo_terms)
                             if _benefit_key(old) == _benefit_key(term)), None)
            if existing is None:
                merged.sources[f'term:{len(merged.promo_terms)}'] = source
                merged.promo_terms.append(deepcopy(term))
            else:
                merged.promo_terms[existing] = deepcopy(term)
                merged.sources[f'term:{existing}'] = source
        else:
            merged.sources[key] = source.model_copy(deep=True)
    merged.coverage = 'partial' if merged.promo_terms else merged.coverage
    return merged


def extend_presented_offer(previous: PresentedOffer | None, incoming: PresentedOffer,
                           current_calls: list[dict]) -> PresentedOffer:
    """Retain a spoken historical price only after verifying current compatibility."""
    from app.mcp_servers.mcp_shared.consultation import quote_terms, worse_terms
    if (previous is None or previous.price_vnd is None or incoming.price_vnd is not None
            or (previous.sku, previous.variant, previous.qty, previous.basis)
            != (incoming.sku, incoming.variant, incoming.qty, incoming.basis)):
        return incoming
    sku = incoming.variant or incoming.sku
    quotes = [c for c in current_calls if c.get('name') == 'pricing.get_quote'
              and c.get('args', {}).get('sku') == sku]
    if not quotes:
        return incoming
    quote = quotes[-1]
    args, result = quote.get('args', {}), quote.get('result', {})
    price = result.get('final_price_vnd')
    if ('error' in result or type(price) is not int or result.get('sku', sku) != sku
            or args.get('qty', 1) != previous.qty):
        return incoming
    if incoming.basis == 'total':
        price *= previous.qty
    if price != previous.price_vnd or worse_terms(previous.promo_terms, quote_terms(result)):
        return incoming
    return merge_presented_offer(previous, incoming)


def derive_presented_offers(*, customer_id: str | None, session_id: str,
                           committed_turns: list[dict], tool_calls: list[dict]) -> list[PresentedOffer]:
    # Anonymous speech/reads remain session history, not customer-bound offers.
    # Derive again from attributed evidence after identity has been verified.
    if not customer_id:
        return []
    from app.agent.guardrails.checks import _money_claims, check_answer
    from app.mcp_servers.mcp_shared.consultation import quote_terms
    turns = [t for t in committed_turns if t.get('customer_id') == customer_id
             and str(t.get('session_id')) == session_id]
    calls = [c for c in tool_calls if c.get('customer_id', customer_id) == customer_id
             and str(c.get('session_id', session_id)) == session_id]
    offers = []
    signatures = []
    seen = set()
    focus = None
    for turn in turns:
        tid = str(turn.get('turn_id', turn.get('source_turn_id', '')))
        if not tid:
            continue
        seen.add(tid)
        available = [c for c in calls if str(c.get('source_turn_id', '')) in seen]
        # Keep failures when deciding the latest result for a SKU.
        latest = {}
        for c in available:
            if c.get('name') == 'pricing.get_quote':
                latest[c.get('args', {}).get('sku')] = c
        catalogs = [c for c in calls if c.get('name') == 'catalog.search'
                    and 'error' not in c.get('result', {})]
        items = {i['sku']: i for c in catalogs for i in c['result'].get('items', []) if i.get('sku')}
        agent = turn.get('agent_text', turn.get('agent', ''))
        customer = turn.get('customer_text', turn.get('customer', ''))
        selected = resolve_claim_skus(customer, catalogs)
        if len(selected) == 1:
            focus = next(iter(selected))
        named_agent = resolve_claim_skus(agent, catalogs)
        if len(named_agent) == 1:
            focus = next(iter(named_agent))
        for clause in re.split(r'[;!?\n]|\.(?!\d)', agent):
            if not clause.strip():
                continue
            bound = resolve_claim_skus(clause, available, focus_sku=focus)
            if not bound:
                continue
            direct = bound & items.keys() & latest.keys()
            if len(direct) == 1:
                bound = direct
            if len(bound) != 1:
                continue
            sku = next(iter(bound))
            call = latest.get(sku)
            if not call or 'error' in call.get('result', {}) or call['result'].get('success') is False:
                continue
            args, result = call.get('args', {}), call['result']
            if result.get('sku', sku) != sku or args.get('on') != str(turn.get('on', '')):
                continue
            stock = next((c for c in reversed(available)
                          if c.get('name') == 'inventory.check'
                          and c.get('args', {}).get('sku') == sku), None)
            evidence = [*catalogs, call]
            evidence.extend(c for c in available if c.get('name') == 'policy.search'
                            and c.get('args', {}).get('on') == str(turn.get('on', '')))
            if stock and stock.get('args', {}).get('on') == str(turn.get('on', '')):
                evidence.append(stock)
            if check_answer(clause, evidence, focus_sku=sku)[1] is not None:
                continue
            parent = next((p for p, i in items.items() if p == sku or any(
                v.get('variant_sku') == sku for v in i.get('variants', []))), None)
            if not parent:
                continue
            prices = [a for a, kind, neg in _money_claims(clause) if kind == 'price' and not neg]
            folded = _search_text(clause)
            basis = 'total' if re.search(r'\btong\b|ca don', folded) else 'unit'
            expected_price = result.get('final_price_vnd')
            if type(expected_price) is int and basis == 'total':
                expected_price *= args.get('qty', 1)
            price = expected_price if expected_price in prices else None
            terms = []
            spoken_codes = {code for code in re.findall(r'\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b', clause)
                            if not code.startswith('SKU-')}
            all_terms = quote_terms(result)
            generic_gift = (not spoken_codes and bool(re.search(r'tang (?:qua|kem qua)|qua tang', folded))
                            and len([t for t in all_terms if t.get('type') == 'gift']) > 1)
            if generic_gift:
                terms.append({'type': 'gift'})
            for term in all_terms:
                if spoken_codes and term.get('type') not in {'delivery', 'freecod'} and term.get('promo_code') not in spoken_codes:
                    continue
                if generic_gift and term.get('type') == 'gift':
                    continue
                kind = term.get('type')
                if ((kind == 'gift' and re.search(r'tang|qua|bieu', folded))
                    or (kind == 'delivery' and re.search(r'freeship|mien phi (?:ship|van chuyen|giao hang)', folded)
                        and term.get('freeship') is True)
                    or (kind == 'freecod' and 'cod' in folded and 'mien phi' in folded)
                    or (kind in {'fixed','percent','percent_second_item'} and 'giam' in folded
                        and not re.search(r'khong|chua', folded))):
                    terms.append(term)
            if price is None and not terms:
                continue
            evidence = clause.strip()[:200]
            agent_ref = SourceRef(customer_id=customer_id, session_id=session_id, source_turn_id=tid,
                                  source_kind='agent', evidence_quote=evidence)
            source_tid = str(call['source_turn_id'])
            siblings = [c for c in calls if str(c.get('source_turn_id')) == source_tid]
            source = OfferComponentSource(agent=agent_ref, observation=ObservationRef(
                customer_id=customer_id, session_id=session_id, source_turn_id=source_tid,
                observation_index=next(i for i, c in enumerate(siblings) if c is call)))
            sources = {'price': source} if price is not None else {}
            sources.update({f'term:{i}': source for i in range(len(terms))})
            offer = PresentedOffer(sku=parent, variant=sku if sku != parent else None,
                qty=args.get('qty', 1), price_vnd=price, basis=basis, on=args['on'],
                promo_terms=terms, coverage='partial' if terms else 'unknown', sources=sources)
            # Include the full supporting conditions in the transient merge key, never
            # persist unspoken conditions as promises or duplicate tool payloads.
            signature = (sku, args.get('qty', 1), args.get('on'), result.get('final_price_vnd'),
                         tuple(sorted(_benefit_key(t) for t in quote_terms(result))), basis)
            if signature in signatures:
                index = signatures.index(signature)
                offers[index] = merge_presented_offer(offers[index], offer)
            else:
                signatures.append(signature)
                offers.append(offer)
            if len(offers) > 16:
                return []  # Capacity is unknown, never permission to choose an endpoint.
    return offers
