from collections.abc import Iterable
import re

MODEL_TOOL_NAMES = {
    'catalog.search': 'catalog_search', 'inventory.check': 'inventory_check',
    'pricing.get_quote': 'pricing_get_quote', 'order.create': 'order_create',
    'pricing.quote_order': 'pricing_quote_order',
    'order.update': 'order_update', 'order.status': 'order_status',
    'schedule.callback': 'schedule_callback', 'handoff.transfer': 'handoff_transfer',
    'policy.search': 'policy_search',
}


def to_model_tool_name(canonical_name: str) -> str:
    try:
        return MODEL_TOOL_NAMES[canonical_name]
    except KeyError:
        raise ValueError('Unknown canonical tool') from None


def to_canonical_tool_name(model_name: str) -> str:
    for canonical, alias in MODEL_TOOL_NAMES.items():
        if alias == model_name:
            return canonical
    raise ValueError('Unknown model tool')


def validate_model_tool_names(canonical_names: Iterable[str]) -> None:
    aliases = list(MODEL_TOOL_NAMES.values())
    if (set(canonical_names) != set(MODEL_TOOL_NAMES)
            or len(set(aliases)) != len(aliases)
            or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name) for name in aliases)):
        raise ValueError('Invalid model tool contract')


def model_tool_instructions(text: str) -> str:
    pattern = r'(?<![\w.])(' + '|'.join(re.escape(n) for n in MODEL_TOOL_NAMES) + r')(?![\w.])'
    return re.sub(pattern, lambda match: MODEL_TOOL_NAMES[match[0]], text)
