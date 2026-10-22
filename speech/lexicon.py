"""Từ điển Việt-Anh cho hội thoại telesale.

Hai việc:
1. ``canonicalize``: gom biến thể ASR ("e pia", "ê pia", "air pure", "pờ rô") về dạng chuẩn ("AirPure", "Pro").
2. ``spoken_terms``: đổi dạng chuẩn sang dạng nói mà ground truth BTC dùng ("AirPure" → "e pia").

Dữ liệu nằm trong ``lexicon.json``; trường ``source`` ghi mức tin cậy: ``btc_gt`` (có trong ground truth
BTC), ``btc_sample`` (có trong public sample), ``guess`` (nhóm tự đoán, cần nghe audio thật để kiểm).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .textutil import detokenize, fold, tokenize

DEFAULT_LEXICON = Path(__file__).with_name("lexicon.json")

# Âm đầu dễ nhầm khi ASR phiên âm từ tiếng Anh/tên riêng: "kha rô phi" ~ "ka rô phi" ~ "ca rô phi".
_ONSETS = (("ngh", "ng"), ("gh", "g"), ("ph", "f"), ("kh", "k"), ("qu", "kw"), ("gi", "z"), ("tr", "ch"),
           ("ch", "ch"), ("c", "k"), ("q", "k"), ("d", "z"), ("r", "z"), ("x", "s"), ("v", "z"))


def phonetic_key(token: str) -> str:
    key = fold(token)
    for src, dst in _ONSETS:
        if key.startswith(src):
            key = dst + key[len(src):]
            break
    if key.endswith("ch"):
        key = key[:-2] + "k"
    elif key.endswith("c"):
        key = key[:-1] + "k"
    return key


@dataclass(frozen=True)
class Rule:
    canonical: str
    prev: re.Pattern | None = None
    next: re.Pattern | None = None
    window: int = 1


@dataclass(frozen=True)
class Lexicon:
    entries: tuple[dict, ...]
    single: dict[str, tuple[Rule, ...]]               # biến thể một token, so khớp chữ thường giữ dấu
    multi: dict[tuple[str, ...], tuple[Rule, ...]]    # biến thể nhiều token, so khớp chữ thường giữ dấu
    phonetic: dict[tuple[str, ...], tuple[Rule, ...]]  # biến thể nhiều token của mục ``fuzzy``: bỏ dấu + gộp âm đầu
    spoken: dict[tuple[str, ...], str]                 # token dạng chuẩn (chữ thường) → dạng nói
    max_len: int
    brand_tokens: frozenset[str]


def _add(table: dict, key: tuple | str, rule: Rule) -> None:
    rules = table.get(key, ())
    if rule not in rules:
        table[key] = rules + (rule,)


def build_lexicon(data: dict) -> Lexicon:
    single: dict[str, tuple[Rule, ...]] = {}
    multi: dict[tuple[str, ...], tuple[Rule, ...]] = {}
    phonetic: dict[tuple[str, ...], tuple[Rule, ...]] = {}
    spoken: dict[tuple[str, ...], str] = {}
    brand_tokens: set[str] = set()
    max_len = 1
    entries = tuple(data["entries"])
    for entry in entries:
        canonical = entry["canonical"]
        rule = Rule(canonical)
        canonical_tokens = tokenize(canonical)
        # Viết tắt toàn chữ hoa chỉ đổi sang dạng nói khi đúng chữ hoa ("RO" → "rô", nhưng "rủi ro" giữ nguyên).
        acronym = canonical.isupper()
        spoken[tuple(t if acronym else t.lower() for t in canonical_tokens)] = entry.get("spoken", canonical.lower())
        if entry.get("type") == "brand":
            brand_tokens.update(fold(t) for t in canonical_tokens)
        own = [canonical] if entry.get("match_canonical", True) else []
        variants = [(v, rule) for v in [*own, *entry.get("variants", [])]]
        for ctx in entry.get("context_variants", []):
            variants.append((ctx["variant"], Rule(
                canonical,
                re.compile(ctx["prev"]) if ctx.get("prev") else None,
                re.compile(ctx["next"]) if ctx.get("next") else None,
                int(ctx.get("window", 1)),
            )))
        for variant, variant_rule in variants:
            tokens = tokenize(variant)
            if not tokens:
                continue
            max_len = max(max_len, len(tokens))
            if len(tokens) == 1:
                _add(single, tokens[0].lower(), variant_rule)
                continue
            _add(multi, tuple(t.lower() for t in tokens), variant_rule)
            if entry.get("fuzzy"):
                _add(phonetic, tuple(phonetic_key(t) for t in tokens), variant_rule)
    return Lexicon(entries, single, multi, phonetic, spoken, max_len, frozenset(brand_tokens))


def load_lexicon(path: str | Path | None = None) -> Lexicon:
    with open(path or DEFAULT_LEXICON, encoding="utf-8") as fh:
        return build_lexicon(json.load(fh))


def _context_ok(rule: Rule, low: list[str], start: int, length: int) -> bool:
    if rule.next is not None:
        nxt = low[start + length] if start + length < len(low) else ""
        if not rule.next.search(nxt):
            return False
    if rule.prev is not None:
        window = low[max(0, start - rule.window):start]
        if not any(rule.prev.search(tok) for tok in window):
            return False
    return True


def canonicalize(text: str, lexicon: Lexicon) -> str:
    tokens = tokenize(text)
    low = [t.lower() for t in tokens]
    keys = [phonetic_key(t) for t in tokens]
    out: list[str] = []
    i, n = 0, len(tokens)
    while i < n:
        for length in range(min(lexicon.max_len, n - i), 0, -1):
            if length == 1:
                candidates = lexicon.single.get(low[i], ())
            else:
                candidates = (lexicon.multi.get(tuple(low[i:i + length]), ())
                              + lexicon.phonetic.get(tuple(keys[i:i + length]), ()))
            rule = next((r for r in candidates if _context_ok(r, low, i, length)), None)
            if rule is not None:
                out.append(rule.canonical)
                i += length
                break
        else:
            out.append(tokens[i])
            i += 1
    return detokenize(out)


def spoken_terms(text: str, lexicon: Lexicon) -> str:
    """Đổi các dạng chuẩn trong câu sang dạng nói; từ khác giữ nguyên."""
    tokens = tokenize(text)
    low = [t.lower() for t in tokens]
    longest = max((len(k) for k in lexicon.spoken), default=1)
    out: list[str] = []
    i, n = 0, len(tokens)
    while i < n:
        for length in range(min(longest, n - i), 0, -1):
            spoken = lexicon.spoken.get(tuple(low[i:i + length])) or lexicon.spoken.get(tuple(tokens[i:i + length]))
            if spoken is not None:
                out.append(spoken)
                i += length
                break
        else:
            out.append(tokens[i])
            i += 1
    return detokenize(out)


def hotwords(lexicon: Lexicon, limit: int = 40) -> str:
    """Danh sách dạng chuẩn đưa vào ``hotwords`` của faster-whisper (giới hạn để không chiếm hết prompt)."""
    terms: list[str] = []
    for entry in lexicon.entries:
        if entry.get("hotword") and entry["canonical"] not in terms:
            terms.append(entry["canonical"])
    return ", ".join(terms[:limit])
