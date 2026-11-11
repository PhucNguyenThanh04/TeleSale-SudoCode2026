"""Read-only commercial evidence selection from runtime-owned session observations.

No customer consent is inferred here. Never append this view to the tool trace.
"""
from copy import deepcopy
import json
import re
from app.mcp_servers.mcp_shared.commerce_rules import _search_text

COMMERCIAL_TOOLS = frozenset({'catalog.search', 'pricing.get_quote', 'pricing.quote_order', 'inventory.check'})


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
    # Missing metadata is allowed only because these lists are owned/bound by runtime.
    return True


def _signature(args):
    return json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)


def current_customer_address(state: dict) -> str | None:
    """Effective explicit address/region, retained only with customer-source proof."""
    request = state.get('request')
    raw = getattr(request, 'text', '')
    pattern = r'(?i)(?:địa chỉ|dia chi)\s*:\s*([^\n.!?]+)'
    match = re.search(pattern, raw)
    if match:
        return match.group(1).strip()
    speech = [(str(t.get('source_turn_id', t.get('turn_id', ''))),
               t.get('customer', t.get('customer_text', ''))) for t in state.get('history', [])]
    speech.append((str(getattr(request, 'client_msg_id', '')), raw))
    current = state.get('tool_calls', [])
    calls = [c for c in [*state.get('session_tool_calls', []), *current]
             if isinstance(c, dict) and c.get('name') in {'pricing.get_quote', 'pricing.quote_order'} and _bound(c, state)]
    for tid, text in reversed(speech):
        folded = _search_text(text)
        if not re.search(r'\bo\b|dia chi|giao den', folded):
            continue
        # An unresolved change/revocation cannot revive the previous address.
        if re.search(r'\b(?:khong|chua)\s+(?:con\s+)?(?:o|giao)|\bneu\b|\bdoi\s+(?:dia chi|noi o|khu vuc)', folded):
            return None
        for call in reversed(calls):
            source = call.get('source_turn_id')
            if str(source) != tid and not (source is None and call in current
                                          and tid == str(getattr(request, 'client_msg_id', ''))):
                continue
            address = call.get('args', {}).get('address')
            if (isinstance(address, str) and address.strip() and '[' not in address
                    and re.search(r'(?<!\w)' + re.escape(_search_text(address)) + r'(?!\w)', folded)):
                return address
        if re.search(r'dia chi|giao den|\b(?:anh|chi|toi|minh|a|e|em)\s+o\b', folded):
            return None  # A newer location without matching proof invalidates the old one.
    return None


def build_commerce_evidence(state: dict, *, args: dict | None = None) -> list[dict]:
    """Latest compatible reads + current noncommercial calls, without mutating either list."""
    current = state.get('tool_calls', [])
    prior = state.get('session_tool_calls', [])
    observations = [c for c in [*prior, *current] if isinstance(c, dict) and _bound(c, state)]
    latest = {}
    conflicts = set()
    for index, call in enumerate(observations):
        name = call.get('name')
        if name not in COMMERCIAL_TOOLS:
            continue
        proposed = call.get('args') or {}
        key = (name, _signature(proposed) if name == 'catalog.search' else proposed.get('sku'))
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
    quantities = re.findall(r'(?<!\d)(\d+)\s*(?:chiec|cai|doi|bo|san pham)\b',
                            _search_text(state.get('safe_text', '')))
    desired_qty = (args or {}).get('qty', int(quantities[0]) if len(set(quantities)) == 1 else None)
    selected = []
    for key, (index, call) in latest.items():
        if key in conflicts or not successful(call):
            continue
        name = call['name']
        proposed, result = call.get('args') or {}, call['result']
        if name != 'catalog.search':
            if on and proposed.get('on') != on:
                continue
            if args and args.get('on') and args['on'] != proposed.get('on'):
                continue
            if result.get('sku', proposed.get('sku')) != proposed.get('sku'):
                continue
            if args and args.get('sku') and args['sku'] != proposed.get('sku'):
                continue
            if name == 'pricing.get_quote':
                address = current_customer_address(state)
                if address is not None and proposed.get('address') != address:
                    continue
                if desired_qty is not None and proposed.get('qty', 1) != desired_qty:
                    continue
                if args is not None and any(proposed.get(k) != args.get(k)
                                            for k in ('address', 'basket_skus')):
                    continue
        selected.append((index, deepcopy(call)))
    # A later lookup for a SKU replaces earlier metadata for that SKU even if empty/failed.
    catalog_barriers = {}
    for index, call in enumerate(observations):
        if call.get('name') == 'catalog.search':
            sku = (call.get('args') or {}).get('sku')
            if sku:
                catalog_barriers[sku] = index
            for item in (call.get('result') or {}).get('items', []) or []:
                if isinstance(item, dict) and item.get('sku'):
                    catalog_barriers[item['sku']] = index
    for index, call in selected:
        if call['name'] == 'catalog.search' and isinstance(call['result'].get('items'), list):
            call['result']['items'] = [item for item in call['result']['items']
                if isinstance(item, dict) and catalog_barriers.get(item.get('sku'), index) <= index]
    selected.extend((len(prior) + i, deepcopy(call)) for i, call in enumerate(current)
                    if isinstance(call, dict) and call.get('name') not in COMMERCIAL_TOOLS
                    and _bound(call, state))
    return [call for _, call in sorted(selected, key=lambda item: item[0])]
