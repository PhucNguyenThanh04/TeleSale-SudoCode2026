"""Conservative lexical grounding for optional episode proposals."""

import re


_SHORT_TERMS = {"vợ", "vo", "bố", "bo", "mẹ", "me", "ok"}


def _terms(value: str) -> set[str]:
    normalized = re.sub(r"\b(?:ông xã|ong xa|anh nhà|anh nha)\b", "chồng", value)
    normalized = re.sub(r"\b(?:bà xã|ba xa)\b", "vợ", normalized)
    return {
        term for term in re.findall(r"\w+", normalized, flags=re.UNICODE)
        if len(term) >= 3 or term in _SHORT_TERMS
    }


def evidence_supports(text: str, quote: str) -> bool:
    if not isinstance(text, str) or not isinstance(quote, str) or len(quote.strip()) < 8:
        return False
    value, source = text.casefold().strip(), quote.casefold().strip()
    if len(value) >= 8 and value in source:
        return True
    terms = _terms(value)
    source_terms = _terms(source)
    return bool(terms) and len(terms & source_terms) >= max(2, (len(terms) + 1) // 2)
