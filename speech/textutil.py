from __future__ import annotations

import re
import unicodedata

TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)+|\w+(?:[&'’]\w+)*|[^\w\s]")
_SPACE_BEFORE = re.compile(r"\s+([,.!?;:%)\]}])")
_SPACE_AFTER = re.compile(r"([(\[{])\s+")
_HYPHEN_IN_WORD = re.compile(r"(?<=[^\W\d_])[-‐–](?=[^\W\d_])")


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text)


def detokenize(tokens: list[str]) -> str:
    text = " ".join(tokens)
    text = _SPACE_BEFORE.sub(r"\1", text)
    return _SPACE_AFTER.sub(r"\1", text)


def clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _HYPHEN_IN_WORD.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def btc_norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text.lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()
