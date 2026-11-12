"""Pure consultation decisions from observed speech and verified tool evidence.

Catalog order can choose a recommendation, never customer consent. Caller state
must be owner-bound by the harness/MCP; no scenario or expected-answer input.
"""
from copy import deepcopy
from datetime import date
import re
from app.mcp_servers.mcp_shared.decision_diagnostics import gate_boundary, emit as diagnostic_emit, active as diagnostic_active
from typing import Any

from app.schemas.consultation import (AcceptedOffer, ConsultationDecision,
    ConsultationSnapshot, Delegation, SourceRef, SpendingLimit, PresentedOffer, mask_evidence)
from app.mcp_servers.mcp_shared.commerce_rules import _search_text
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence, current_customer_address
from app.agent.guardrails.checks import customer_budget_amounts, _money_claims


def successful(call):
    result=call.get('result')
    return isinstance(result,dict) and 'error' not in result and result.get('ok') is not False and result.get('success') is not False


def observations(state):
    return build_commerce_evidence(state)


def catalog_items(state):
    items={}
    for call in observations(state):
        if call.get('name')=='catalog.search' and successful(call):
            for item in (call['result'].get('items') or []) if isinstance(call['result'].get('items'),list) else []:
                if isinstance(item,dict) and isinstance(item.get('sku'),str): items[item['sku']]=item
    return items


def _mentions(text, items):
    from app.mcp_servers.mcp_shared.commerce_entities import allows_short_product_name
    folded=_search_text(text)
    matches=[]
    aliases={}
    for sku,item in items.items():
        words=_search_text(item.get('name','')).split()
        starts = range(max(0,len(words)-1)) if allows_short_product_name(text, item) else range(1)
        for start in starts:
            aliases.setdefault(' '.join(words[start:]),set()).add(sku)
        # BTC tool metadata omits brand; proper-name tokens still support a
        # unique spoken short name without changing the tool result contract.
        if allows_short_product_name(text, item) and not (item.get('attributes') or {}).get('bundle_of'):
            labels = [item['brand']] if item.get('brand') else [
                word for word in item.get('name', '').split()[1:]
                if len(word) >= 3 and word[0].isupper()]
            for label in labels:
                aliases.setdefault(_search_text(label), set()).add(sku)
    for sku,item in items.items():
        labels=[sku,item.get('name','')]
        labels.extend(label for label,owners in aliases.items() if owners=={sku})
        labels.extend(v.get('variant_sku','') for v in item.get('variants',[]) if isinstance(v,dict))
        for label in labels:
            if not label: continue
            for m in re.finditer(r'(?<![\w-])'+re.escape(_search_text(label))+r'(?![\w-])',folded):
                matches.append((m.start(),m.end(),sku))
    return {sku for start,end,sku in matches if not any(a<=start and b>=end and b-a>end-start for a,b,_ in matches)}


def quote_terms(result):
    terms=[{k:deepcopy(v) for k,v in p.items() if k in {'promo_code','type','discount_vnd','gift_sku','qty'}}
           for p in (result.get('applied_promos') or []) if isinstance(p,dict)]
    if type(result.get('freeship')) is bool:
        terms.append({'type':'delivery','freeship':result['freeship']})
    return terms


def worse_terms(old, new):
    for benefit in old:
        kind=benefit.get('type')
        if kind in {'fixed','percent','percent_second_item'}: continue  # final price is checked separately
        if kind in {'freeship','delivery'}:
            promised=kind=='freeship' or benefit.get('freeship') is True
            if promised and not any(p.get('type')=='freeship' or p.get('freeship') is True for p in new):return True
        elif kind=='gift':
            if not any((not benefit.get('gift_sku') or p.get('gift_sku')==benefit.get('gift_sku')) and p.get('type')=='gift' and p.get('qty',1)>=benefit.get('qty',1) for p in new):return True
        elif kind=='freecod':
            if not any(p.get('type')=='freecod' for p in new):return True
        elif benefit not in new:return True
    return False


def requested_quantity(state):
    found=re.findall(r'(?<!\d)(\d+)\s*(?:chiec|cai|doi|bo|san pham)\b',_search_text(state.get('safe_text','')))
    return int(found[0]) if len(set(found))==1 else None


def current_quote(state, sku, qty=1):
    request=state.get('request')
    on=getattr(request,'on',None)
    on=on.isoformat() if hasattr(on,'isoformat') else str(on or '')
    matching=[c for c in observations(state) if c.get('name')=='pricing.get_quote' and c.get('args',{}).get('sku')==sku]
    if not matching: return None
    call=matching[-1];args=call.get('args',{});result=call.get('result',{})
    if (not successful(call) or args.get('on')!=on or args.get('qty',1)!=qty or result.get('sku',sku)!=sku
            or type(result.get('final_price_vnd')) is not int): return None
    return AcceptedOffer(sku=sku,variant=sku,qty=qty,price_vnd=result['final_price_vnd'],on=on,
                         promo_terms=quote_terms(result))


def _ref(state, turn, kind, text):
    quote = mask_evidence(text)[:200]
    if quote.rfind('[') > quote.rfind(']'):
        quote = quote[:quote.rfind('[')]
    req=state.get('request')
    return SourceRef(customer_id=state.get('customer_id'),session_id=str(getattr(req,'session_id','')),
                     source_turn_id=str(turn),source_kind=kind,evidence_quote=quote)


def _restore(state):
    if state.get('identity_status')!='known' or not state.get('customer_id'): return ConsultationSnapshot()
    current=state.get('current_episode') or {}
    entries=[]
    for ep in [*state.get('episodes',[]),current]:
        if not isinstance(ep,dict) or ep.get('customer_id',state['customer_id'])!=state['customer_id']:continue
        for topic in ep.get('topics',[]):
            if topic.get('scope_type')!='global' or not topic.get('consultation'):continue
            try:snap=ConsultationSnapshot.model_validate(topic['consultation'])
            except ValueError:continue
            if any(ref.customer_id!=state['customer_id'] for ref in snap.source_refs.values()):continue
            if any(snap.source_refs[k].source_kind!='customer' for k in ('selected_sku','budget','accepted_offer','delegation') if k in snap.source_refs):continue
            if snap.presented_offer and any(src.agent.customer_id != state['customer_id'] for src in snap.presented_offer.sources.values()):continue
            if snap.accepted_offer and snap.accepted_offer.presented_source is None:
                consent_ref = snap.source_refs.get('accepted_offer')
                explicit = consent_ref.evidence_quote if consent_ref else ''
                if (not any(amount == snap.accepted_offer.price_vnd for amount, kind, negative in _money_claims(explicit)
                            if kind == 'price' and not negative)
                        or _negated(explicit) or not (_buy(explicit) or 'dong y' in _search_text(explicit))):
                    snap.accepted_offer = None

            rank=(str(ep.get('on_date',ep.get('on',''))),int(ep is current),str(ep.get('updated_at',ep.get('created_at',''))))
            entries.append((rank,snap))
    merged=ConsultationSnapshot()
    # Merge only fields with provenance. Omission is not a revocation. Conflicts
    # without ordering evidence remain unknown; a null with a source is a tombstone.
    for field in ('candidates','recommended_sku','selected_sku','budget','presented_offer','accepted_offer','delegation'):
        versions=[(rank,snap) for rank,snap in entries if field in snap.source_refs]
        if not versions:continue
        newest=max(rank for rank,_ in versions)
        recent=[snap for rank,snap in versions if rank==newest]
        values=[getattr(snap,field) for snap in recent]
        if all(v==values[0] for v in values):setattr(merged,field,deepcopy(values[0]))
        merged.source_refs[field]=recent[0].source_refs[field].model_copy(deep=True)
    if merged.presented_offer and merged.presented_offer.price_vnd is None:
        from app.mcp_servers.mcp_shared.presented_offers import extend_presented_offer
        historical = [(rank, snap.presented_offer) for rank, snap in entries
                      if snap.presented_offer and snap.presented_offer.price_vnd is not None]
        if historical:
            newest = max(rank for rank, _ in historical)
            recent = [offer for rank, offer in historical if rank == newest]
            if all(offer == recent[0] for offer in recent):
                merged.presented_offer = extend_presented_offer(recent[0], merged.presented_offer,
                                                               observations(state))
    named = _mentions(state.get('safe_text', ''), catalog_items(state))
    if len(named) == 1:
        parent = next(iter(named))
        candidates = []
        for ep in [*state.get('episodes', []), current]:
            if not isinstance(ep, dict) or ep.get('customer_id', state['customer_id']) != state['customer_id']:
                continue
            raw = ep.get('offer_candidates', [])
            if not isinstance(raw, list) or len(raw) > 16:
                continue
            for value in raw:
                try:
                    offer = PresentedOffer.model_validate(value)
                except ValueError:
                    continue
                if offer.sku == parent and offer.sources and all(
                        src.agent.customer_id == state['customer_id'] for src in offer.sources.values()):
                    candidates.append(offer)
        if candidates:
            dates = [str(o.on) for o in candidates]
            recent = [o for o in candidates if str(o.on) == max(dates)]
            # Contradictory same-day versions from different sessions have no order.
            sessions = {src.agent.session_id for o in recent for src in o.sources.values()}
            if len(sessions) == 1 or all(o == recent[0] for o in recent):
                focused = _focused_offer(recent, state)
                if focused:
                    merged.presented_offer = focused
                    merged.source_refs['presented_offer'] = next(reversed(focused.sources.values())).agent
    return merged


def _negated(text):
    return bool(re.search(r'\b(?:khong|chua|dung)\s+(?:(?:muon|dinh)\s+)?(?:mua|lay|chon|dat|len|tao|order|chot|dong y)\b|\b(?:huy|bo mau|doi y)\b',_search_text(text)))


def _buy(text):
    folded=_search_text(text)
    from app.mcp_servers.mcp_shared.consultation_followup import order_status_requested
    if order_status_requested(text) and not re.search(
            r'len don|len order|tao don|chot don|mua (?:them|lai)|dat (?:them|moi)', folded):
        return False
    return not _negated(text) and not re.search(r'\bneu\b',folded) and bool(re.search(
        r'\b(?:len don|len order|tao don|dat hang|dat mua|chot don|mua|lay)\b',folded)) and not re.search(r'xem|can nhac|de biet|gia bao nhieu',folded)


def _requirement_changes(text):
    folded=_search_text(text)
    if '?' in text:return {}
    changes={}
    delivery = re.search(r'\bgiao\b|(?<!xac )\bnhan(?: hang)? (?:truoc|trong|dung|vao)\b', folded)
    if delivery:
        if (not re.search(r'\bneu\b|khong bo|chua bo', folded)
                and re.search(r'khong can giao|bo (?:yeu cau|dieu kien) giao', folded)):
            changes['delivery_condition'] = None
        elif (re.search(r'(?:bat buoc|nhat dinh|phai|can) (?:duoc )?(?:giao|nhan)|(?:giao|nhan(?: hang)?)[^,;.]{0,60}bat buoc|chi (?:mua|lay).{0,60}\b(?:neu|khi)\b|moi (?:mua|lay)', folded)
                or re.search(r'(?:giao|nhan(?: hang)?) (?:truoc|dung|vao)\b|\btruoc\s+(?:\d|thu\b|ngay\b|hom\b)|\d+\s*(?:gio|ngay)\b', folded)
                or re.search(r'(?:giao|nhan(?: hang)?) trong\b', folded)
                and not re.search(r'(?:giao|nhan(?: hang)?) trong tuan\b', folded)):
            changes['delivery_condition'] = mask_evidence(text)[:200]
    if re.search(r'\bneu\b', folded):return changes
    areas=re.findall(r'(?<![\d.])(\d+(?:[.,]\d+)?)\s*(?:m2|m²|met vuong)(?!\w)',folded)
    if len(set(areas))==1:changes['room_area_m2']=float(areas[0].replace(',','.'))
    if re.search(r'(?:bat buoc|can(?: co)?|phai co).{0,25}khoa tre em',folded):changes['child_lock_required']=True
    if re.search(r'khong can.{0,20}khoa tre em|bo yeu cau.{0,20}khoa tre em',folded):changes['child_lock_required']=False
    if re.search(r'khong can (?:giao|dung ma)|bo (?:yeu cau|dieu kien) giao', folded):
        if 'ma' in folded:changes['required_promo_code'] = None
    code = re.search(r'(?i)(?:phải dùng mã|bắt buộc.*?mã|dùng mã)\s+([A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+)', text)
    if code and not re.search(r'khong (?:can|dung)|chua', folded):
        changes['required_promo_code'] = code[1].upper()
    return changes


def requirements(state):
    result={k:v for k,v in _restore(state).delegation.constraints.items() if k in {'room_area_m2','child_lock_required','delivery_condition','required_promo_code'}}
    fact=state.get('profile',{}).get('room_area_m2',{})
    if type(fact.get('value')) in (int,float):result['room_area_m2']=fact['value']
    from app.mcp_servers.mcp_shared.room_context import named_rooms
    rooms=state.get('scoped_facts',{}).get('room',{})
    selected_rooms=named_rooms(state.get('safe_text',''), rooms)
    room_values={f.get('room_area_m2',{}).get('value') for room,f in rooms.items()
                 if isinstance(f,dict) and (not selected_rooms or room in selected_rooms)}-{None}
    if len(room_values)==1:result['room_area_m2']=next(iter(room_values))
    elif len(room_values)>1:result.pop('room_area_m2',None)
    for turn in state.get('history',[]):
        text=turn.get('customer',turn.get('customer_text',''))
        changes=_requirement_changes(text)
        if selected_rooms and named_rooms(text, rooms)!=selected_rooms:
            changes.pop('room_area_m2',None)
        result.update(changes)
    result.update(_requirement_changes(state.get('safe_text','')))
    return result


def _approval(text, previous_agent, focus, visible):
    return bool(focus and visible and visible.sku==focus and
        re.fullmatch(r'(?:da\s+)?(?:dong y|vang|u|ok|duoc(?: roi)?|dung roi)(?:\s+(?:a|nhe))?'
                     r'(?:,?\s+(?:cam on|thanks|thank you)(?:\s+(?:anh|chi|em|ban))?)?',
                     _search_text(text).strip(' .!?')) and
        re.search(r'len don|tao don|dat hang|mua',_search_text(previous_agent)) and
        ('?' in previous_agent or re.search(r'dong y|xac nhan',_search_text(previous_agent))))


def _apply_customer(snap,text,items,focus,visible,ref,state,*,approval=False):
    folded=_search_text(text)
    if re.search(r'\bneu\b',folded):
        needed = _requirement_changes(text)
        if needed:
            snap.delegation = snap.delegation.model_copy(update={'constraints': {**snap.delegation.constraints, **needed}})
            snap.source_refs['delegation'] = ref
        return focus
    amounts=customer_budget_amounts(text)
    if len(amounts)==1:
        snap.budget=SpendingLimit(limit_vnd=next(iter(amounts)),mode='hard' if re.search(r'toi da|khong vuot|khong qua|duoi',folded) else 'approx',
            basis='total' if re.search(r'tong|ca don|tat ca',folded) else 'unit' if re.search(r'moi|don gia',folded) else 'unknown')
        snap.source_refs['budget']=ref
    if _negated(text) and re.search(r'chua mua|khong (?:mua|lay|chon)|dung (?:mua|lay)|huy|bo mau|doi y',folded):
        snap.selected_sku=None;snap.accepted_offer=None;snap.delegation=Delegation(status='revoked')
        for key in ('selected_sku','accepted_offer','delegation'):snap.source_refs[key]=ref
        return None
    needed=_requirement_changes(text)
    if needed:
        snap.delegation=Delegation(status='unknown',constraints={**snap.delegation.constraints,**needed})
        snap.source_refs['delegation']=ref
    mentioned=_mentions(text,items)
    wants_choice=approval or _buy(text) or (not _negated(text) and bool(re.search(r'\b(?:chon|lay|mua|doi sang|chot)\b',folded)) and not re.search(r'xem them|can nhac',folded))
    from app.agent.harness.catalog_query import explicit_product_queries
    named = [_mentions(query, items) for query in explicit_product_queries(text)]
    if wants_choice and named and (any(len(matches) != 1 for matches in named)
                                  or any(matches != named[0] for matches in named)):
        snap.selected_sku = None
        snap.accepted_offer = None
        snap.source_refs['selected_sku'] = snap.source_refs['accepted_offer'] = ref
        return None
    candidate=next(iter(mentioned)) if len(mentioned)==1 else focus if not mentioned and (_buy(text) or re.search(r'mau (?:nay|do|hom truoc)|may (?:nay|do)|san pham (?:nay|do)|cai (?:nay|do)',folded)) else None
    if approval:candidate=focus
    if wants_choice and candidate:
        if candidate!=snap.selected_sku:
            snap.accepted_offer=None;snap.source_refs['accepted_offer']=ref
        snap.selected_sku=candidate;snap.source_refs['selected_sku']=ref
    delegated=not _negated(text) and bool(re.search(r'chon (?:giup|ho)|tu chon',folded)) and _buy(text)
    if delegated:
        snap.delegation=Delegation(status='active',constraints={**snap.delegation.constraints,**snap.budget.model_dump(),**requirements(state)})
        snap.source_refs['delegation']=ref
        eligible=[sku for sku in items if _eligible(state,sku,snap.budget)]
        if len(eligible)==1:
            snap.selected_sku=eligible[0];snap.source_refs['selected_sku']=ref
    if (_buy(text) or approval) and snap.selected_sku:
        sku=snap.selected_sku
        offer=visible if visible and visible.sku==sku else None
        qty=requested_quantity({'safe_text':text}) or (visible.qty if visible and visible.sku==sku else 1)
        from app.agent.harness.policy import resolve_product_selection
        selection=resolve_product_selection(state,{'sku':sku})
        quote=current_quote(state,selection.sku,qty) if selection.status=='resolved' else None
        if re.search(r'\bgia\b',folded):
            amounts=[a for a,kind,_ in _money_claims(text) if kind=='price']
            if amounts:
                offer=quote if quote and quote.price_vnd in amounts else None
                if offer is None:
                    snap.accepted_offer=None;snap.source_refs['accepted_offer']=ref
        if offer and offer.variant:
            from app.agent.harness.policy import resolve_product_selection
            chosen = resolve_product_selection(state, {'sku': sku})
            if chosen.status == 'resolved' and chosen.sku != offer.variant:
                offer = None
                snap.accepted_offer = None
                snap.source_refs['accepted_offer'] = ref
        if offer:
            snap.accepted_offer=offer.model_copy(deep=True);snap.source_refs['accepted_offer']=ref
    return next(iter(mentioned)) if len(mentioned)==1 else focus


def _eligible(state,sku,budget):
    items=catalog_items(state);item=items.get(sku,{})
    attrs=item.get('attributes') or {}
    if attrs.get('discontinued'):return False
    needs=requirements(state)
    area=needs.get('room_area_m2')
    if type(area) in (int,float) and (type(attrs.get('room_area_m2')) not in (int,float) or attrs['room_area_m2']<area):return False
    if needs.get('child_lock_required') is True and attrs.get('child_safe_lock') is not True:return False
    # Variant ambiguity is independent from parent product interest.
    if item.get('variants'):
        from app.agent.harness.policy import resolve_product_selection
        if resolve_product_selection(state,{'sku':sku}).status!='resolved':return False
    quote=current_quote(state,sku)
    price=quote.price_vnd if quote else item.get('list_price_vnd')
    return type(price) is int and (budget.limit_vnd is None or price<=budget.limit_vnd)


def _focused_offer(offers, state):
    if not offers:
        return None
    from app.agent.harness.policy import resolve_product_selection
    parents = {o.sku for o in offers}
    if len(parents) != 1:
        return None
    selected = resolve_product_selection(state, {'sku': next(iter(parents))})
    if selected.status == 'resolved':
        specific = [o for o in offers if o.variant == selected.sku]
        offers = specific or [o for o in offers if o.variant is None]
    qty = requested_quantity(state)
    if qty is not None:
        offers = [o for o in offers if o.qty == qty]
    if len({(o.variant, o.qty, o.basis) for o in offers}) != 1:
        return None
    return offers[-1] if offers else None


def _accepted_view(offer):
    if not offer or offer.price_vnd is None or offer.qty is None or offer.basis == 'unknown':
        return None
    source = offer.sources.get('price')
    if not source:
        return None
    return AcceptedOffer(sku=offer.sku, variant=offer.variant, qty=offer.qty,
                         price_vnd=(offer.price_vnd // offer.qty if offer.basis == 'total' else offer.price_vnd),
                         on=offer.on, basis='unit', presented_basis=offer.basis,
                         promo_terms=deepcopy(offer.promo_terms), presented_source=source.agent)


def derive_consultation(state: dict) -> ConsultationDecision:
    snap=_restore(state);items=catalog_items(state)
    snap.candidates=list(items)[:16]
    catalogs=[c for c in observations(state) if c.get('name')=='catalog.search' and successful(c)]
    if catalogs:
        snap.source_refs['candidates']=_ref(state,catalogs[-1].get('source_turn_id',getattr(state.get('request'),'client_msg_id','')),'tool','catalog.search')
    if snap.budget.limit_vnd is None and 'budget' not in snap.source_refs:
        fact=state.get('profile',{}).get('budget_vnd',{})
        if fact.get('source') and fact.get('source_kind','customer')=='customer' and type(fact.get('value')) is int:
            snap.budget=SpendingLimit(limit_vnd=fact['value'],mode='approx',basis='unknown')
    focus=snap.selected_sku or (None if 'selected_sku' in snap.source_refs else snap.recommended_sku)
    visible=_accepted_view(snap.presented_offer) or snap.accepted_offer
    if not focus and snap.presented_offer and 'selected_sku' not in snap.source_refs:
        focus=snap.presented_offer.sku
    previous_agent=''
    offers=[]
    for i,turn in enumerate(state.get('history',[])):
        if not isinstance(turn,dict):continue
        customer=turn.get('customer',turn.get('customer_text',''))
        agent=turn.get('agent',turn.get('agent_text',''))
        ref=_ref(state,turn.get('source_turn_id',turn.get('turn_id',f'history-{i}')),'customer',customer)
        focus=_apply_customer(snap,customer,items,focus,visible,ref,state,approval=_approval(customer,previous_agent,focus,visible))
        mentioned=_mentions(agent,items)
        from app.mcp_servers.mcp_shared.commerce_entities import product_alternatives_requested
        if (focus and _mentions(customer, items) == {focus}
                and not product_alternatives_requested(customer)):
            # A previous agent mistake is not evidence that the customer switched.
            mentioned &= {focus}
        if len(mentioned)==1 and not re.search(r'khong phu hop|khong de xuat|khong nen',_search_text(agent)):
            focus=next(iter(mentioned))
            if re.search(r'de xuat|goi y|phu hop',_search_text(agent)):
                snap.recommended_sku=focus;snap.source_refs['recommended_sku']=_ref(state,ref.source_turn_id,'agent',agent)
        elif mentioned:
            focus=None;visible=None
        from app.mcp_servers.mcp_shared.presented_offers import derive_presented_offers, extend_presented_offer
        req = state.get('request')
        sid = str(getattr(req, 'session_id', ''))
        prefix = [{'turn_id': str(t.get('source_turn_id', t.get('turn_id', f'history-{j}'))),
                   'customer_id': state.get('customer_id'), 'session_id': sid,
                   'on': str(t.get('on', getattr(req, 'on', ''))),
                   'customer_text': t.get('customer', t.get('customer_text', '')),
                   'agent_text': t.get('agent', t.get('agent_text', ''))}
                  for j, t in enumerate(state.get('history', [])[:i+1])]
        historical_calls = [*state.get('session_tool_calls', []), *state.get('tool_calls', [])]
        offers = derive_presented_offers(customer_id=state.get('customer_id'), session_id=sid,
                                        committed_turns=prefix, tool_calls=historical_calls)
        relevant = [o for o in offers if o.sku == focus] if focus else offers
        # Latest conditions for one explicitly focused product may supersede old
        # conditions; multiple products never acquire focus from list order.
        if relevant and len({o.sku for o in relevant}) == 1:
            presented = _focused_offer(relevant, state)
            if presented is not None:
                presented = extend_presented_offer(snap.presented_offer, presented, observations(state))
            snap.presented_offer = presented
            if presented is None:
                snap.source_refs['presented_offer'] = _ref(state, ref.source_turn_id, 'agent', agent)
                visible = None
                previous_agent = agent
                continue
            latest_source = next((v.agent for v in reversed(list(presented.sources.values()))), None)
            if latest_source:
                snap.source_refs['presented_offer'] = latest_source
            visible = _accepted_view(presented)
            focus = presented.sku
        elif len({o.sku for o in relevant}) > 1:
            snap.presented_offer = None
            snap.source_refs['presented_offer'] = _ref(state, ref.source_turn_id, 'agent', agent)
            visible = None
        if snap.selected_sku is None and snap.delegation.status == 'revoked':
            focus = None
            visible = None
        previous_agent=agent
    text=state.get('safe_text','');req=state.get('request')
    named = _mentions(text, items)
    if len(named) == 1:
        chosen_parent = next(iter(named))
        candidates = [o for o in offers if o.sku == chosen_parent]
        if candidates:
            chosen_offer = _focused_offer(candidates, state)
            visible = _accepted_view(chosen_offer)
            snap.presented_offer = chosen_offer
            if chosen_offer:
                snap.source_refs['presented_offer'] = next(reversed(chosen_offer.sources.values())).agent
            focus = chosen_parent
    ref=_ref(state,str(getattr(req,'client_msg_id','')),'customer',text)
    approved=_approval(text,previous_agent,focus,visible)
    focus=_apply_customer(snap,text,items,focus,visible,ref,state,approval=approved)
    intent=_buy(text) or approved

    missing=[]
    if intent and not snap.selected_sku:missing.append('selection')
    action='purchase' if intent and snap.selected_sku else 'quote' if focus else 'clarify' if items else 'search'
    if re.search(r'tam dung|chua mua|de .*hoi|se goi lai|goi lai sau|de .*goi lai',_search_text(text)):action='pause'
    decision=ConsultationDecision(snapshot=snap,purchase_intent=intent,missing_fields=missing,next_action=action)
    # Runtime-only focus never supplies customer selection by itself.
    decision.focus_sku=focus
    return decision


@gate_boundary
def purchase_block_reason(state: dict, args: dict) -> str | None:
    if state.get('identity_status')!='known':return 'identity_required'
    d=derive_consultation(state);snap=d.snapshot
    if diagnostic_active():
        diagnostic_emit('gate_input', state=state, snapshot=snap.model_dump(mode='json'),
                        decision=d.model_dump(mode='json'), args=args)
    if not d.purchase_intent:return 'purchase_permission_required'
    if not snap.selected_sku:return 'selection_required'
    sku=args.get('sku');qty=args.get('qty',1)
    if type(qty) is not int or qty<1:return 'quantity_required'
    if requested_quantity(state) is not None and requested_quantity(state)!=qty:return 'quantity_mismatch'
    from app.agent.harness.policy import resolve_product_selection
    selected=resolve_product_selection(state,{'sku':snap.selected_sku,'size':args.get('size'),'color':args.get('color')})
    if selected.status!='resolved':return selected.status
    if sku not in {snap.selected_sku,selected.sku}:return 'selection_mismatch'
    sku=selected.sku
    parent=catalog_items(state).get(selected.parent_sku,{})
    needs=requirements(state);attrs=parent.get('attributes') or {}
    if diagnostic_active():
        diagnostic_emit('requirements_checked', state=state, args={**needs, 'child_safe_lock': attrs.get('child_safe_lock'), 'required_room_area_m2': needs.get('room_area_m2'), 'room_area_m2': attrs.get('room_area_m2')})
    if needs.get('child_lock_required') is True and attrs.get('child_safe_lock') is not True:return 'product_requirements_not_met'
    if type(needs.get('room_area_m2')) in (int,float) and (type(attrs.get('room_area_m2')) not in (int,float) or attrs['room_area_m2']<needs['room_area_m2']):return 'product_requirements_not_met'
    quote=current_quote(state,sku,qty)
    compatible=build_commerce_evidence(state,args=args)
    if diagnostic_active():
        diagnostic_emit('quote_binding', state=state, args={**args, **({'price_vnd': quote.price_vnd, 'on': quote.on, 'promo_terms': quote.promo_terms} if quote else {})}, status='success' if quote is not None and any(c.get('name')=='pricing.get_quote' for c in compatible) else 'failed')
    if quote is None or not any(c.get('name')=='pricing.get_quote' for c in compatible):return 'current_quote_required'
    if args.get('price_vnd')!=quote.price_vnd:return 'price_mismatch'
    stock=[c for c in observations(state) if c.get('name')=='inventory.check' and c.get('args',{}).get('sku')==sku]
    on=str(getattr(state.get('request'),'on',''))
    if diagnostic_active():
        diagnostic_emit('stock_binding', state=state, args={**stock[-1].get('args', {}), 'available_qty': stock[-1].get('result', {}).get('qty')} if stock else {}, fresh=bool(stock and stock[-1].get('args', {}).get('on')==on), quantity_sufficient=bool(stock and type(stock[-1].get('result', {}).get('qty')) is int and stock[-1]['result']['qty']>=qty), status='success' if stock and successful(stock[-1]) else 'failed', in_stock=stock[-1].get('result', {}).get('in_stock') if stock else None)
    if not stock or not successful(stock[-1]) or stock[-1].get('args',{}).get('on')!=on or stock[-1]['result'].get('in_stock') is not True or type(stock[-1]['result'].get('qty')) is not int or stock[-1]['result'].get('qty',0)<qty:
        return 'current_stock_required'
    # The current tools provide estimates, not confirmation of customer deadlines.
    if needs.get('delivery_condition'):
        return 'delivery_confirmation_required'
    if needs.get('required_promo_code') and not any(t.get('promo_code')==needs['required_promo_code'] for t in quote.promo_terms):return 'offer_confirmation_required'
    consent=snap.accepted_offer
    if consent:
        if consent.basis != 'unit':return 'offer_confirmation_required'
        if consent.sku not in {sku,snap.selected_sku} or consent.qty!=qty or consent.variant not in {None,sku}:return 'offer_confirmation_required'
        if quote.price_vnd>consent.price_vnd or worse_terms(consent.promo_terms,quote.promo_terms):return 'offer_confirmation_required'
    elif snap.delegation.status!='active' or snap.source_refs.get('delegation') is None or snap.source_refs['delegation'].session_id!=str(getattr(state.get('request'),'session_id','')):return 'offer_confirmation_required'
    cost=quote.price_vnd*(qty if snap.budget.basis=='total' else 1)
    delegated_limit=snap.delegation.constraints.get('limit_vnd')
    if not consent and (type(delegated_limit) is not int or cost>delegated_limit):return 'budget_consent_required'
    if qty>1 and snap.budget.limit_vnd is not None and snap.budget.basis=='unknown':return 'budget_basis_required'
    if snap.budget.limit_vnd is not None and cost>snap.budget.limit_vnd:
        budget_ref=snap.source_refs.get('budget');offer_ref=snap.source_refs.get('accepted_offer')
        if not consent or (budget_ref and offer_ref and budget_ref.source_turn_id==offer_ref.source_turn_id):return 'budget_consent_required'
    return None



def purchase_arguments(state: dict) -> dict | None:
    """Build a candidate order from sourced selection and customer options, never a draft."""
    from app.agent.harness.policy import resolve_product_selection
    decision = derive_consultation(state)
    if not decision.purchase_intent or decision.next_action == 'pause':
        return None
    sku = decision.snapshot.selected_sku
    if not sku:
        return None
    selection = resolve_product_selection(state, {'sku': sku})
    if selection.status != 'resolved':
        return None
    qty = requested_quantity(state) or (decision.snapshot.accepted_offer.qty if decision.snapshot.accepted_offer else 1)
    offer = current_quote(state, selection.sku, qty)
    if offer is None:
        return None
    args = {'sku': selection.sku, 'qty': qty, 'price_vnd': offer.price_vnd, 'payment': 'COD'}
    options = customer_order_options(state)
    if options is None:
        return None
    args.update(options)
    return args


def customer_order_options(state: dict) -> dict | None:
    """Customer-sourced transaction options, shared with quote preparation."""
    args = {'payment': 'COD'}
    speech = [t.get('customer', t.get('customer_text', '')) for t in state.get('history', [])]
    speech.append(state.get('safe_text', ''))
    for text in speech:
        folded = _search_text(text)
        if re.search(r'\bneu\b', folded):
            continue
        methods = set()
        refused = set()
        for pattern, value in [(r'\bcod\b', 'COD'), (r'chuyen khoan|\bbank\b', 'bank'),
                               (r'\bmomo\b', 'momo'), (r'\bzalopay\b', 'zalopay')]:
            for match in re.finditer(pattern, folded):
                if re.search(r'(?:khong|chua)\s+(?:thanh toan\s+)?(?:bang\s+)?$', folded[:match.start()]):
                    refused.add(value)
                else:
                    methods.add(value)
        if len(methods) > 1:
            return None
        if methods:
            args['payment'] = next(iter(methods))
        elif args['payment'] in refused:
            args['payment'] = None
    if args['payment'] is None:
        return None
    address = current_customer_address(state)
    if address:
        args['address'] = address
    return args


def consultation_missing_fields(state: dict) -> list[str]:
    """Explain the same gate, without inventing an independent permission decision."""
    from app.agent.harness.policy import resolve_product_selection
    decision = derive_consultation(state)
    if not decision.purchase_intent:
        return []
    if state.get('identity_status') != 'known':
        return ['identity']
    if not decision.snapshot.selected_sku:
        return ['selection']
    selection = resolve_product_selection(state, {'sku': decision.snapshot.selected_sku})
    if selection.status != 'resolved':
        return list(selection.missing_fields) or ['catalog']
    if customer_order_options(state) is None:
        return ['payment']
    args = purchase_arguments(state)
    if args is None:
        return ['quote']
    reason = purchase_block_reason(state, args)
    mapping = {'current_quote_required': 'quote', 'current_stock_required': 'stock',
               'offer_confirmation_required': 'offer', 'budget_consent_required': 'budget',
               'budget_basis_required': 'budget_basis', 'delivery_confirmation_required': 'delivery', 'product_requirements_not_met': 'requirements'}
    return [mapping.get(reason, reason)] if reason else []


def committed_consultation(customer_id, session_id, turns, calls, *, prior_episodes=None):
    """Rebuild a historical snapshot from ordered, owner-bound committed turns."""
    from types import SimpleNamespace
    bound=[t for t in turns if t.get('customer_id')==customer_id and str(t.get('session_id'))==session_id]
    if not bound:return ConsultationSnapshot()
    ids={str(t['turn_id']) for t in bound}
    verified=[c for c in calls if str(c.get('source_turn_id')) in ids]
    last=bound[-1]
    state={'customer_id':customer_id,'identity_status':'known',
        'request':SimpleNamespace(session_id=session_id,client_msg_id=str(last['turn_id']),on=date.fromisoformat(str(last['on']))),
        'history':[{'customer':t.get('customer_text',''),'agent':t.get('agent_text',''),'source_turn_id':str(t['turn_id']), 'on': str(t['on'])} for t in bound],
        'safe_text':'','tool_calls':verified,'episodes':prior_episodes or []}
    return derive_consultation(state).snapshot


def admit_consultation(snapshot: dict, *, customer_id: str, session_id: str,
                       committed_turns: list[dict], tool_calls: list[dict], prior_episodes: list[dict] | None = None) -> dict | None:
    try:
        proposed=ConsultationSnapshot.model_validate(snapshot)
        canonical=committed_consultation(customer_id,session_id,committed_turns,tool_calls,prior_episodes=prior_episodes)
        patch=proposed.model_dump(mode='json',exclude_unset=True)
        actual=canonical.model_dump(mode='json')
        fields=set(patch)-{'source_refs','schema_version'}
        if not fields:return None
        refs=patch.get('source_refs',{})
        if set(refs)!=fields:return None
        for field in fields:
            if patch[field]!=actual[field] or refs[field]!=actual['source_refs'].get(field):return None
        return patch
    except (ValueError,TypeError,KeyError):
        return None
