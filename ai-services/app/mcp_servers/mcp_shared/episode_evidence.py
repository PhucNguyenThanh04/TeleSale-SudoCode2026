"""Conservative lexical grounding for optional episode proposals."""

import re


def evidence_supports(text: str, quote: str) -> bool:
    if not isinstance(text, str) or not isinstance(quote, str) or len(quote.strip()) < 8:
        return False
    value, source = text.casefold().strip(), quote.casefold().strip()
    if len(value) >= 8 and value in source:
        return True
    terms = {term for term in re.findall(r"\w+", value, flags=re.UNICODE)
             if len(term) >= 3}
    source_terms = {term for term in re.findall(r"\w+", source, flags=re.UNICODE)
                    if len(term) >= 3}
    return len(terms & source_terms) >= max(2, (len(terms) + 1) // 2)
