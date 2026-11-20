from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .lexicon import DEFAULT_LEXICON, Lexicon, canonicalize, load_lexicon, spoken_terms
from .textutil import btc_norm, clean
from .vi_numbers import itn, spell_numbers

_RULE_FILES = ("lexicon.py", "normalize.py", "vi_numbers.py", "textutil.py", "entities.py")

_LETTER_NAMES = {
    "A": "a", "B": "bê", "C": "xê", "D": "đê", "E": "e", "F": "ép", "G": "giê", "H": "hát", "I": "i",
    "J": "gi", "K": "ca", "L": "eo", "M": "em", "N": "en", "O": "ô", "P": "pê", "Q": "quy", "R": "e rờ",
    "S": "ét", "T": "tê", "U": "u", "V": "vê", "W": "vê kép", "X": "ích", "Y": "i dài", "Z": "dét",
}
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,5}\b")


@dataclass(frozen=True)
class Normalized:
    raw: str
    canonical: str
    written: str
    spoken: str


@lru_cache(maxsize=1)
def default_lexicon() -> Lexicon:
    return load_lexicon()


def rules_fingerprint() -> dict[str, str]:
    def read(path: Path) -> bytes:
        return path.read_bytes().replace(b"\r\n", b"\n")

    lexicon_bytes = read(Path(DEFAULT_LEXICON))
    rules = hashlib.sha256(lexicon_bytes)
    for name in _RULE_FILES:
        rules.update(read(Path(__file__).with_name(name)))
    return {"lexicon_sha256": hashlib.sha256(lexicon_bytes).hexdigest(), "rules_sha256": rules.hexdigest()}


def spell_acronyms(text: str) -> str:
    return _ACRONYM_RE.sub(lambda m: " ".join(_LETTER_NAMES[ch] for ch in m.group(0)), text)


def normalize_text(raw: str, lexicon: Lexicon | None = None) -> Normalized:
    lexicon = lexicon or default_lexicon()
    canonical = canonicalize(clean(raw), lexicon)
    written = itn(canonical, lexicon.brand_tokens)
    spoken = btc_norm(spell_acronyms(spoken_terms(spell_numbers(canonical), lexicon)))
    return Normalized(raw, canonical, written, spoken)
