"""Split TTS input at periods or after 20 whitespace-delimited words."""

from __future__ import annotations

import re


MAX_WORDS_PER_SEGMENT = 20


def split_tts_text(text: str) -> list[str]:
    normalized = " ".join(text.split())
    segments: list[str] = []
    for match in re.finditer(r"[^.]+(?:\.|$)", normalized):
        clause = match.group().strip()
        words = clause.rstrip(".").split()
        for start in range(0, len(words), MAX_WORDS_PER_SEGMENT):
            chunk = " ".join(words[start:start + MAX_WORDS_PER_SEGMENT])
            if start + MAX_WORDS_PER_SEGMENT >= len(words) and clause.endswith("."):
                chunk += "."
            segments.append(chunk)
    return segments
