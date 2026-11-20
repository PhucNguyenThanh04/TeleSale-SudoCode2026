
from __future__ import annotations

import re

from speech.text.tts import prepare_tts_text


MAX_WORDS_PER_SEGMENT = 20
_NUMBER_DOT = "\ue000"


def prepare_tts_segments(text: str) -> list[str]:
    return split_tts_text(prepare_tts_text(text))


def split_tts_text(text: str) -> list[str]:
    normalized = " ".join(text.replace(_NUMBER_DOT, " ").split())
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
