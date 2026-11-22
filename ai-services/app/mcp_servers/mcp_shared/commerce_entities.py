from app.mcp_servers.mcp_shared.commerce_evidence import CATALOG_TOOLS
import re
from app.mcp_servers.mcp_shared.commerce_rules import _search_text


def variant_option_values(text: str, variants: list[dict], key: str) -> set[str]:
    cue = r'\b(?:size|co|kich co)' if key == 'size' else r'\bmau'
    matches = [(m.start(), m.end(), _search_text(str(v[key])))
               for v in variants if isinstance(v, dict) and v.get(key) is not None
               for m in re.finditer(cue + r'\s+' + re.escape(_search_text(str(v[key])))
                                    + r'(?![\w-]|[.,]\d)', _search_text(text))]
    return {value for start, end, value in matches
            if not any(a == start and b > end for a, b, _ in matches)}


def resolve_claim_skus(text: str, calls: list[dict], *, focus_sku: str | None = None) -> set[str]:
    folded = _search_text(text)
    items = {item['sku']: item for call in calls if call.get('name') in CATALOG_TOOLS
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
    matches = [(match.start(), match.end(), sku)
               for sku,item in items.items() if item.get('name')
               for match in re.finditer(r'(?<![\w-])'+re.escape(_search_text(item['name']))+r'(?![\w-])',folded)]
    parents = {sku for start,end,sku in matches
               if not any(a<=start and b>=end and b-a>end-start for a,b,_ in matches)}
    if not parents:
        return {focus_sku} if focus_sku else set()
    result = set()
    for parent in parents:
        variants = items[parent].get('variants') or []
        if not variants:
            result.add(parent)
            continue
        options = {}
        for key in ('size', 'color'):
            values = variant_option_values(text, variants, key)
            if values:
                options[key] = values
        selected = [v for v in variants if isinstance(v, dict)
                    and all(_search_text(str(v.get(key, ''))) in values for key, values in options.items())]
        if options:
            result.update(v['variant_sku'] for v in selected if v.get('variant_sku'))
        elif focus_sku and any(v.get('variant_sku') == focus_sku for v in variants):
            result.add(focus_sku)
        else:
            result.add(parent)
            result.update(v['variant_sku'] for v in selected if v.get('variant_sku'))
    return result
