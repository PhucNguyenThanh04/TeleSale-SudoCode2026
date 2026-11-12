"""Resolve spoken product references from catalog metadata, never matching prices."""
import re
from app.mcp_servers.mcp_shared.commerce_rules import _search_text


def allows_short_product_name(text: str, item: dict) -> bool:
    """An accessory's compatible model name alone does not identify the accessory."""
    if not _search_text(item.get('category', '')).endswith('/phu-kien'):
        return True
    words = _search_text(item.get('name', '')).split()
    cue = ' '.join(words[:2] if words[:1] == ['bo'] else words[:1])
    return bool(cue and re.search(r'(?<!\w)' + re.escape(cue) + r'(?!\w)', _search_text(text)))


def resolve_claim_skus(text: str, calls: list[dict], *, focus_sku: str | None = None) -> set[str]:
    folded = _search_text(text)
    items = {item['sku']: item for call in calls if call.get('name') == 'catalog.search'
             and 'error' not in call.get('result', {})
             for item in call['result'].get('items', []) if isinstance(item, dict) and item.get('sku')}
    known = set(items)
    known.update(v['variant_sku'] for item in items.values() for v in item.get('variants', [])
                 if isinstance(v, dict) and v.get('variant_sku'))
    known.update(c.get('args', {}).get('sku') for c in calls
                 if c.get('name') in {'pricing.get_quote', 'inventory.check'})
    def named(label):
        return bool(label and re.search(r'(?<![\w-])' + re.escape(_search_text(label)) + r'(?![\w-])', folded))
    explicit = {sku for sku in known if sku and named(sku)}
    if explicit:
        return explicit
    aliases = {}
    for sku, item in items.items():
        words = _search_text(item.get('name', '')).split()
        starts = range(max(1, len(words) - 1)) if allows_short_product_name(text, item) else range(1)
        for start in starts:
            label = ' '.join(words[start:])
            if label:
                aliases.setdefault(label, set()).add(sku)
        if allows_short_product_name(text, item) and not (item.get('attributes') or {}).get('bundle_of'):
            for word in item.get('name', '').split()[1:]:
                if len(word) >= 3 and word[0].isupper() and word.casefold() not in {'pro', 'lite', 'mini', 'max', 'plus', 'ultra'}:
                    aliases.setdefault(_search_text(word), set()).add(sku)
    matches = [(label, owners) for label, owners in aliases.items() if named(label)]
    parents = set().union(*(owners for label, owners in matches
                           if not any(label != other and label in other for other, _ in matches))) if matches else set()
    if not parents:
        return {focus_sku} if focus_sku else set()
    result = set()
    size = re.search(r'\bsize\s*(\d+|xs|s|m|l|xl|xxl)\b', folded)
    color = re.search(r'\bmau\s+(den|trang|xam|do|xanh|navy|be)\b', folded)
    for parent in parents:
        variants = items[parent].get('variants') or []
        if not variants:
            result.add(parent)
            continue
        selected = [v for v in variants if isinstance(v, dict)
                    and (not size or _search_text(str(v.get('size'))) == size[1])
                    and (not color or _search_text(str(v.get('color', ''))) == color[1])]
        if size or color:
            result.update(v['variant_sku'] for v in selected if v.get('variant_sku'))
        elif focus_sku and any(v.get('variant_sku') == focus_sku for v in variants):
            result.add(focus_sku)
        else:
            # Parent quotes remain valid, but cannot pick one of several variants.
            result.add(parent)
            result.update(v['variant_sku'] for v in selected if v.get('variant_sku'))
    return result
