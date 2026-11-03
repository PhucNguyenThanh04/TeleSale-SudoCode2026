"""Split TTS input at sentence periods or after 20 words."""

from __future__ import annotations

import re


MAX_WORDS_PER_SEGMENT = 20
_NUMBER_DOT = "\ue000"


def split_tts_text(text: str) -> list[str]:
    normalized = " ".join(text.replace(_NUMBER_DOT, " ").split())
    # Vietnamese prices, dates and decimals commonly contain periods. Protect a
    # period only when it is surrounded by digits, so the final period in
    # ``25.000.000. Mẫu khác...`` remains a sentence boundary.
    protected = re.sub(r"(?<=\d)\.(?=\d)", _NUMBER_DOT, normalized)
    segments: list[str] = []
    for match in re.finditer(r"[^.]+(?:\.|$)", protected):
        clause = match.group().strip()
        words = clause.rstrip(".").split()
        for start in range(0, len(words), MAX_WORDS_PER_SEGMENT):
            chunk = " ".join(words[start:start + MAX_WORDS_PER_SEGMENT])
            if start + MAX_WORDS_PER_SEGMENT >= len(words) and clause.endswith("."):
                chunk += "."
            segments.append(chunk.replace(_NUMBER_DOT, "."))
    return segments
