from __future__ import annotations

import re

from ..lexicon import spoken_terms
from ..normalize import default_lexicon, spell_acronyms
from ..textutil import clean
from ..vi_numbers import spell_numbers

_MONEY = re.compile(r"(?<![\w.,])(\d{7,})(?=\s*(?:đồng|vnđ|vnd|đ|₫)(?!\w))", re.I)


def respell(text: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return text
    lowered = {key.lower(): value for key, value in mapping.items()}
    alternatives = "|".join(re.escape(key) for key in sorted(lowered, key=len, reverse=True))
    return re.sub(rf"(?<!\w)({alternatives})(?!\w)",
                  lambda match: lowered[match.group(0).lower()], text, flags=re.IGNORECASE)


def prepare_tts_text(text: str, *, pronounce: dict[str, str] | None = None) -> str:
    text = _MONEY.sub(lambda match: f"{int(match.group()):,}".replace(",", "."), clean(text))
    spoken = spoken_terms(spell_numbers(text), default_lexicon())
    return respell(spell_acronyms(spoken), pronounce or {})
