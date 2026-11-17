"""Sourced follow-up tasks. No memory writes, competitor claims or purchase permission."""
from dataclasses import dataclass, field
import re
from uuid import UUID

from app.mcp_servers.mcp_shared.commerce_rules import _search_text
from app.mcp_servers.mcp_shared.consultation import catalog_items, derive_consultation
from app.agent.memory.episode_candidates import blocker_resolution


def order_status_requested(text: str) -> bool:
    folded = _search_text(text)
    folded = re.split(r'\bneu\b', folded, maxsplit=1)[0]
    return bool(re.search(r'\bdon\b|tracking', folded)
                and re.search(r'\btra\b|kiem (?:tra|lai)|tinh trang|trang thai|van don|tracking|'
                              r'da (?:duoc )?xac nhan|ban giao|du kien giao', folded)
                and not re.search(r'(?:khong|chua|dung).{0,12}(?:kiem (?:tra|lai)|\btra\b)', folded))


@dataclass
class FollowupTask:
    kind: str = 'none'
    focus_sku: str | None = None
    missing_fields: list[str] = field(default_factory=list)
    policy_query: str | None = None
    objection: dict | None = None
    open_blocker: dict | None = None
    order_id: str | None = None


def _valid_turn(value):
    try:
        UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _price_objection(text):
    return bool(re.search(r'dat qua|dat hon|gia cao|so sanh gia|ben kia|ben khac|'
                          r'doi thu|khong giam|giam them', _search_text(str(text)).replace('_', ' ')))


def _source(fact):
    if not isinstance(fact, dict) or fact.get('status', 'active') != 'active':
        return None
    source = fact.get('source')
    if not isinstance(source, str) or not source.startswith('langmem:'):
        return None
    parts = source.split(':')
    return (parts[-2], parts[-1]) if len(parts) >= 3 and _valid_turn(parts[-1]) else None


def _resolved(state, item):
    source = item.get('source_turn_id')
    history = state.get('history', [])
    at = next((i for i, t in enumerate(history) if t.get('source_turn_id') == source), None)
    request = state.get('request')
    same_session = item.get('session_id') == str(getattr(request, 'session_id', ''))
    following = history[at + 1:] if at is not None else [] if same_session else history
    return any(blocker_resolution(t.get('customer', t.get('customer_text', '')),
        {'blocker': {'value': item['text']}})[0] for t in [*following, {'customer': state.get('safe_text', '')}])


def _open_items(state, focus):
    if not focus or not state.get('customer_id'):
        return []
    episodes = [*state.get('episodes', []), state.get('current_episode') or {}]
    episodes = [ep for ep in episodes if isinstance(ep, dict) and ep.get('status', 'active') == 'active'
                and ep.get('customer_id', state['customer_id']) == state['customer_id']]
    closed = {r.get('item_id') for ep in episodes for r in ep.get('resolved_prior_items', []) if isinstance(r, dict)}
    result = []
    for ep in episodes:
        for topic in ep.get('topics', []):
            if topic.get('scope_type') != 'product' or topic.get('scope_id') != focus:
                continue
            for item in topic.get('items', []):
                if (item.get('kind') not in {'blocker', 'objection'} or item.get('status') != 'open'
                        or item.get('item_id') in closed or not _valid_turn(item.get('source_turn_id'))):
                    continue
                candidate = {**item, 'session_id': str(ep.get('session_id', ''))}
                if isinstance(candidate.get('text'), str) and not _resolved(state, candidate):
                    result.append(candidate)
    for key, fact in state.get('scoped_facts', {}).get('product', {}).get(focus, {}).items():
        if key not in {'objection', 'blocker'} or fact.get('source_kind') != 'customer':
            continue
        source = _source(fact)
        if source and isinstance(fact.get('value'), str):
            candidate = {'text': fact['value'], 'source_turn_id': source[1], 'session_id': source[0]}
            if not _resolved(state, candidate):
                result.append(candidate)
    # Runtime-bound customer turns can establish the same product link without an LLM extraction.
    from app.mcp_servers.mcp_shared.consultation import _mentions
    items = catalog_items(state)
    historical_focus = None
    for t in state.get('history', []):
        speech = t.get('customer', t.get('customer_text', ''))
        named = _mentions(speech, items)
        if named:
            historical_focus = next(iter(named)) if len(named) == 1 else None
        if (historical_focus == focus and _price_objection(speech)
                and _valid_turn(t.get('source_turn_id'))):
            candidate = {'text': speech, 'source_turn_id': t['source_turn_id'],
                         'session_id': str(getattr(state.get('request'), 'session_id', ''))}
            if not _resolved(state, candidate):
                result.append(candidate)
        named_agent = _mentions(t.get('agent', t.get('agent_text', '')), items)
        if named_agent:
            historical_focus = next(iter(named_agent)) if len(named_agent) == 1 else None
    return result


def _policy_question(text):
    folded = _search_text(text)
    if re.search(r'(?:khong|chua) can (?:hoi|tra cuu|kiem tra|noi).{0,25}(?:bao hanh|chinh sach|quy dinh giao lai)', folded):
        return None
    topic_pattern = r'bao hanh|chinh sach|doi tra|tra hang|hoan tien|doi size|phi (?:doi|ship|van chuyen)|mat phi|thu hoi|tem mac|tem nhan|quy dinh giao lai|giao lai'
    topic = re.search(topic_pattern, folded)
    if not topic:
        return None
    if (re.search(r'tem mac|tem nhan', folded)
            and not re.search(r'bao hanh|chinh sach|doi tra|tra hang|hoan tien|doi size|\bphi\b|thu hoi|giao lai|'
                              r'dieu kien|quy dinh|yeu cau|the nao|ra sao|luu y|can.{0,20}giu|giu.{0,20}khong', folded)):
        return None  # Reporting intact packaging is not itself a policy question.
    if not (re.search(r'\?|the nao|ra sao|luu y|bao lau|may ngay|co .{0,60}khong|cho (?:biet|hoi)|kiem tra|tra cuu|chinh sach|quy dinh', folded)
            or folded.strip() in {'bao hanh', 'doi tra', 'phi doi size'}):
        return None
    # Keep the actual question and remove a trailing sales pause rather than dropping the question.
    clauses = re.split(r'[?;\n]', text)
    index = next((i for i, c in enumerate(clauses) if re.search(topic_pattern, _search_text(c))), None)
    # A fee question can depend on the preceding question (e.g. changing size).
    # Keep that context instead of retrieving generic shipping fees in isolation.
    return ('? '.join(clauses[:index + 1]) if index is not None else text).strip()[:400]


def followup_task(state: dict) -> FollowupTask:
    text = state.get('safe_text', '')
    decision = derive_consultation(state)
    focus = decision.focus_sku
    if not focus:
        scoped = state.get('scoped_facts', {}).get('product', {})
        linked = [sku for sku, facts in scoped.items() if _source(facts.get('product_advised'))]
        if len(linked) == 1:
            focus = linked[0]
    query = _policy_question(text)
    if query:
        task = FollowupTask('policy', focus_sku=focus, policy_query=query)
        # Rights tied to an existing order keep the existing ownership and order.status boundary.
        folded = _search_text(text)
        if re.search(r'\bdon\b|da mua|da nhan|mua hom|mua ngay|doi.{0,30}hom truoc|(?:ao|hang) cu', folded):
            requested = re.findall(r'\bOD[A-Z0-9-]+\b', text)
            owned = set(state.get('owned_order_ids', [])) | set(state.get('remembered_order_ids', []))
            orders = requested or (list(owned) if len(owned) == 1 else [])
            if len(orders) == 1 and orders[0] in owned:
                task.order_id = orders[0]
            else:
                task.missing_fields.append('order_owner')
        return task
    if decision.next_action == 'pause' or decision.purchase_intent:
        return FollowupTask(focus_sku=focus)
    if _price_objection(text):
        return FollowupTask('price_objection', focus_sku=focus,
            missing_fields=[] if focus else ['product_scope'], objection={'text': text})
    open_items = _open_items(state, focus)
    objection = next((i for i in reversed(open_items) if _price_objection(i['text'])), None)
    returning = bool(re.search(r'goi lai|hom truoc|lan truoc', _search_text(text)) or
                     state.get('turn_no') == 1 and state.get('episodes'))
    if objection and returning:
        return FollowupTask('returning_objection', focus_sku=focus, objection=objection,
                            open_blocker=next(iter(open_items), None))
    return FollowupTask(focus_sku=focus)


def policy_arguments(state, task):
    args = {'query': task.policy_query, 'on': str(getattr(state.get('request'), 'on', ''))}
    if task.order_id:
        orders = [order for c in state.get('tool_calls', []) if c.get('name') == 'order.status'
                  and 'error' not in c.get('result', {}) for order in c['result'].get('orders', [])
                  if order.get('order_id') == task.order_id]
        if len(orders) != 1:
            return None
        created = orders[0].get('created_on') or orders[0].get('created_at') or orders[0].get('date')
        if not created:
            return None
        args['order_date'] = str(created)[:10]
    return args


def policy_call_for_task(state, task):
    from app.knowledge.context import selected_release
    args = policy_arguments(state, task)
    verified_order = args is not None and task.order_id is not None
    if args is None:
        # A model may obtain a conditional public explanation using a customer-reported date.
        # This never supplies a verified order_date or entitlement.
        args = {'query': task.policy_query, 'on': str(getattr(state.get('request'), 'on', ''))}
    for index, call in reversed(list(enumerate(state.get('tool_calls', [])))):
        if call.get('name') != 'policy.search':
            continue
        actual = call.get('args', {})
        if verified_order and state.get('policy_order_bindings', {}).get(index) != task.order_id:
            continue
        if any(actual.get(k) != args.get(k) for k in ('query', 'on', 'order_date')):
            continue
        context = call.get('result', {}).get('context') or {}
        if context.get('on', args['on']) != args['on']:
            continue
        release = selected_release()
        if release and context.get('knowledge_release_id') != release:
            continue
        return call
    return None


def product_price_requested(text):
    folded = re.sub(r'\bgia (?:han|dung|dinh)\b', '', _search_text(text))
    return bool(re.search(r'\bgia\b|bao nhieu tien|may tien', folded))


def stock_requested(text):
    folded = _search_text(text)
    return bool(re.search(r'con hang|het hang|co (?:san )?hang|co san trong kho|ton kho|nhap lai|con (?:size|co)\s+\d+', folded)
                and not re.search(r'(?:khong|chua|dung)\s+(?:can\s+)?kiem tra\s+(?:ton kho|hang)', folded))


def compatible_quote(state, focus):
    from app.agent.harness.policy import resolve_product_selection
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    from app.mcp_servers.mcp_shared.consultation import requested_quantity, customer_order_options
    if not focus:
        return None
    selection = resolve_product_selection(state, {'sku': focus})
    if selection.status != 'resolved':
        return None
    qty = requested_quantity(state) or 1
    args = {'sku': selection.sku, 'qty': qty}
    options = customer_order_options(state) or {}
    if options.get('address'):
        args['address'] = options['address']
    calls = [c for c in build_commerce_evidence(state, args=args) if c.get('name') == 'pricing.get_quote']
    return calls[-1] if calls else None


def offer_changes(state, focus, result):
    """Only classify sourced old codes; absence from applied_promos is not expiry."""
    from app.mcp_servers.mcp_shared.consultation import quote_terms, worse_terms
    decision = derive_consultation(state)
    old = decision.snapshot.presented_offer
    if old is not None and focus not in {old.sku, old.variant}:
        old = None
    codes = {t.get('promo_code') for t in old.promo_terms if t.get('promo_code')} if old else set()
    requested = re.findall(r'\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b|\b[A-Z][A-Z0-9-]*[0-9][A-Z0-9-]*\b', state.get('safe_text', ''))
    codes.update(c for c in requested if not c.startswith(('SKU-', 'OD-')))
    def code_set(values):
        return {v.get('promo_code') if isinstance(v, dict) else v for v in values if isinstance(v, (str, dict))}
    applied = code_set(result.get('applied_promos', []))
    expired = code_set(result.get('expired_promos', []))
    ineligible = code_set(result.get('ineligible_promos', []))
    exclusive = code_set(result.get('not_applied_exclusive', []))
    labels = []
    for code in sorted(codes):
        if code in expired: labels.append((code, 'expired'))
        elif code in ineligible: labels.append((code, 'ineligible'))
        elif code in exclusive: labels.append((code, 'exclusive'))
        elif code not in applied: labels.append((code, 'unknown'))
    higher = bool(old and old.basis == 'unit' and type(old.price_vnd) is int
                  and type(result.get('final_price_vnd')) is int and result['final_price_vnd'] > old.price_vnd)
    worse = bool(old and worse_terms(old.promo_terms, quote_terms(result)))
    return labels, higher, worse


def followup_answer_complete(state, task, answer):
    """Task completeness only; factual verification remains in existing guardrails."""
    text = _search_text(answer)
    if task.kind == 'none':
        return True
    if task.kind == 'policy':
        from app.agent.guardrails.claims import assertion_text
        from app.agent.guardrails.policy_grounding import policy_clarification_or_refusal
        if (not assertion_text(answer).strip(' .!?;\n')
                or policy_clarification_or_refusal(answer)):
            return True
        if (re.search(r'phi (?:giao hang|van chuyen|ship)', _search_text(task.policy_query or ''))
                and not re.search(r'(?:phi|mien phi) (?:giao hang|van chuyen|ship)', text)):
            return False
        if task.missing_fields:
            return bool(re.search(r'xac minh|ma don|don nao', text)) and '?' in answer
        call = policy_call_for_task(state, task)
        result = call.get('result', {}) if call else {}
        if result.get('retrieval_status') != 'ok':
            return bool(re.search(r'chua (?:co|xac minh|tra cuu)|tam thoi', text))
        query = _search_text(task.policy_query or '')
        topic = ('bao hanh' if 'bao hanh' in query else
                 'giao lai|giao hang|van chuyen' if 'giao lai' in query else 'doi|tra|phi|chinh sach')
        if not re.search(topic, text):
            return False
        from app.agent.guardrails.policy_grounding import policy_evidence_for_answer, policy_clarification_or_refusal
        evidence = policy_evidence_for_answer(answer, [call])
        return bool(evidence and re.search(r'\d|mien phi|khong bao hanh|khong ap dung|dieu kien', text)
                    or policy_clarification_or_refusal(answer) and any(
                        row.get('applicability', {}).get('status') == 'conditional' for row in result.get('evidence', [])))
    if not task.focus_sku:
        return '?' in answer and bool(re.search(r'san pham|mau nao', text))
    call = compatible_quote(state, task.focus_sku)
    if call is None:
        return bool(re.search(r'chua xac minh|chua kiem tra', text))
    if re.search(r'ben kia|ben khac|doi thu|re hon|dat hon|chenh lech', text):
        return False  # A truthful numeric comparison still violates PB-02/PB-04.
    labels, higher, worse = offer_changes(state, task.focus_sku, call['result'])
    if (higher or worse) and not re.search(r'thay doi|cao hon|khong con|het han|khong du dieu kien|chua xac minh', text):
        return False
    if any(status == 'unknown' for _, status in labels) and 'het han' in text:
        return False
    return bool(re.search(r'quyen loi|tang|qua|mien phi|cod|bao hanh|uu dai|giam', text))
