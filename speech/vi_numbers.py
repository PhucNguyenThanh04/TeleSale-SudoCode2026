"""Số tiếng Việt theo hai chiều.

* TN (``spell_numbers``): chữ số → chữ, ra **dạng nói** để so WER với ground truth BTC
  ("25m2" → "hai mươi lăm mét vuông", "0917223456" → đọc từng chữ số).
* ITN (``itn``): chữ → chữ số, ra **dạng viết** cho agent và trích entity
  ("năm triệu hai trăm nghìn" → "5,2 triệu", "ba năm" → "3 năm" chứ không phải 35).

Quy ước đọc theo ``asr/ground_truth.json``: "hai mươi mốt", "hai mươi lăm", "mười lăm",
"một trăm linh năm", "năm triệu hai trăm nghìn", số điện thoại đọc từng chữ số.
"""
from __future__ import annotations

import re

from .textutil import detokenize, fold, tokenize

DIGIT_WORDS = ("không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín")


# ---------------------------------------------------------------------------
# Chữ số → chữ
# ---------------------------------------------------------------------------

def _triple_words(n: int, full: bool) -> list[str]:
    """0 < n < 1000. ``full``: nhóm không đứng đầu nên đọc đủ "không trăm", "linh"."""
    hundreds, rest = divmod(n, 100)
    tens, unit = divmod(rest, 10)
    words: list[str] = []
    if hundreds or full:
        words += [DIGIT_WORDS[hundreds], "trăm"]
    if tens == 0:
        if unit:
            if hundreds or full:
                words.append("linh")
            words.append(DIGIT_WORDS[unit])
    elif tens == 1:
        words.append("mười")
        if unit:
            words.append("lăm" if unit == 5 else DIGIT_WORDS[unit])
    else:
        words += [DIGIT_WORDS[tens], "mươi"]
        if unit == 1:
            words.append("mốt")
        elif unit == 5:
            words.append("lăm")
        elif unit:
            words.append(DIGIT_WORDS[unit])
    return words


def _scale_words(group_index: int) -> list[str]:
    tier, rest = divmod(group_index, 3)
    words = [("", "nghìn", "triệu")[rest]] if rest else []
    return words + ["tỷ"] * tier


def number_to_words(n: int) -> str:
    """5200000 → "năm triệu hai trăm nghìn"; nhóm 0 ở cuối được bỏ, nhóm 0 ở giữa đọc "không nghìn"
    (1000500 → "một triệu không nghìn năm trăm", tránh nhầm với "một triệu năm trăm" = 1,5 triệu)."""
    if n < 0:
        return "âm " + number_to_words(-n)
    if n == 0:
        return "không"
    groups: list[int] = []
    while n:
        n, rest = divmod(n, 1000)
        groups.append(rest)
    top = len(groups) - 1
    lowest = min(i for i, group in enumerate(groups) if group)
    words: list[str] = []
    for index in range(top, -1, -1):
        if groups[index]:
            words += _triple_words(groups[index], full=index != top)
            words += _scale_words(index)
        elif index > lowest:
            words += ["không", *_scale_words(index)]
    return " ".join(words)


def digits_to_words(digits: str) -> str:
    return " ".join(DIGIT_WORDS[int(ch)] for ch in digits if ch.isdigit())


_DIGITWISE_MIN_LEN = 7


def _int_words(digits: str) -> str:
    """Số có số 0 đứng đầu (mã, số điện thoại) hoặc chuỗi ≥ 7 chữ số viết liền đọc từng chữ số; còn lại đọc như số đếm.

    Số đếm lớn theo chính tả tiếng Việt được viết có dấu phân cách hàng nghìn ("5.490.000"), nên chuỗi dài viết liền
    là mã định danh (số điện thoại thiếu đầu số, số tài khoản…). Mã 6 chữ số như OD487215 vẫn đọc như số đếm theo BTC.
    """
    if (len(digits) > 1 and digits.startswith("0")) or len(digits) >= _DIGITWISE_MIN_LEN:
        return digits_to_words(digits)
    return number_to_words(int(digits))


def _decimal_words(whole: str, frac: str) -> str:
    return f"{number_to_words(int(whole))} phẩy {_int_words(frac)}"


_SCALE_VALUE = {"nghìn": 10**3, "ngàn": 10**3, "triệu": 10**6, "tỷ": 10**9, "tỉ": 10**9}
_UNIT_SPOKEN = {
    "m2": "mét vuông", "m²": "mét vuông", "ml": "mi li lít", "kg": "ki lô gam", "km": "ki lô mét",
    "cm": "xen ti mét", "mm": "mi li mét", "l": "lít", "tr": "triệu", "k": "nghìn", "đ": "đồng",
    "₫": "đồng", "vnđ": "đồng", "vnd": "đồng", "%": "phần trăm", "m": "mét",
}
_NUM = r"\d+(?:[.,]\d+)*"
_UNIT_RE = re.compile(rf"(?<![\w.,])({_NUM})\s*(m2|m²|ml|kg|km|cm|mm|tr|vnđ|vnd|l|k|đ|₫|%|m)(?![\w²])", re.I)
_HOUR_RE = re.compile(r"(?<![\w.,])(\d{1,2})h(\d{2})?(?!\w)", re.I)
_PHONE_RE = re.compile(r"(?<![\w.,])(?:\+84|0)(?:[ .-]?\d){8,10}(?![\w])")
_DATE_RE = re.compile(r"(?<![\w/.,])(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?(?![\w/])")
_RANGE_RE = re.compile(r"(?<![\w.,/])(\d+)\s*[-–]\s*(\d+)(?![\w.,/]?\d)")
# Chuỗi ≥3 số nối gạch ("RO 1-2-3") là tên/mã đọc từng số, không phải khoảng "từ … đến …".
_CHAIN_RE = re.compile(r"(?<![\w.,/])\d+(?:\s*[-–]\s*\d+){2,}(?![\w.,/]?\d)")
_SCALED_DECIMAL_RE = re.compile(r"(?<![\w.,])(\d+)[,.](\d{1,2})\s*(triệu|tỷ|tỉ|nghìn|ngàn)(?!\w)", re.I)
_THOUSANDS_RE = re.compile(r"(?<![\w.,])\d{1,3}(?:([.,])\d{3})(?:\1\d{3})*(?![\w]|[.,]\d)")
_DECIMAL_RE = re.compile(r"(?<![\w.,])(\d+)[,.](\d+)(?![\w]|[.,]\d)")
_ORDINAL_RE = re.compile(r"\b(thứ)\s+(\d+)\b", re.I)
_LETTER_DIGIT_RE = re.compile(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])")
_INT_RE = re.compile(r"\d+")


def _phone_words(match: re.Match) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+84"):
        return "cộng tám tư " + digits_to_words(digits[2:])
    return digits_to_words(digits)


def _date_words(match: re.Match) -> str:
    day, month, year = match.group(1), match.group(2), match.group(3)
    if not (1 <= int(day) <= 31 and 1 <= int(month) <= 12):
        return match.group(0)
    text = f"{number_to_words(int(day))} tháng {number_to_words(int(month))}"
    return text + (f" năm {number_to_words(int(year))}" if year else "")


def _scaled_decimal_words(match: re.Match) -> str:
    whole, frac, scale_word = match.group(1), match.group(2), match.group(3).lower()
    if len(frac) == 1:
        # Cách nói tắt: "5,7 triệu" ↔ "năm triệu bảy".
        return f"{number_to_words(int(whole))} {scale_word} {DIGIT_WORDS[int(frac)]}"
    value = round(float(f"{whole}.{frac}") * _SCALE_VALUE[scale_word])
    return number_to_words(value)


def _ordinal_words(match: re.Match) -> str:
    n = int(match.group(2))
    return f"{match.group(1)} " + {1: "nhất", 4: "tư"}.get(n, number_to_words(n))


def spell_numbers(text: str) -> str:
    """Chuyển mọi chữ số trong câu sang chữ (dạng nói). Chữ cái và dấu câu giữ nguyên."""
    text = _UNIT_RE.sub(lambda m: f"{m.group(1)} {_UNIT_SPOKEN[m.group(2).lower()]}", text)
    text = _HOUR_RE.sub(lambda m: f"{m.group(1)} giờ" + (f" {m.group(2)}" if m.group(2) else ""), text)
    text = _PHONE_RE.sub(_phone_words, text)
    text = _DATE_RE.sub(_date_words, text)
    text = _CHAIN_RE.sub(lambda m: " ".join(re.findall(r"\d+", m.group(0))), text)
    text = _RANGE_RE.sub(lambda m: f"{m.group(1)} đến {m.group(2)}", text)
    text = _SCALED_DECIMAL_RE.sub(_scaled_decimal_words, text)
    text = _THOUSANDS_RE.sub(lambda m: number_to_words(int(re.sub(r"\D", "", m.group(0)))), text)
    text = _DECIMAL_RE.sub(lambda m: _decimal_words(m.group(1), m.group(2)), text)
    text = _ORDINAL_RE.sub(_ordinal_words, text)
    text = _LETTER_DIGIT_RE.sub(" ", text)
    return _INT_RE.sub(lambda m: _int_words(m.group(0)), text)


# ---------------------------------------------------------------------------
# Chữ → chữ số (ITN)
# ---------------------------------------------------------------------------

_DIGIT = {word: value for value, word in enumerate(DIGIT_WORDS)} | {"bẩy": 7}
_AFTER_MUOI = {"một": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4, "lăm": 5, "nhăm": 5,
               "sáu": 6, "bảy": 7, "bẩy": 7, "tám": 8, "chín": 9}  # sau "mười"; "mười năm" là 10 năm
_AFTER_MUOI_TENS = _AFTER_MUOI | {"mốt": 1}  # sau "mươi"
_COLLOQUIAL_UNIT = {"mốt": 1, "lăm": 5, "nhăm": 5}  # "bốn mốt" = 41, "hai lăm" = 25
_TAIL = {"một": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4, "năm": 5, "lăm": 5,
         "sáu": 6, "bảy": 7, "bẩy": 7, "tám": 8, "chín": 9}  # "năm triệu bảy" = 5,7 triệu
_SCALE = {"nghìn": 10**3, "ngàn": 10**3, "triệu": 10**6, "tỷ": 10**9, "tỉ": 10**9}
_LINH = {"linh", "lẻ"}
_CONTINUES = {"trăm", "mươi", "chục", "phẩy", "rưỡi"} | set(_SCALE) | set(_COLLOQUIAL_UNIT)
_SMALL_NUMBER_TOKEN = re.compile(r"\d{1,3}")

# Một từ số đứng riêng ("ba", "mười") chỉ đổi sang chữ số khi có đơn vị phía sau hoặc ngữ cảnh phía trước;
# nếu không, "ba" (bố), "năm nay", "một màng lọc" sẽ bị đổi sai.
UNIT_AFTER = frozenset({
    "mét", "m", "m2", "m²", "cm", "mm", "km", "kg", "ký", "lạng", "gam", "lít", "l", "ml", "tháng", "ngày",
    "năm", "tuần", "giờ", "tiếng", "phút", "giây", "tuổi", "lõi", "inch", "%", "phần", "độ", "đồng", "k",
    "chức",
})
CONTEXT_BEFORE = frozenset({
    "size", "cỡ", "số", "mã", "quận", "phường", "tầng", "lầu", "tháng", "ngày", "hôm", "thứ", "đợt", "bản",
})
MODEL_WORDS = frozenset({"pro", "lite", "plus", "max", "mini", "ultra", "smart", "gen", "series"})
_RANGE_WORDS = frozenset({"đến", "tới", "-", "–", "hoặc", "hay"})
_RUN2_CONTEXT = frozenset({"size", "cỡ", "số", "mã"})  # "size bốn hai" = 42
_CODE_PREFIX = frozenset({"od", "mã"})  # mã đơn đọc như số đếm nhưng viết thành dãy số


def _group(t: list[str], i: int, after_scale: bool) -> tuple[int, int] | None:
    """Đọc một nhóm 1..999 bắt đầu tại ``i`` → (giá trị, vị trí kế tiếp)."""
    n = len(t)
    if i >= n:
        return None
    if _SMALL_NUMBER_TOKEN.fullmatch(t[i]):
        return int(t[i]), i + 1
    if after_scale and t[i] in _LINH and i + 1 < n and _DIGIT.get(t[i + 1], 0) > 0:
        return _DIGIT[t[i + 1]], i + 2
    value, j = 0, i
    if j + 1 < n and t[j] in _DIGIT and t[j + 1] == "trăm":
        value, j = _DIGIT[t[j]] * 100, j + 2
        if j < n and t[j] == "rưỡi":
            return value + 50, j + 1
        if j + 1 < n and t[j] in _LINH and _DIGIT.get(t[j + 1], 0) > 0:
            return value + _DIGIT[t[j + 1]], j + 2
    if j < n and t[j] == "mười":
        value, j = value + 10, j + 1
        if j < n and t[j] in _AFTER_MUOI:
            value, j = value + _AFTER_MUOI[t[j]], j + 1
        return value, j
    digit = _DIGIT.get(t[j]) if j < n else None
    if digit and j + 1 < n and (t[j + 1] == "chục" or (t[j + 1] == "mươi" and digit >= 2)):
        value, j = value + digit * 10, j + 2
        if t[j - 1] == "mươi" and j < n and t[j] in _AFTER_MUOI_TENS:
            value, j = value + _AFTER_MUOI_TENS[t[j]], j + 1
        return value, j
    if digit and digit >= 2 and j + 1 < n and t[j + 1] in _COLLOQUIAL_UNIT:
        return value + digit * 10 + _COLLOQUIAL_UNIT[t[j + 1]], j + 2
    if j > i:
        return value, j
    if digit is not None:
        return digit, j + 1
    return None


def _cardinal(t: list[str], i: int) -> tuple[int | float, int, bool] | None:
    """Đọc một số đếm (có thể có nghìn/triệu/tỷ, phẩy, rưỡi) → (giá trị, vị trí kế tiếp, có đơn vị lớn)."""
    first = _group(t, i, after_scale=False)
    if first is None:
        return None
    value, k = first
    total, last_scale, n = 0, 0, len(t)
    while True:
        if k + 1 < n and t[k] == "phẩy" and t[k + 1] in _DIGIT:
            m, frac = k + 1, ""
            while m < n and t[m] in _DIGIT:
                frac, m = frac + str(_DIGIT[t[m]]), m + 1
            number = value + float("0." + frac)
            if m < n and t[m] in _SCALE and (not last_scale or _SCALE[t[m]] < last_scale):
                return total + round(number * _SCALE[t[m]]), m + 1, True
            if not last_scale:
                return number, m, False
            return total + value, k, True
        word = t[k] if k < n else ""
        if word in _SCALE and (not last_scale or _SCALE[word] < last_scale):
            scale = _SCALE[word]
            total, last_scale, j = total + value * scale, scale, k + 1
            if j < n and t[j] == "rưỡi":
                return total + scale // 2, j + 1, True
            if j < n and t[j] in _TAIL and (j + 1 >= n or t[j + 1] not in _CONTINUES):
                return total + _TAIL[t[j]] * scale // 10, j + 1, True
            # Whisper viết "năm triệu bảy" thành "5 triệu 7": phần đuôi là các chữ số đầu của phần lẻ (5,7 triệu).
            if (j < n and _SMALL_NUMBER_TOKEN.fullmatch(t[j])
                    and (j + 1 >= n or (t[j + 1] not in _CONTINUES and t[j + 1] not in UNIT_AFTER))):
                return total + int(t[j]) * scale // 10 ** len(t[j]), j + 1, True
            following = _group(t, j, after_scale=True)
            if following is None:
                return total, j, True
            value, k = following
            continue
        if last_scale >= 10**6 and value and word not in _SCALE:
            # "năm triệu hai trăm" trong lời nói là 5,2 triệu (bỏ chữ "nghìn").
            value *= last_scale // 1000
        return total + value, k, last_scale > 0


def _digit_run(low: list[str], i: int) -> tuple[str, int]:
    """Chuỗi từ chữ số liên tiếp ("không chín một bảy …") → (dãy số, vị trí kế tiếp)."""
    digits, j, n = "", i, len(low)
    while j < n:
        if low[j] in _DIGIT:
            digits, j = digits + str(_DIGIT[low[j]]), j + 1
        elif low[j] == "," and digits.startswith("0") and len(digits) >= 3 and j + 1 < n and low[j + 1] in _DIGIT:
            j += 1
        else:
            break
    return digits, j


def _single_ok(low: list[str], i: int, context_words: frozenset[str]) -> bool:
    if low[i] == "không":
        return False
    prev = low[i - 1] if i > 0 else ""
    nxt = low[i + 1] if i + 1 < len(low) else ""
    if nxt in UNIT_AFTER or prev in CONTEXT_BEFORE:
        return True
    if fold(prev) in context_words or prev in MODEL_WORDS or nxt in MODEL_WORDS:
        return True
    if nxt in _RANGE_WORDS:
        other = _cardinal(low, i + 2)
        return other is not None and other[1] < len(low) and low[other[1]] in UNIT_AFTER
    return False


def format_amount(value: int) -> str:
    """5200000 → "5,2 triệu"; 30000 → "30 nghìn". Số lẻ hơn hai chữ số thập phân giữ dạng số trơn."""
    for scale, word in ((10**9, "tỷ"), (10**6, "triệu"), (10**3, "nghìn")):
        if value >= scale:
            if value % (scale // 100):
                return str(value)
            whole, rest = divmod(value, scale)
            if rest == 0:
                return f"{whole} {word}"
            return f"{whole},{rest * 100 // scale:02d}".rstrip("0") + f" {word}"
    return str(value)


def _format(value: int | float, has_scale: bool, as_code: bool) -> str:
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".").replace(".", ",")
    if as_code or not has_scale:
        return str(value)
    return format_amount(value)


def itn_tokens(tokens: list[str], context_words: frozenset[str] = frozenset()) -> list[str]:
    """``context_words``: token (đã gấp dấu) cho phép đọc một chữ số đứng riêng, ví dụ tên hãng "runlite"."""
    low = [tok.lower() for tok in tokens]
    out: list[str] = []
    i, n = 0, len(tokens)
    while i < n:
        digits, run_end = _digit_run(low, i)
        if len(digits) == 11 and digits.startswith("0") and low[run_end - 1] == "không":
            digits, run_end = digits[:-1], run_end - 1  # "… năm sáu không?" là câu hỏi, không phải số thứ 11
        if len(digits) >= 3:
            out.append(digits)
            i = run_end
            continue
        if len(digits) == 2:
            prev = low[i - 1] if i > 0 else ""
            nxt = low[run_end] if run_end < n else ""
            first, second = int(digits[0]), int(digits[1])
            if prev in _RUN2_CONTEXT and not (run_end < n and low[run_end] in _CONTINUES):
                out.append(digits)
                i = run_end
                continue
            if second == first + 1 and nxt in UNIT_AFTER:  # "hai ba ngày" = 2-3 ngày
                out.append(f"{first}-{second}")
                i = run_end
                continue
        parsed = _cardinal(low, i)
        if parsed is not None:
            value, end, has_scale = parsed
            as_code = i > 0 and low[i - 1] in _CODE_PREFIX
            if _SMALL_NUMBER_TOKEN.fullmatch(low[i]) and not has_scale:
                pass  # đã là chữ số
            elif end - i >= 2 or has_scale or _single_ok(low, i, context_words):
                out.append(_format(value, has_scale, as_code))
                i = end
                continue
        out.append(tokens[i])
        i += 1
    return _merge_codes(out)


def _merge_codes(tokens: list[str]) -> list[str]:
    """"OD 312456" → "OD312456"."""
    out: list[str] = []
    for tok in tokens:
        if out and out[-1].upper() == "OD" and tok.isdigit():
            out[-1] = "OD" + tok
        else:
            out.append(tok)
    return out


def itn(text: str, context_words: frozenset[str] = frozenset()) -> str:
    return detokenize(itn_tokens(tokenize(text), context_words))
