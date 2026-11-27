from copy import deepcopy
import hashlib
import json

CATALOG_TOOLS = frozenset({'catalog.search', 'catalog.get_details'})
COMMERCIAL_TOOLS = CATALOG_TOOLS | {'pricing.get_quote', 'pricing.quote_order', 'inventory.check', 'order.preview_update', 'policy.search'}


def successful(call: dict) -> bool:
    result = call.get('result')
    return (isinstance(result, dict) and 'error' not in result
            and result.get('ok') is not False and result.get('success') is not False)


def _bound(call, state):
    request = state.get('request')
    for field, expected in (('customer_id', state.get('customer_id')),
                            ('session_id', str(getattr(request, 'session_id', '')))):
        if field in call and str(call[field]) != str(expected):
            return False
    return True


def _signature(args):
    return json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)


def quote_context_hash(args: dict) -> str:
    return hashlib.sha256(_signature({key: args.get(key) for key in
        ('customer_phone', 'address', 'basket_skus')}).encode()).hexdigest()


def quote_context_matches(call: dict, args: dict) -> bool:
    if call.get('quote_context_hash'):
        return call['quote_context_hash'] == quote_context_hash(args)
    return all(call.get('args', {}).get(key) == args.get(key)
               for key in ('customer_phone', 'address', 'basket_skus'))


def build_commerce_evidence(state: dict, *, args: dict | None = None) -> list[dict]:
    current = [c for c in state.get('tool_calls', []) if isinstance(c, dict) and _bound(c, state)]
    prior = [c for c in state.get('session_tool_calls', []) if isinstance(c, dict) and _bound(c, state)]
    observations = [*prior, *current]
    completed = [i for i, call in enumerate(prior)
                 if isinstance(call, dict) and _bound(call, state)
                 and call.get('name') == 'order.create'
                 and call.get('result', {}).get('status') == 'created']
    quote_barrier = max(completed, default=-1)
    latest = {}
    conflicts = set()
    for index, call in enumerate(observations):
        name = call.get('name')
        if name not in COMMERCIAL_TOOLS:
            continue
        if name in {'pricing.get_quote', 'pricing.quote_order'} and index <= quote_barrier:
            continue
        proposed = call.get('args') or {}
        key = (name, _signature(proposed) if name in CATALOG_TOOLS | {'order.preview_update', 'policy.search', 'pricing.get_quote'} else proposed.get('sku'))
        previous = latest.get(key)
        same_order = (previous and call.get('observation_order') is not None
                      and call['observation_order'] == previous[1].get('observation_order'))
        if same_order:
            if call.get('result') != previous[1].get('result'):
                conflicts.add(key)
        else:
            conflicts.discard(key)
        latest[key] = (index, call)
    request = state.get('request')
    on = getattr(request, 'on', None)
    on = on.isoformat() if hasattr(on, 'isoformat') else str(on or '')
    desired_qty = (args or {}).get('qty')
    selected = []
    for key, (index, call) in latest.items():
        if key in conflicts or not successful(call):
            continue
        name = call['name']
        proposed, result = call.get('args') or {}, call['result']
        if name not in CATALOG_TOOLS:
            if name == 'policy.search':
                if on and (index < len(prior) or proposed.get('on') is not None) and proposed.get('on') != on:
                    continue
            elif on and proposed.get('on') != on:
                continue
            if args and args.get('on') and args['on'] != proposed.get('on'):
                continue
            if name not in {'order.preview_update', 'policy.search'}:
                if result.get('sku', proposed.get('sku')) != proposed.get('sku'):
                    continue
                if args and args.get('sku') and args['sku'] != proposed.get('sku'):
                    continue
            if name == 'pricing.get_quote':
                if desired_qty is not None and proposed.get('qty', 1) != desired_qty:
                    continue
                if args is not None and any(proposed.get(k) != args.get(k)
                                            for k in ('address', 'basket_skus')):
                    continue
        selected.append((index, deepcopy(call)))
    catalog_barriers = {}
    for index, call in enumerate(observations):
        if call.get('name') in CATALOG_TOOLS:
            sku = (call.get('args') or {}).get('sku')
            if sku:
                catalog_barriers[sku] = index
            for item in (call.get('result') or {}).get('items', []) or []:
                if isinstance(item, dict) and item.get('sku'):
                    catalog_barriers[item['sku']] = index
    for index, call in selected:
        if call['name'] in CATALOG_TOOLS and isinstance(call['result'].get('items'), list):
            call['result']['items'] = [item for item in call['result']['items']
                if isinstance(item, dict) and catalog_barriers.get(item.get('sku'), index) <= index]
    selected.extend((i, deepcopy(call)) for i, call in enumerate(prior)
                    if call.get('name') == 'order.status' and successful(call))
    selected.extend((len(prior) + i, deepcopy(call)) for i, call in enumerate(current)
                    if isinstance(call, dict) and call.get('name') not in COMMERCIAL_TOOLS
                    and _bound(call, state))
    return [call for _, call in sorted(selected, key=lambda item: item[0])]
