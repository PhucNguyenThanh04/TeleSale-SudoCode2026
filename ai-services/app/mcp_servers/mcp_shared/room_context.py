import re

from app.mcp_servers.mcp_shared.commerce_rules import _search_text

ROOM_ALIASES = {
    'bedroom': ('bedroom', 'bed room', 'phong ngu'),
    'living_room': ('living room', 'living_room', 'phong khach'),
    'kitchen': ('kitchen', 'bep', 'phong bep'),
    'dining_room': ('dining room', 'dining_room', 'phong an'),
    'office': ('office', 'phong lam viec'),
    'bathroom': ('bathroom', 'phong tam'),
}


def canonical_room(scope):
    label = _search_text(scope).replace('_', ' ')
    return next((key for key, aliases in ROOM_ALIASES.items()
                 if label in {key.replace('_', ' '), *aliases}), scope)


def named_rooms(text, scopes=None):
    folded = _search_text(text).replace('_', ' ')
    result = set()
    for scope in ROOM_ALIASES if scopes is None else scopes:
        label = _search_text(scope).replace('_', ' ')
        aliases = ROOM_ALIASES.get(canonical_room(scope), (label,))
        if any(re.search(r'(?<![\w-])' + re.escape(alias.replace('_', ' ')) + r'(?![\w-])', folded)
               for alias in aliases):
            result.add(scope)
    return result
