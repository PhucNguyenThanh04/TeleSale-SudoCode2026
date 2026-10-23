"""Tách token, gấp dấu và chuẩn hóa chuỗi theo đúng luật chấm WER của BTC."""
from __future__ import annotations

import re
import unicodedata

# Số có dấu phân cách ("5,2", "5.200.000") giữ thành một token; "Lock&Lock", "OD312456", "m²" cũng là một token.
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
    """NFC, bỏ gạch nối giữa hai chữ cái ("e-pia" → "e pia"), gộp khoảng trắng; giữ chữ hoa và dấu câu."""
    text = unicodedata.normalize("NFC", text)
    text = _HYPHEN_IN_WORD.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt, đ → d. Dùng để so khớp không phụ thuộc dấu."""
    text = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def btc_norm(text: str) -> str:
    """Giống hàm ``norm`` trong ``wer_cer`` của reference_eval.py: lowercase, NFC, bỏ dấu câu, gộp khoảng trắng."""
    text = unicodedata.normalize("NFC", text.lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()
