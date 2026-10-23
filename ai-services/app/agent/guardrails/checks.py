"""Small deterministic checks around external model input and output."""

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from app.mcp_servers.mcp_shared.pii import mask_pii
from app.constants import PROFILE_SLOT_KEYS, SLOT_SPEC_BY_KEY, TOOL_ONLY_SLOT_KEYS, Slot
from app.agent.guardrails.skus import known_skus, mentioned_skus
from app.agent.memory.decision_makers import PERSON_PATTERN


FALLBACK = "Dạ, hiện em chưa kiểm tra được thông tin này. Em sẽ nhờ nhân viên hỗ trợ mình ạ."

_STOCK = re.compile(r"(?i)\b(?:còn hàng|có hàng|sẵn hàng|hết hàng)\b")
_ORDER = re.compile(r"(?i)\bđã\s+(?:lên|tạo|đặt|chốt)\s+đơn\b")
# A digit inside an area such as "25m2 trong" must not become "2 tr".
_AMOUNT = re.compile(r"(?i)(?<!\w)(\d[\d.,]*)\s*(triệu|tr|nghìn|ngàn|k|đồng|đ|vnd|₫)")
_MILLION_SHORTHAND = re.compile(r"(?i)\b(\d{1,3})\s*tr\s*(\d{1,3})(?!\d)")
_PRICE_NUMBER = re.compile(r"(?i)\bgiá\s+(?:là\s+)?(\d[\d.,]*)")
_BARE_MONEY = re.compile(r"\b(?:\d{1,3}(?:[.,]\d{3})+|\d{6,})\b")
_DISCOUNT_CONTEXT = re.compile(r"(?i)\b(?:giảm(?:\s+giá|\s+thêm)?|khuyến mãi|ưu đãi|chiết khấu|tiết kiệm)\b")
_NEGATIVE_DISCOUNT = re.compile(
    r"(?i)\b(?:không|chưa|hết)\s+"
    r"(?:(?:có|còn|được|mã|chương\s+trình|áp\s+dụng|đang)\s+){0,4}"
    r"(?:giảm(?:\s+giá)?|khuyến mãi|ưu đãi)\b"
)
_PRICE_CONTEXT = re.compile(r"(?i)\b(?:giá(?:\s+bán)?|còn|chỉ)\b")
_COMPETITOR_CONTEXT = re.compile(r"(?i)\b(?:bên kia|bên khác|shop khác|đối thủ)\b")
_REPEATED_BUDGET = re.compile(
    r"\b(?:ngan sach|tam gia|muc gia|gioi han|toi da|duoi)\s+"
    r"(?:(?:toi da|tam|khoang|la|duoi)\s+)?"
    r"\d[\d.,]*\s*(?:trieu|tr|nghin|ngan|k|dong|d|vnd)\b"
)
_PRODUCT_FEATURE = re.compile(r"(?i)\b(?:HEPA(?:\s*H\d+)?|PM\s*2[.,]5)\b")
# Public catalog attribute names and their customer-facing expressions.
_BOOLEAN_FEATURE_ALIASES = {
    "child_safe_lock": (r"\bkhoa (?:an toan )?tre em\b",),
}
_SUPERLATIVE = re.compile(r"(?i)\b(?:phù hợp nhất|tốt nhất|hiệu quả nhất)\b")
_LEGACY_SKU_SIGNAL = re.compile(r"\bSKU-[A-Z0-9-]+\b")
_PROMOTION = re.compile(r"(?i)\b(?:khuyến mãi|giảm giá|còn giảm|được giảm|mã giảm|freeship|miễn phí (?:ship|vận chuyển))\b")
_DELIVERY = re.compile(r"(?i)\b(?:dự kiến giao|ngày giao|giao trong|giao vào|giao ngày|giao\s+\d)\b")
_POLICY = re.compile(r"(?i)\b(?:bảo hành|đổi trả|đổi size|hoàn tiền|chính sách)\b")
_INTERNAL = re.compile(r"(?i)\b(?:giá nhập|giá sàn|nhà cung cấp)\b")
_PII_KEY = re.compile(r"(?i)(?:phone|address|name|email|zalo|fb_id|cccd|bank|account|card|password|token|sdt|stk)")
_PROMO_CODE = re.compile(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b")
_ORDER_STATUS = re.compile(r"(?i)\b(?:đơn đang giao|đơn đã giao|đơn đã tạo|đã hủy đơn)\b")
_PRICE_REFERENCE = re.compile(r"(?i)\bgiá\b[^.!?]{0,40}\b(?:như hôm trước|vẫn vậy|không đổi|còn hiệu lực)\b")
_STOCK_QTY = re.compile(r"(?i)\bcòn\s+(\d+)\s+(?:cái|chiếc|sản phẩm)\b")
_ORDER_ID = re.compile(r"\bOD[A-Z0-9-]+\b")
_AREA_UNIT = r"(?:m²|m2|m\s+vuông|mét\s+vuông|met\s+vuong)"
_NUMBER_WORDS = {
    "không": 0, "một": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4,
    "năm": 5, "lăm": 5, "sáu": 6, "bảy": 7, "tám": 8, "chín": 9,
}
_AREA_NUMBER_WORD = r"(?:không|một|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|mười|mươi|trăm|linh|lẻ|chục|"
_AREA_NUMBER_WORD += r"khong|mot|bon|nam|lam|sau|bay|tam|chin|muoi|tram|le|chuc)"
_SPOKEN_AREA = re.compile(
    rf"(?i)\b({_AREA_NUMBER_WORD}(?:\s+{_AREA_NUMBER_WORD}){{0,6}})\s*{_AREA_UNIT}(?!\w)"
)


def _spoken_integer(words: str) -> int | None:
    """Parse a spoken Vietnamese room area, up to 999 m²."""
    parts = _fold_text(words).replace("chuc", "muoi").split()
    normalized = {"khong": 0, "mot": 1, "hai": 2, "ba": 3, "bon": 4,
                  "tu": 4, "nam": 5, "lam": 5, "sau": 6, "bay": 7,
                  "tam": 8, "chin": 9}
    if not parts:
        return None
    total = 0
    if len(parts) >= 2 and parts[1] == "tram" and parts[0] in normalized:
        total = normalized[parts[0]] * 100
        parts = parts[2:]
        if parts and parts[0] in {"linh", "le"}:
            parts = parts[1:]
            if len(parts) != 1 or parts[0] not in normalized:
                return None
            return total + normalized[parts[0]]
    if len(parts) >= 2 and parts[1] == "muoi" and parts[0] in normalized:
        if normalized[parts[0]] < 2:
            return None
        total += normalized[parts[0]] * 10
        parts = parts[2:]
    elif parts and parts[0] == "muoi":
        total += 10
        parts = parts[1:]
    if not parts:
        return total or None
    if len(parts) != 1 or parts[0] not in normalized:
        return None
    return total + normalized[parts[0]]


def _fold_text(value: str) -> str:
    value = value.casefold().replace("đ", "d")
    return "".join(char for char in unicodedata.normalize("NFD", value)
                   if unicodedata.category(char) != "Mn")


_ERASURE_ACTION = re.compile(r"\b(?:xoa|go|huy|loai bo)\b|\b(?:dung|khong)\s+(?:tiep tuc\s+)?(?:giu|luu)\b")
_ERASURE_SUBJECT = re.compile(r"\b(?:du lieu|thong tin|ho so)\b")
_ERASURE_OWNER = re.compile(r"\b(?:cua\s+(?:toi|anh|chi|em|minh)|ca nhan|ve\s+(?:toi|anh|chi|em|minh)|toan bo|tat ca|het)\b")
_ERASURE_SPECIFIC_INFO = re.compile(r"\bthong tin\s+(?:ve\s+)?(?:so thich|mau|size|co giay|ngan sach|dien tich phong)\b")
_ERASURE_WHOLE_RECORD = re.compile(r"\b(?:toan bo|tat ca|het)\s+(?:du lieu|thong tin|ho so)\b")
_ERASURE_DONE = re.compile(r"\bda\s+(?:duoc\s+)?(?:xoa|go|huy|loai bo|xu ly xong)\b|\b(?:xoa|go|huy)\s+(?:xong|het|hoan tat)\b|\bda\s+(?:xu ly|hoan thanh)\s+xong\s+yeu cau\s+xoa\b")
_HANDOFF_DONE = re.compile(
    r"\b(?:da|vua)\s+(?:ban giao|ket noi|noi may|chuyen may)\b"
    r"|\b(?:da|vua)\s+chuyen\b[^.!?]{0,60}\b(?:nhan vien|bo phan|tong dai|nguoi tu van)\b"
    r"|\b(?:chuyen|ban giao|ket noi|noi may)\b[^.!?]{0,50}\b(?:nhan vien|bo phan|tong dai)\b[^.!?]{0,30}\broi\b")


def customer_erasure_requested(customer_text: str) -> bool:
    """Recognize requests about the customer's whole record, not one preference."""
    folded = _fold_text(customer_text)
    subjects = list(_ERASURE_SUBJECT.finditer(folded))
    return bool(_ERASURE_ACTION.search(folded) and subjects
                and (any(subject.group() != "thong tin"
                         or not _ERASURE_SPECIFIC_INFO.match(folded, subject.start())
                         for subject in subjects)
                     or _ERASURE_WHOLE_RECORD.search(folded))
                and (_ERASURE_OWNER.search(folded)
                     or any(subject.group() in {"du lieu", "ho so"}
                            for subject in subjects)))


def _customer_erasure_completion_claim(answer: str) -> bool:
    folded = _fold_text(answer)
    for clause in re.split(r"[;.!?]|\bnhung\b|,\s*(?=(?:gio|nay|bay gio|sau do)\b)", folded):
        if (_ERASURE_DONE.search(clause) and _ERASURE_ACTION.search(clause)
                and _ERASURE_SUBJECT.search(clause)
                and not re.search(r"\b(?:chua|khong)\s+(?:duoc\s+)?(?:xoa|go|huy|xu ly)\b", clause)):
            return True
    return False


def _room_area_evidenced(value: Any, customer_text: str) -> bool:
    if type(value) is not int or value <= 0:
        return False
    if re.search(rf"(?i)\b{value}\s*{_AREA_UNIT}(?!\w)", customer_text):
        return True
    return any(_spoken_integer(match.group(1)) == value
               for match in _SPOKEN_AREA.finditer(customer_text))



def safe_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    """Remove tool-only prices and personal fields before model observation."""
    def clean(value: Any) -> Any:
        if isinstance(value, str):
            return mask_pii(value)
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {
                key: clean(item) for key, item in value.items()
                if not key.startswith("_") and key not in {"phone", "customer_phone", "address", "candidates"}
            }
        return value

    return clean(result)


def _money_amount(value: str) -> int | None:
    shorthand = _MILLION_SHORTHAND.fullmatch(value.strip())
    if shorthand:
        millions, fraction = shorthand.groups()
        return int(millions) * 1_000_000 + int(fraction) * 10 ** (6 - len(fraction))
    match = _AMOUNT.fullmatch(value.strip())
    if not match:
        return None
    digits, unit = match.groups()
    if unit.lower() in {"triệu", "tr"} and "," in digits and "." not in digits:
        number = float(digits.replace(",", "."))
    else:
        number = float(digits.replace(".", "").replace(",", ""))
    if unit.lower() in {"triệu", "tr"}:
        number *= 1_000_000
    elif unit.lower() in {"nghìn", "ngàn", "k"}:
        number *= 1_000
    return int(number)


_BUDGET_AMOUNT_FOLDED = (r"(?:\d{1,3}\s*tr\s*\d{1,3}"
                         r"|\d[\d.,]*\s*trieu\s+ruoi"
                         r"|\d[\d.,]*\s*(?:trieu|tr|cu|nghin|ngan|k|dong|d|vnd)"
                         r"|[a-z]+\s+trieu(?:\s+(?:ruoi|mot|hai|ba|bon|nam|sau|bay|tam|chin))?)")
_BUDGET_RANGE = re.compile(
    r"\b(?:tu\s+|tam\s+|khoang\s+)?(?P<low>\d[\d.,]*)\s*"
    r"(?P<low_unit>trieu|tr|cu|nghin|ngan|k|dong|d|vnd)?\s*"
    r"(?:den|[-–—])\s*(?P<high>\d[\d.,]*)\s*"
    r"(?P<high_unit>trieu|tr|cu|nghin|ngan|k|dong|d|vnd)\b")
_BUDGET_FLOOR = re.compile(
    rf"\b(?:khong\s+duoi|khong\s+thap\s+hon|toi\s+thieu|it\s+nhat)\s+"
    rf"(?:la\s+)?(?P<amount>{_BUDGET_AMOUNT_FOLDED})\b")
_BUDGET_CEILING = re.compile(
    rf"\b(?:khong\s+(?:qua|hon|vuot)|toi\s+da|duoi)\s+"
    rf"(?:la\s+)?(?P<amount>{_BUDGET_AMOUNT_FOLDED})\b")
_REPORTED_PRICE_SUBJECT = re.compile(r"\b(?:shop|cua hang|ben kia|ben khac|doi thu)\b[^.!?;,]{0,32}"
                                     r"\b(?:bao gia|gia ban|gia)\b")
_BUDGET_CUE = re.compile(r"\b(?:ngan sach|budget|muon chi|dinh chi|co the chi|chi tam|chi khoang)\b")
_PRICE_AFTER_BUDGET_CUE = re.compile(r"\b(?:gia|shop|cua hang|ben kia|ben khac|doi thu)\b")


def _folded_budget_amount(raw: str) -> int | None:
    """Parse a folded money expression without changing the existing amount parser."""
    shorthand = re.fullmatch(r"(\d{1,3})\s*tr\s*(\d{1,3})", raw)
    if shorthand:
        millions, fraction = shorthand.groups()
        return int(millions) * 1_000_000 + int(fraction) * 10 ** (6 - len(fraction))
    half = re.fullmatch(r"(\d[\d.,]*)\s*trieu\s+ruoi", raw)
    if half:
        whole = _folded_budget_amount(half.group(1) + " trieu")
        return whole + 500_000 if whole is not None else None
    number = re.fullmatch(r"(\d[\d.,]*)\s*(trieu|tr|cu|nghin|ngan|k|dong|d|vnd)", raw)
    if number:
        if number.group(2) == "cu":
            return _money_amount(number.group(1) + "triệu")
        unit = {"trieu": "triệu", "nghin": "nghìn", "ngan": "ngàn",
                "dong": "đồng", "d": "đ"}.get(number.group(2), number.group(2))
        return _money_amount(number.group(1) + unit)
    words = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5,
             "sau": 6, "bay": 7, "tam": 8, "chin": 9}
    spoken = re.fullmatch(r"([a-z]+)\s+trieu(?:\s+(ruoi|[a-z]+))?", raw)
    if spoken and spoken.group(1) in words:
        tail = spoken.group(2)
        if tail is None or tail == "ruoi" or tail in words:
            return words[spoken.group(1)] * 1_000_000 + (
                500_000 if tail == "ruoi" else words.get(tail, 0) * 100_000)
    return None


def customer_budget_floor_amounts(customer_text: str) -> set[int]:
    """Recognize stated spending floors, which budget_vnd cannot represent."""
    folded = _fold_text(customer_text)
    amounts = {amount for match in _BUDGET_FLOOR.finditer(folded)
               if (amount := _folded_budget_amount(match.group("amount"))) is not None}
    for match in _BUDGET_RANGE.finditer(folded):
        unit = match.group("low_unit") or match.group("high_unit")
        low = _folded_budget_amount(match.group("low") + unit)
        high = _folded_budget_amount(match.group("high") + match.group("high_unit"))
        if low is not None and high is not None and low <= high:
            amounts.add(low)
    return amounts


def customer_budget_amounts(customer_text: str) -> set[int]:
    """Only amounts explicitly framed as the customer's spending limit."""
    amounts: set[int] = set()
    folded = _fold_text(customer_text)
    floors = list(_BUDGET_FLOOR.finditer(folded))
    ranges = list(_BUDGET_RANGE.finditer(folded))
    for match in ranges:
        unit = match.group("low_unit") or match.group("high_unit")
        low = _folded_budget_amount(match.group("low") + unit)
        high = _folded_budget_amount(match.group("high") + match.group("high_unit"))
        if low is not None and high is not None and low <= high:
            amounts.add(high)
    # Keep separators inside 4,5 or 4.000.000 intact while bounding each cue.
    bounded = re.sub(r"(?<!\d)[,.]|[,.](?!\d)|[;!?]", "|", folded)
    for clause in re.finditer(r"[^|]+", bounded):
        for cue in _BUDGET_CUE.finditer(clause.group()):
            tail = clause.group()[cue.end():]
            money = re.search(rf"\b{_BUDGET_AMOUNT_FOLDED}\b", tail)
            if money is None or len(tail[:money.start()].split()) > 14:
                continue
            if _PRICE_AFTER_BUDGET_CUE.search(tail[:money.start()]):
                continue
            start = clause.start() + cue.end() + money.start()
            if any(floor.start("amount") <= start < floor.end("amount") for floor in floors):
                continue
            if any(price_range.start() <= start < price_range.end() for price_range in ranges):
                continue
            amount = _folded_budget_amount(money.group())
            if amount is not None:
                amounts.add(amount)
    for match in _BUDGET_CEILING.finditer(folded):
        # "khong duoi" is a floor; the trailing "duoi" is not a ceiling.
        if match.group().startswith("duoi") and re.search(r"\bkhong\s+$", folded[:match.start()]):
            continue
        clause_start = max(folded.rfind(mark, 0, match.start()) for mark in ".!?;,") + 1
        if _REPORTED_PRICE_SUBJECT.search(folded[clause_start:match.start()]):
            continue
        amount = _folded_budget_amount(match.group("amount"))
        if amount is not None:
            amounts.add(amount)
    return amounts


def _money_claims(text: str) -> list[tuple[int, str, bool]]:
    """Extract amounts and classify discount claims separately from sale prices."""
    mentions: list[tuple[int, int, int]] = []
    for match in _MILLION_SHORTHAND.finditer(text):
        amount = _money_amount(match.group())
        if amount is not None:
            mentions.append((match.start(), match.end(), amount))
    for match in _AMOUNT.finditer(text):
        if any(start < match.end() and match.start() < end for start, end, _ in mentions):
            continue
        amount = _money_amount(match.group())
        if amount is not None:
            mentions.append((match.start(), match.end(), amount))
    for match in _PRICE_NUMBER.finditer(text):
        if any(start < match.end(1) and match.start(1) < end for start, end, _ in mentions):
            continue
        mentions.append((match.start(1), match.end(1),
                         int(match.group(1).replace(".", "").replace(",", ""))))
    for match in _BARE_MONEY.finditer(text):
        if any(start < match.end() and match.start() < end for start, end, _ in mentions):
            continue
        mentions.append((match.start(), match.end(),
                         int(match.group().replace(".", "").replace(",", ""))))
    mentions.sort()
    claims = []
    previous_end = 0
    for start, end, amount in mentions:
        # A later amount starts a new claim; punctuation also ends the prior context.
        context = re.split(r"[.!?;,](?!\d)", text[previous_end:start])[-1]
        discount_cues = list(_DISCOUNT_CONTEXT.finditer(context))
        price_cues = list(_PRICE_CONTEXT.finditer(context))
        discount = bool(discount_cues) and (
            not price_cues or discount_cues[-1].end() >= price_cues[-1].end()
        )
        negative = discount and _NEGATIVE_DISCOUNT.search(context) is not None
        competitor = _COMPETITOR_CONTEXT.search(context) is not None
        claims.append((amount, "competitor" if competitor else
                       "discount" if discount else "price", negative))
        previous_end = end
    return claims


def attribute_feature_status(item: dict[str, Any], key: str) -> str:
    """Interpret explicit boolean evidence; absent or non-boolean data is unknown."""
    attributes = item.get("attributes")
    if not isinstance(attributes, dict):
        return "chưa biết"
    value = attributes.get(key)
    if value is True:
        return "có"
    if value is False:
        return "không có"
    # Free-text features can assert presence, but their silence cannot prove absence.
    features = attributes.get("features")
    if isinstance(features, str):
        folded = _fold_text(features)
        if any(re.search(alias, folded) for alias in _BOOLEAN_FEATURE_ALIASES.get(key, ())):
            return "có"
    return "chưa biết"


def _attribute_claim(sentence: str, start: int, end: int) -> str | None:
    """Read the assertion around a named feature, ignoring customer questions."""
    if sentence.rstrip().endswith("?"):
        return None
    before = sentence[max(0, start - 70):start]
    after = sentence[end:end + 25]
    if re.search(r"(?:chua|khong) (?:co )?(?:thong tin|du lieu)|chua ro|khong ro", before):
        return "chưa biết"
    if re.search(r"(?:khong|chua) (?:co|ho tro|duoc trang bi)\s*$", before):
        return "không có"
    if re.search(r"(?:co|ho tro|duoc trang bi)\s*$", before):
        return "có"
    if re.match(r"\s*[:,-]?\s*(?:chua co thong tin|chua ro)", after):
        return "chưa biết"
    if re.match(r"\s*[:,-]?\s*khong co\b", after):
        return "không có"
    if re.match(r"\s*[:,-]?\s*co\b", after):
        return "có"
    return None


def _unsupported_attribute_feature(candidate: str, catalog_items: list[dict[str, Any]]) -> bool:
    for sentence in re.split(r"(?<=[!?])|(?<!\d)\.(?!\d)", candidate):
        folded = _fold_text(sentence)
        for key, aliases in _BOOLEAN_FEATURE_ALIASES.items():
            for alias in aliases:
                for match in re.finditer(alias, folded):
                    claim = _attribute_claim(folded, match.start(), match.end())
                    if claim is None:
                        continue
                    named = []
                    for item in catalog_items:
                        name = item.get("name")
                        if not isinstance(name, str):
                            continue
                        names = (name, " ".join(name.split()[-2:]), item.get("sku"))
                        if any(isinstance(part, str) and part and
                               _fold_text(part) in folded for part in names):
                            named.append(item)
                    targets = named or (catalog_items if len(catalog_items) == 1 or
                                        re.search(r"\b(?:ca hai|tat ca|cac mau)\b", folded)
                                        else [])
                    if not targets or any(attribute_feature_status(item, key) != claim
                                          for item in targets):
                        return True
    return False


def _unsupported_feature(candidate: str, successful: list[dict[str, Any]]) -> bool:
    catalog_items = [item for call in successful if call["name"] == "catalog.search"
                     for item in call["result"].get("items", []) if isinstance(item, dict)]
    if _unsupported_attribute_feature(candidate, catalog_items):
        return True
    for sentence in re.split(r"[.!?](?!\d)", candidate):
        folded_sentence = _fold_text(sentence)
        features = list(_PRODUCT_FEATURE.finditer(folded_sentence))
        if not features:
            continue
        named = []
        for item in catalog_items:
            name = item.get("name")
            if not isinstance(name, str):
                continue
            aliases = [name, " ".join(name.split()[-2:])]
            sku = item.get("sku")
            if isinstance(sku, str):
                aliases.append(sku)
            if any(alias and alias.casefold() in sentence.casefold() for alias in aliases):
                named.append(item)
        supported_items = named or (catalog_items if len(catalog_items) == 1 else [])
        if not supported_items:
            return True
        for feature in features:
            needle = re.sub(r"\s+", "", feature.group()).casefold().replace(",", ".")
            claim = _attribute_claim(folded_sentence, feature.start(), feature.end())
            for item in supported_items:
                attributes = json.dumps(item.get("attributes", {}), ensure_ascii=False).casefold()
                attributes = re.sub(r"\s+", "", attributes).replace(",", ".")
                present = needle in _fold_text(attributes)
                if (claim == "không có" or claim == "có" and not present
                        or claim == "chưa biết" and present
                        or claim is None and not present):
                    return True
    return False


def check_grounding(candidate: str, tool_calls: list[dict[str, Any]]) -> str | None:
    """Checks that must run even when optional answer checks are disabled.

    The broader product, SKU and price evidence checks are added separately.
    """
    successful = [call for call in tool_calls if "error" not in call.get("result", {})]
    # There is no authorized whole-customer purge tool in the current contract.
    if _customer_erasure_completion_claim(candidate):
        return "customer_erasure_unverified"
    if _HANDOFF_DONE.search(_fold_text(candidate)) and not any(
            call.get("name") == "handoff.transfer"
            and isinstance(call.get("result"), dict)
            and call["result"].get("status") == "queued"
            and isinstance(call["result"].get("ticket_id"), str)
            and bool(call["result"]["ticket_id"]) for call in tool_calls):
        return "handoff_not_queued"
    if _unsupported_feature(candidate, successful):
        return "unsupported_product_spec"
    return None


def _quote_money_values(result: dict[str, Any]) -> set[int]:
    values = {result.get("final_price_vnd"), result.get("list_price_vnd")}
    promos = result.get("applied_promos")
    if isinstance(promos, list):
        values.update(promo.get("discount_vnd") for promo in promos
                      if isinstance(promo, dict))
    return {value for value in values if type(value) is int}


def _money_evidenced(candidate: str, successful: list[dict[str, Any]]) -> bool:
    quotes: dict[str, dict[str, Any]] = {}
    for call in successful:
        if call.get("name") != "pricing.get_quote":
            continue
        sku = call.get("args", {}).get("sku")
        result = call.get("result", {})
        if not isinstance(sku, str) or result.get("sku", sku) != sku:
            return False
        previous = quotes.get(sku)
        if previous is not None and _quote_money_values(previous) != _quote_money_values(result):
            return False
        quotes[sku] = result
    if not quotes:
        return False
    names = {item["sku"]: item["name"] for call in successful
             if call.get("name") == "catalog.search"
             for item in call.get("result", {}).get("items", [])
             if isinstance(item, dict) and isinstance(item.get("sku"), str)
             and isinstance(item.get("name"), str)}
    evidenced_skus = known_skus(successful)
    for clause in re.split(r"[;!?\n]|\.(?!\d)", candidate):
        claims = _money_claims(clause)
        if not claims:
            continue
        explicit_skus = mentioned_skus(clause, evidenced_skus)
        if set(_LEGACY_SKU_SIGNAL.findall(clause)) - explicit_skus:
            return False
        if explicit_skus and not explicit_skus <= set(quotes):
            return False
        named_catalog_skus = {sku for sku, name in names.items()
                              if name.casefold() in clause.casefold()}
        if named_catalog_skus and not named_catalog_skus <= set(quotes):
            return False
        mentioned = {sku for sku in quotes
                     if sku in explicit_skus
                     or (sku in names and names[sku].casefold() in clause.casefold())}
        if not mentioned and len(quotes) == 1:
            mentioned = set(quotes)
        if len(mentioned) != 1:
            return False
        quote = quotes[next(iter(mentioned))]
        allowed = _quote_money_values(quote)
        if any(amount not in allowed for amount, _, _ in claims):
            return False
        actual_discount = quote.get("list_price_vnd", 0) - quote.get("final_price_vnd", 0)
        promos = quote.get("applied_promos")
        applied = {promo.get("discount_vnd") for promo in promos if isinstance(promo, dict)} \
            if isinstance(promos, list) else set()
        if any(kind == "discount" and negative and amount > 0
               and amount in applied | {actual_discount}
               for amount, kind, negative in claims):
            return False
    return True


def _empty_catalog_budget_evidenced(candidate: str, customer_text: str,
                                   money_claims: list[tuple[int, str, bool]],
                                   successful: list[dict[str, Any]]) -> bool:
    """Permit one repeated budget, never a product price, after an empty search."""
    searches = [call for call in successful if call.get("name") == "catalog.search"]
    if not searches or any(call.get("name") == "pricing.get_quote" for call in successful):
        return False
    last = searches[-1]
    result = last.get("result", {})
    if result.get("items") != [] or result.get("total") != 0:
        return False
    budget = last.get("args", {}).get("max_price_vnd")
    if type(budget) is not int or budget not in customer_budget_amounts(customer_text):
        return False
    folded = _fold_text(candidate)
    if not re.search(r"\b(?:khong|chua)\s+(?:co|tim thay)\b", folded):
        return False
    if not _REPEATED_BUDGET.search(folded):
        return False
    # A second amount could be a product price even if it equals the budget.
    return len(money_claims) == 1 and money_claims[0] == (budget, "price", False)


def check_answer(candidate: str, tool_calls: list[dict[str, Any]],
                 customer_text: str = "") -> tuple[str, str | None]:
    """Return a verified answer and a stable, non-sensitive rejection reason."""
    if not candidate.strip():
        return FALLBACK, "empty_answer"
    if _customer_erasure_completion_claim(candidate):
        return FALLBACK, "customer_erasure_unverified"
    if _INTERNAL.search(candidate) or _PRICE_REFERENCE.search(candidate):
        return FALLBACK, "unsupported_policy_or_internal_claim"
    successful = [
        call
        for call in tool_calls
        if "error" not in call.get("result", {})
    ]
    policy_claim = bool(_POLICY.search(candidate))
    policy_chunks = [chunk for call in successful if call.get("name") == "policy.search"
                     for chunk in call.get("result", {}).get("chunks", [])
                     if isinstance(chunk, dict) and isinstance(chunk.get("body"), str)]
    if policy_claim:
        if not policy_chunks:
            return FALLBACK, "unsupported_policy_or_internal_claim"
        source_text = " ".join(chunk["body"] for chunk in policy_chunks)
        policy_days = re.findall(r"\b\d+\s+ngày\b", candidate.casefold())
        if any(day not in source_text.casefold() for day in policy_days):
            return FALLBACK, "unsupported_policy_or_internal_claim"
    evidenced_skus = known_skus(successful)
    claimed_skus = mentioned_skus(candidate, evidenced_skus)
    unverified_legacy_skus = set(_LEGACY_SKU_SIGNAL.findall(candidate)) - claimed_skus
    if _SUPERLATIVE.search(candidate):
        return FALLBACK, "unsupported_comparison"
    if _unsupported_feature(candidate, successful):
        return FALLBACK, "unsupported_product_spec"
    money_claims = _money_claims(candidate)
    policy_amounts = (_money_claims(" ".join(chunk["body"] for chunk in policy_chunks))
                      if policy_claim else [])
    policy_values = {amount for amount, _, _ in policy_amounts}
    if money_claims and not (_money_evidenced(candidate, successful) or
                             policy_claim and all(amount in policy_values
                                                  for amount, _, _ in money_claims) or
                             _empty_catalog_budget_evidenced(candidate, customer_text,
                                                              money_claims, successful)):
        return FALLBACK, "price_without_quote"
    if _STOCK.search(candidate):
        checks = [call for call in successful if call["name"] == "inventory.check"]
        checked_skus = {call["args"].get("sku") for call in checks}
        if len(checked_skus) != 1 or unverified_legacy_skus \
                or (claimed_skus and claimed_skus != checked_skus):
            return FALLBACK, "stock_sku_mismatch"
        stock = checks[-1]["result"].get("in_stock")
        if stock is None or ("hết hàng" in candidate.lower()) == stock:
            return FALLBACK, "stock_result_mismatch"
    if _STOCK_QTY.search(candidate):
        checks = [call for call in successful if call["name"] == "inventory.check"]
        signatures = {(call["args"].get("sku"), call["args"].get("on"),
                       call["result"].get("qty")) for call in checks}
        if len(signatures) != 1 or unverified_legacy_skus \
                or (claimed_skus and claimed_skus != {checks[-1]["args"].get("sku")}) \
                or any(int(qty) != checks[-1]["result"].get("qty")
                                    for qty in _STOCK_QTY.findall(candidate)):
            return FALLBACK, "stock_quantity_mismatch"
    if _ORDER.search(candidate) and not any(
        call["name"] == "order.create" and call["result"].get("status") == "created"
        for call in successful
    ):
        return FALLBACK, "order_creation_unverified"
    mentioned_codes = {
        code for code in _PROMO_CODE.findall(candidate)
        if code not in claimed_skus and not code.startswith(("SKU-", "OD-"))
    }
    if _PROMOTION.search(candidate) or mentioned_codes:
        quote_calls = [call for call in successful if call["name"] == "pricing.get_quote"]
        signatures = {(call["args"].get("sku"), call["args"].get("on"),
                       str(call["result"].get("applied_promos")), call["result"].get("freeship"))
                      for call in quote_calls}
        if len(signatures) != 1:
            return FALLBACK, "promotion_quote_missing"
        quotes = [quote_calls[-1]["result"]]
        shipping_only = bool(re.search(r"(?i)\b(?:freeship|miễn phí (?:ship|vận chuyển))\b", candidate))
        verified_negative_discount = any(kind == "discount" and negative
                                         for _, kind, negative in money_claims)
        if (not quotes[0].get("applied_promos") and not verified_negative_discount
                and not (shipping_only and quotes[0].get("freeship"))):
            return FALLBACK, "promotion_unverified"
        applied_codes = {p.get("promo_code") for p in quotes[0]["applied_promos"]}
        if mentioned_codes and not mentioned_codes <= applied_codes:
            return FALLBACK, "promotion_code_mismatch"
        if "%" in candidate or ("freeship" in candidate.lower() and not quotes[0].get("freeship")):
            return FALLBACK, "promotion_detail_unverified"
    if _DELIVERY.search(candidate):
        orders = [call["result"] for call in successful if call["name"] == "order.create"
                  and call["result"].get("status") == "created"]
        if len(orders) != 1 or str(orders[0].get("estimated_delivery")) not in candidate:
            return FALLBACK, "delivery_unverified"
    if _ORDER_STATUS.search(candidate):
        status_results = [call["result"] for call in successful if call["name"] == "order.status"]
        if len(status_results) != 1 or not isinstance(status_results[0].get("orders"), list) \
                or len(status_results[0]["orders"]) != 1:
            return FALLBACK, "order_status_unverified"
        status = status_results[0]["orders"][0].get("status")
        expected_phrases = {
            "shipping": "đơn đang giao", "delivered": "đơn đã giao",
            "created": "đơn đã tạo", "cancelled": "đã hủy đơn",
        }
        expected = expected_phrases.get(status)
        if expected is None or expected not in candidate.lower():
            return FALLBACK, "order_status_mismatch"
        order_ids = set(_ORDER_ID.findall(candidate))
        if order_ids and order_ids != {status_results[0]["orders"][0].get("order_id")}:
            return FALLBACK, "order_id_mismatch"
    return mask_pii(candidate.strip()), None


def verified_answer(candidate: str, tool_calls: list[dict[str, Any]],
                    customer_text: str = "") -> str:
    """Compatibility wrapper for callers that only need the answer text."""
    return check_answer(candidate, tool_calls, customer_text)[0]


class FactRejectReason(StrEnum):
    """Closed rejection vocabulary shared by diagnostics and context admission."""

    QUOTE_NOT_FOUND = "quote_not_found"
    VALUE_NOT_IN_QUOTE_WINDOW = "value_not_in_quote_window"
    UNSUPPORTED_FLOOR = "unsupported_floor"
    PREFERENCE_NOT_BLOCKER = "preference_not_blocker"
    DELIVERY_CONSTRAINT_NOT_BLOCKER = "delivery_constraint_not_blocker"
    DELIVERY_STATUS_NOT_BLOCKER = "delivery_status_not_blocker"
    PAST_CONSULTATION_NOT_BLOCKER = "past_consultation_not_blocker"
    RESOLVED_BLOCKER = "resolved_blocker"
    NEUTRAL_CHOICE_NOT_OBJECTION = "neutral_choice_not_objection"
    PREFERENCE_NOT_OBJECTION = "preference_not_objection"
    CIRCUMSTANCE_NOT_OBJECTION = "circumstance_not_objection"
    PATTERN_NOT_MATCHED = "pattern_not_matched"
    VALUE_OUT_OF_DOMAIN = "value_out_of_domain"
    TYPE_INVALID = "type_invalid"
    HYPOTHETICAL_CONTEXT = "hypothetical_context"
    NEGATED_CONTEXT = "negated_context"
    QUESTION_CONTEXT = "question_context"
    CONFLICT = "conflict"
    UNKNOWN_KEY = "unknown_key"
    PII_KEY = "pii_key"
    PII_VALUE = "pii_value"
    EMPTY_VALUE = "empty_value"
    THIRD_PARTY_CONTEXT = "third_party_context"
    TOOL_EVIDENCE_MISSING = "tool_evidence_missing"
    REPORTED_FACT_MISSING = "reported_fact_missing"


@dataclass(frozen=True)
class FactEvidence:
    source: str | None
    reason: FactRejectReason | None
    normalized_value: Any = None
    evidence_quote: str | None = None

    def __post_init__(self) -> None:
        if (self.source is None) == (self.reason is None):
            raise ValueError("Fact evidence needs exactly one of source or reject reason")


# These are semantic price-objection expressions, not a complete BTC enum.
_EXPENSIVE_PHRASE = re.compile(
    r"(?i)\b(?:đắt(?:\s+(?:quá|thế|hơn))?|mắc(?:\s+quá)?|chát|"
    r"giá\s+(?:hơi\s+|khá\s+)?cao|dat\s+(?:qua|the|hon)|"
    r"mac\s+qua|gia\s+(?:hoi\s+|kha\s+)?cao)\b"
)
_OBJECTION_NEGATION = re.compile(
    r"\b(?:khong|chua)\s+(?:he\s+|qua\s+)?(?:dat|mac|chat|cao)\b|"
    r"\bgia\s+(?:khong|chua)\s+cao\b"
)
_NEUTRAL_CHOICE = re.compile(
    r"\b(?:can nhac|phan van|dang chon|so sanh)\s+giua\b"
)
# Expressions of a purchase concern or refusal, scoped to objection admission.
_OBJECTION_PURCHASE_CONCERN = re.compile(
    r"\b(?:so|lo|ngai|e ngai|chua tin|khong tin|khong yen tam|"
    r"khong muon mua|chua muon mua|khong mua|khong lay|tu choi)\b|"
    r"\bkhong thich\s+(?:mau|san pham|cai|chiec|con)\s+nay\b|"
    r"\b(?:giao|ship|van chuyen|nhan hang)\b[^.!?;,]{0,35}\b(?:lau|cham|tre|dat|kem)\b|"
    r"\bphi\s+(?:giao|ship|van chuyen)\b[^.!?;,]{0,25}\b(?:cao|dat|mac)\b|"
    r"\b(?:chay on|qua on|on qua|khong ben|de hong|de loi|chat luong kem|"
    r"bao hanh ngan|gia khong hop ly)\b|"
    r"\b(?:ben kia|ben khac|doi thu|shop khac)\b[^.!?;,]{0,60}"
    r"\b(?:re hon|tot hon|gia thap hon|giao nhanh hon|bao hanh lau hon)\b"
)
_OBJECTION_PREFERENCE = re.compile(
    r"\b(?:thich|khong thich|ua|uu tien|muon|khong muon|can)\b"
)
_OBJECTION_HYPOTHETICAL = re.compile(
    r"\b(?:neu|gia su|vi du|thu)\b|^nho\b|"
    r"\blo\s+(?:toi|anh|chi|em|minh|nha toi)\b"
)
_PAYMENT_PHRASES = {
    "COD": r"cod|ship\s+cod",
    "bank": r"bank|chuyen\s+khoan|ngan\s+hang",
    "momo": r"momo",
    "zalopay": r"zalopay",
}


def _quote_present(quote: str, customer_text: str) -> bool:
    def light(text: str) -> str:
        return " ".join(unicodedata.normalize("NFC", text).casefold().split())
    return light(quote) in light(customer_text)


def _quote_overlaps_clause(quote: str, clause: str) -> bool:
    return _quote_present(quote, clause) or _quote_present(clause.strip(), quote)


def _normalize_slot_value(key: str, value: Any, customer_text: str,
                          evidence_quote: str | None) -> tuple[Any, str | None, FactRejectReason | None]:
    """Apply the SlotSpec domain before testing evidence for a candidate."""
    spec = SLOT_SPEC_BY_KEY.get(key)
    if spec is None:
        return value, None, FactRejectReason.UNKNOWN_KEY
    types = spec.value_type if isinstance(spec.value_type, tuple) else (spec.value_type,)
    if key != Slot.OBJECTION and type(value) not in types:
        return value, None, FactRejectReason.TYPE_INVALID
    if isinstance(value, str) and (not value.strip() or mask_pii(value) != value):
        return value, None, (FactRejectReason.EMPTY_VALUE if not value.strip()
                             else FactRejectReason.PII_VALUE)
    if evidence_quote is not None:
        if (not isinstance(evidence_quote, str) or not evidence_quote.strip()
                or len(evidence_quote) > 200 or mask_pii(evidence_quote) != evidence_quote
                or not _quote_present(evidence_quote, customer_text)):
            return value, None, FactRejectReason.QUOTE_NOT_FOUND
    if key == Slot.OBJECTION:
        if not isinstance(value, str):
            return value, None, FactRejectReason.TYPE_INVALID
        quote = evidence_quote
        if quote is None and value not in spec.allowed_values and _quote_present(value, customer_text):
            quote = value
        if quote is None:
            match = _EXPENSIVE_PHRASE.search(customer_text)
            if match:
                quote = match.group()
        if quote is None:
            return value, None, FactRejectReason.QUOTE_NOT_FOUND
        expensive = bool(_EXPENSIVE_PHRASE.search(quote))
        if not expensive and _NEUTRAL_CHOICE.search(_fold_text(quote)):
            return value, quote, FactRejectReason.NEUTRAL_CHOICE_NOT_OBJECTION
        if value == "dat_qua" and not expensive:
            return value, quote, FactRejectReason.VALUE_NOT_IN_QUOTE_WINDOW
        return ("dat_qua" if expensive else "khac"), quote, None
    if spec.value_domain == "closed":
        if spec.allowed_values:
            canonical = next((item for item in spec.allowed_values
                              if isinstance(value, str) and item.casefold() == value.casefold()), None)
            if canonical is None:
                return value, evidence_quote, FactRejectReason.VALUE_OUT_OF_DOMAIN
            value = canonical
        elif type(value) is int and value <= 0:
            return value, evidence_quote, FactRejectReason.VALUE_OUT_OF_DOMAIN
        elif spec.value_format == "date":
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError("noncanonical date")
            except ValueError:
                return value, evidence_quote, FactRejectReason.VALUE_OUT_OF_DOMAIN
    return value, evidence_quote, None


def _fact_evidence_source(
    key: str, value: Any, op: str, customer_text: str, tool_calls: list[dict[str, Any]],
    evidence_quote: str | None = None,
) -> str | None:
    """Original admission rule. Keep this independent of diagnostic classification."""
    if key not in PROFILE_SLOT_KEYS or _PII_KEY.search(key) or type(value) not in {str, int, float, bool}:
        return None
    if isinstance(value, str) and (not value.strip() or mask_pii(value) != value):
        return None
    tool_only_keys = TOOL_ONLY_SLOT_KEYS
    folded_customer = _fold_text(customer_text)
    if re.search(r"\b(?:ban toi|ban minh|hang xom|dong nghiep|khach khac)\b", folded_customer):
        # Do not attach a third party's statement to this customer's profile.
        customer_evidence_allowed = False
    else:
        customer_evidence_allowed = True
    if op == "delete":
        return "customer" if re.search(r"(?i)\b(?:xóa|bỏ|không còn)\b", customer_text) and key in customer_text else None
    if isinstance(value, bool) and key not in tool_only_keys and customer_evidence_allowed:
        if key == Slot.HAS_CHILDREN and value and not re.search(
            r"\b(?:khong|chua)\s+(?:co\s+)?(?:con|be|em be)\b", folded_customer
        ) and re.search(r"\b(?:be nho|con nho|co con|co em be)\b", folded_customer):
            return "customer"
        if key == Slot.HAS_CHILDREN and value is False and re.search(
            r"\b(?:khong|chua)\s+(?:co\s+)?(?:con|be|em be)\b", folded_customer
        ):
            return "customer"
    elif key not in tool_only_keys and customer_evidence_allowed:
        direct = str(value).lower() in customer_text.lower()
        if key == Slot.ROOM_AREA_M2:
            direct = _room_area_evidenced(value, customer_text)
        elif key == Slot.PREFERRED_SIZE:
            direct = bool(re.search(rf"(?i)\bsize\s*{re.escape(str(value))}\b", customer_text))
        elif key == Slot.PREFERRED_COLOR:
            direct = bool(re.search(rf"\bmau\b(?:\s+\w+){{0,5}}\s+"
                                    rf"{re.escape(_fold_text(str(value)))}\b", folded_customer))
        elif key == Slot.SIZE:
            direct = bool(re.search(rf"(?i)\bsize\s*{re.escape(str(value))}\b", customer_text))
        elif key == Slot.COLOR:
            direct = bool(re.search(rf"\bmau\b(?:\s+\w+){{0,5}}\s+"
                                    rf"{re.escape(_fold_text(str(value)))}\b", folded_customer))
        elif key == Slot.PAYMENT:
            phrase = _PAYMENT_PHRASES.get(str(value))
            direct = bool(phrase and re.search(
                r"\b(?:thanh toan|tra|chuyen khoan|ship)\s+"
                r"(?:(?:bang|qua|vi)\s+)?(?:" + phrase + r")\b", folded_customer))
            if value == "bank" and re.search(r"\bchuyen khoan\b", folded_customer):
                direct = True
        elif key == Slot.OBJECTION:
            direct = bool(evidence_quote and _quote_overlaps_clause(evidence_quote, customer_text)) and (
                bool(_EXPENSIVE_PHRASE.search(customer_text)) if value == "dat_qua"
                else value == "khac")
        normalized_money = set()
        for digits, unit in re.findall(r"(?i)\b(\d+(?:[.,]\d+)?)\s*(triệu|tr|nghìn|ngàn|k)\b", customer_text):
            number = float(digits.replace(",", "."))
            normalized_money.add(int(number * (1_000_000 if unit.lower() in {"triệu", "tr"} else 1_000)))
        if key == Slot.COMPETITOR_PRICE_VND:
            competitor_amounts = {
                int(float(digits.replace(",", ".")) *
                    (1_000_000 if unit.lower() in {"triệu", "tr"} else 1_000))
                for digits, unit in re.findall(
                    r"(?i)\b(?:bên kia|bên khác|shop khác|đối thủ)\b[^.!?]{0,80}?\b"
                    r"(\d+(?:[.,]\d+)?)\s*(triệu|tr|nghìn|ngàn|k)\b", customer_text)
            }
            if value in competitor_amounts:
                return "customer"
        elif key == Slot.BUDGET_VND:
            if type(value) is int and value in customer_budget_amounts(customer_text):
                return "customer"
        elif direct or (key not in {Slot.ROOM_AREA_M2, Slot.BUDGET_VND}
                        and value in normalized_money):
            return "customer"
    for call in tool_calls:
        if "error" in call.get("result", {}):
            continue
        name = call["name"]
        result = safe_tool_result(call["result"])
        supported = False
        if key == Slot.PRODUCT_ADVISED and name in {
            "catalog.search", "inventory.check", "pricing.get_quote"
        }:
            supported = value == result.get("sku") or (
                name == "catalog.search"
                and any(value == item.get("sku") for item in result.get("items", []))
            )
        elif key == Slot.PRICE_QUOTED_VND and name == "pricing.get_quote":
            supported = value == result.get("final_price_vnd")
        elif key == Slot.PROMO_CODE and name == "pricing.get_quote":
            supported = any(value == promo.get("promo_code")
                            for promo in result.get("applied_promos", []))
        elif key == Slot.PROMO_EXPIRY and name == "pricing.get_quote":
            supported = any(value == promo.get("valid_until")
                            for promo in result.get("applied_promos", []))
        elif key == Slot.ORDER_ID and name == "order.create":
            supported = result.get("status") == "created" and value == result.get("order_id")
        elif key == Slot.VARIANT_SKU and name == "catalog.search":
            supported = any(value == variant.get("variant_sku")
                            for item in result.get("items", []) if isinstance(item, dict)
                            for variant in item.get("variants", []) if isinstance(variant, dict))
        elif key == Slot.VARIANT_SKU and name == "order.create":
            supported = result.get("status") == "created" and value == call.get("args", {}).get("sku")
        elif key == Slot.IN_STOCK and name == "inventory.check":
            supported = value is result.get("in_stock")
        if supported:
            return f"tool:{name}"
    return None


def _fact_reject_reason(key: str, value: Any, op: str, customer_text: str,
                        tool_calls: list[dict[str, Any]]) -> FactRejectReason:
    """Classify an existing rejection; this function cannot admit a candidate."""
    if key not in PROFILE_SLOT_KEYS:
        return FactRejectReason.UNKNOWN_KEY
    if _PII_KEY.search(key):
        return FactRejectReason.PII_KEY
    if type(value) not in {str, int, float, bool}:
        return FactRejectReason.TYPE_INVALID
    if isinstance(value, str):
        if not value.strip():
            return FactRejectReason.EMPTY_VALUE
        if mask_pii(value) != value:
            return FactRejectReason.PII_VALUE
    if op == "delete":
        return FactRejectReason.PATTERN_NOT_MATCHED
    folded = _fold_text(customer_text)
    if re.search(r"\b(?:ban toi|ban minh|hang xom|dong nghiep|khach khac)\b", folded):
        return FactRejectReason.THIRD_PARTY_CONTEXT
    if key in TOOL_ONLY_SLOT_KEYS:
        return FactRejectReason.TOOL_EVIDENCE_MISSING
    if key == Slot.OBJECTION and value not in SLOT_SPEC_BY_KEY[Slot.OBJECTION].allowed_values:
        return FactRejectReason.VALUE_OUT_OF_DOMAIN
    if re.search(r"\bneu\b", folded):
        return FactRejectReason.HYPOTHETICAL_CONTEXT
    if "?" in customer_text or re.search(r"\b(?:duoc khong|phai khong)\b", folded):
        return FactRejectReason.QUESTION_CONTEXT
    if key == Slot.BUDGET_VND and type(value) is int:
        amounts = {
            int(float(digits.replace(",", ".")) *
                (1_000_000 if unit.lower() in {"triệu", "tr"} else 1_000))
            for digits, unit in re.findall(
                r"(?i)\b(\d+(?:[.,]\d+)?)\s*(triệu|tr|nghìn|ngàn|k)\b", customer_text)
        }
        if value in amounts and value not in customer_budget_amounts(customer_text):
            return FactRejectReason.VALUE_NOT_IN_QUOTE_WINDOW
    if key in {Slot.ROOM_AREA_M2, Slot.BUDGET_VND, Slot.HAS_CHILDREN,
               Slot.PREFERRED_SIZE, Slot.SIZE, Slot.PREFERRED_COLOR, Slot.COLOR,
               Slot.PAYMENT, Slot.OBJECTION, Slot.COMPETITOR_PRICE_VND}:
        return FactRejectReason.PATTERN_NOT_MATCHED
    if isinstance(value, str) and value.casefold() not in customer_text.casefold():
        return FactRejectReason.QUOTE_NOT_FOUND
    if type(value) in {int, float} and str(value) not in customer_text:
        return FactRejectReason.VALUE_NOT_IN_QUOTE_WINDOW
    return FactRejectReason.PATTERN_NOT_MATCHED


_CONTEXT_CLAUSE = re.compile(r"[;,](?!\d)|\b(?:nhưng|nhung|và|va|mà|ma)\b", re.IGNORECASE)
_HYPOTHETICAL_CUE = re.compile(r"\b(?:neu|gia su|lo|vi du)\b|^nho\b")
_QUESTION_CUE = re.compile(r"\b(?:duoc khong|khong a|phai khong|the nao|thi sao|hay sao)\b|\b(?:a|ha|nhi|chua)\s*$")
_POLAR_CHILD_NEGATION = re.compile(r"\b(?:khong|chua)\s+(?:co\s+)?(?:con|be|em be)\b")
_SELECTION_NEGATION = re.compile(r"\bkhong\s+(?:(?:can|muon)\s+)?(?:thanh toan|tra|chuyen khoan|chon|lay|thich|mua|dung|phai)\b|\bkhong\s+(?:can|muon)\b")
_OBSTACLE_NEGATION = re.compile(r"\bkhong\s+can\b")
_BLOCKER_DECISION_PERSON = PERSON_PATTERN
_BLOCKER_CONSULT = re.compile(
    rf"\b(?:hoi\s+(?:them\s+|y kien\s+)?|xin y kien\s+|"
    rf"(?:ban|trao doi)\s+(?:bac\s+)?voi\s+){_BLOCKER_DECISION_PERSON}\b")
_BLOCKER_APPROVAL = re.compile(
    rf"\b{_BLOCKER_DECISION_PERSON}\b(?:\s+(?:toi|minh|nha toi))?\s+"
    r"(?:chua|khong)\s+(?:dong y|chap nhan|ung ho|quyet)\b")
_BLOCKER_WAIT_PERSON = re.compile(
    rf"\b(?:doi|cho)\s+{_BLOCKER_DECISION_PERSON}\s+(?:ve|quay lai|tra loi)\b")
_BLOCKER_WAIT = re.compile(
    r"\b(?:doi|cho)\b[^.!?;,]{0,45}\b(?:luong|bao gia|duyet|xac nhan|quyet dinh|mua)\b")
_BLOCKER_DEFERRED_REPLY = re.compile(
    r"\b(?:xem|kiem tra)\s+lai\b[^.!?;,]{0,20}\b(?:roi\s+)?bao\b")
_BLOCKER_DECISION = re.compile(
    r"\b(?:chua quyet|chua chot|chua the mua|can nhac gia|so sanh gia)\b|"
    r"\b(?:can|phai)\b[^.!?;,]{0,45}\b(?:truoc khi|roi moi)\s+(?:mua|quyet|chot)\b")
_BLOCKER_DELIVERY = re.compile(r"\b(?:giao|nhan hang|ship|van chuyen)\b")
_BLOCKER_PREFERENCE = re.compile(r"\b(?:khong thich|thich|uu tien|khong muon|muon|can)\b")
_BLOCKER_REJECTED_CONSULT = re.compile(r"\bkhong\s+(?:thich|muon|can)\b[^.!?;,]{0,25}\bhoi\b")
_BLOCKER_PAST_CONSULT = re.compile(
    rf"\bda\b[^.!?;,]{{0,30}}\b(?:ban|trao doi|hoi)\b[^.!?;,]{{0,30}}\b{_BLOCKER_DECISION_PERSON}\b|"
    rf"\b(?:ban|trao doi|hoi)\b[^.!?;,]{{0,25}}\b{_BLOCKER_DECISION_PERSON}\s+roi\s*[.!?]?$"
)
_BLOCKER_RESOLVED_APPROVAL = re.compile(
    rf"\b{_BLOCKER_DECISION_PERSON}\b(?:\s+(?:toi|minh|nha toi))?\s+"
    r"(?:da\s+)?(?:dong y|chap nhan|ung ho)\s*(?:roi)?\b")
_BLOCKER_DELIVERY_STATUS = re.compile(
    r"\b(?:cho|doi)\s+(?:giao\s+)?hang\b[^.!?;,]{0,35}\b(?:ngay|tuan|chua thay|chua toi)\b")


def _blocker_rejection(value: Any, customer_text: str) -> FactRejectReason | None:
    """Classify a proposed blocker by the meaning of its supporting clause."""
    if not isinstance(value, str) or not value.strip() or mask_pii(value) != value:
        return None
    folded_value = _fold_text(value).strip()
    clauses = [part.strip() for part in _CONTEXT_CLAUSE.split(unicodedata.normalize("NFC", customer_text))
               if part.strip()]
    reasons: list[FactRejectReason] = []
    for clause in clauses:
        folded = _fold_text(clause)
        if folded_value not in folded:
            continue
        if _BLOCKER_PAST_CONSULT.search(folded):
            reasons.append(FactRejectReason.PAST_CONSULTATION_NOT_BLOCKER)
            continue
        if _BLOCKER_RESOLVED_APPROVAL.search(folded):
            reasons.append(FactRejectReason.RESOLVED_BLOCKER)
            continue
        if _BLOCKER_DELIVERY_STATUS.search(folded):
            reasons.append(FactRejectReason.DELIVERY_STATUS_NOT_BLOCKER)
            continue
        if _BLOCKER_REJECTED_CONSULT.search(folded):
            reasons.append(FactRejectReason.PREFERENCE_NOT_BLOCKER)
            continue
        if (_BLOCKER_CONSULT.search(folded) or _BLOCKER_APPROVAL.search(folded)
                or _BLOCKER_WAIT_PERSON.search(folded) or _BLOCKER_WAIT.search(folded)
                or _BLOCKER_DEFERRED_REPLY.search(folded) or _BLOCKER_DECISION.search(folded)):
            return None
        if _BLOCKER_DELIVERY.search(folded):
            reasons.append(FactRejectReason.DELIVERY_CONSTRAINT_NOT_BLOCKER)
        elif _BLOCKER_PREFERENCE.search(folded):
            reasons.append(FactRejectReason.PREFERENCE_NOT_BLOCKER)
        else:
            reasons.append(FactRejectReason.PATTERN_NOT_MATCHED)
    return reasons[0] if reasons else None


def _objection_rejection(customer_text: str, quote: str) -> FactRejectReason | None:
    """Require the quoted clause to express a purchase concern or refusal."""
    reasons: list[FactRejectReason] = []
    for clause in _CONTEXT_CLAUSE.split(unicodedata.normalize("NFC", customer_text)):
        if not clause.strip() or not _quote_overlaps_clause(quote, clause):
            continue
        folded = _fold_text(clause)
        if _EXPENSIVE_PHRASE.search(quote) or _OBJECTION_PURCHASE_CONCERN.search(folded):
            return None
        if _OBJECTION_PREFERENCE.search(folded):
            reasons.append(FactRejectReason.PREFERENCE_NOT_OBJECTION)
        else:
            reasons.append(FactRejectReason.CIRCUMSTANCE_NOT_OBJECTION)
    return reasons[0] if reasons else FactRejectReason.QUOTE_NOT_FOUND


def _context_rejection(key: str, value: Any, op: str, customer_text: str,
                       evidence_quote: str | None = None) -> FactRejectReason | None:
    """Reject a proposed customer fact only when all matching clauses lack an assertion.

    Current proposals have no evidence_quote. The existing slot matcher identifies
    clauses that could support this exact key/value; ambiguous unmatched clauses
    remain governed by the existing whole-turn evidence rule.
    """
    spec = SLOT_SPEC_BY_KEY.get(key)
    if op != "set" or spec is None or spec.evidence_source != "customer":
        return None
    clauses = [part.strip() for part in _CONTEXT_CLAUSE.split(unicodedata.normalize("NFC", customer_text))
               if part.strip()]
    reasons: list[FactRejectReason] = []
    for clause in clauses:
        if _fact_evidence_source(key, value, op, clause, [], evidence_quote) != "customer":
            continue
        folded = _fold_text(clause)
        hypothetical = (_HYPOTHETICAL_CUE.search(folded)
                        or re.search(r"\b(?:nhỡ|thử)\b", clause.casefold()))
        if spec.semantic_gate == "purchase_objection":
            # Accent folding makes the concern "lo" identical to hypothetical
            # "lỡ". Keep the explicit accented cue and a narrow ASR form.
            hypothetical = (_OBJECTION_HYPOTHETICAL.search(folded)
                            or re.search(r"\b(?:lỡ|nhỡ)\b", clause.casefold()))
        if hypothetical:
            reasons.append(FactRejectReason.HYPOTHETICAL_CONTEXT)
        elif "?" in clause or _QUESTION_CUE.search(folded):
            reasons.append(FactRejectReason.QUESTION_CONTEXT)
        elif spec.context_negation == "polar" and key == Slot.HAS_CHILDREN \
                and value is True and _POLAR_CHILD_NEGATION.search(folded):
            reasons.append(FactRejectReason.NEGATED_CONTEXT)
        elif spec.context_negation == "selection" and _SELECTION_NEGATION.search(folded):
            reasons.append(FactRejectReason.NEGATED_CONTEXT)
        elif spec.context_negation == "objection" and _OBJECTION_NEGATION.search(folded):
            reasons.append(FactRejectReason.NEGATED_CONTEXT)
        elif spec.context_negation == "obstacle" and _OBSTACLE_NEGATION.search(folded):
            reasons.append(FactRejectReason.NEGATED_CONTEXT)
        else:
            return None
    return reasons[0] if reasons else None


def fact_evidence(
    key: str, value: Any, op: str, customer_text: str, tool_calls: list[dict[str, Any]],
    evidence_quote: str | None = None,
) -> FactEvidence:
    """Apply clause context before the existing slot evidence decision."""
    if key not in PROFILE_SLOT_KEYS:
        return FactEvidence(source=None, reason=FactRejectReason.UNKNOWN_KEY)
    if _PII_KEY.search(key):
        return FactEvidence(source=None, reason=FactRejectReason.PII_KEY)
    if op == "set":
        value, evidence_quote, domain_reason = _normalize_slot_value(
            key, value, customer_text, evidence_quote)
        if domain_reason is not None:
            return FactEvidence(source=None, reason=domain_reason)
        if evidence_quote and SLOT_SPEC_BY_KEY[key].evidence_source == "customer":
            quoted_clauses = [clause.strip() for clause in
                              _CONTEXT_CLAUSE.split(unicodedata.normalize("NFC", customer_text))
                              if _quote_overlaps_clause(evidence_quote, clause)]
            if not quoted_clauses:
                return FactEvidence(source=None, reason=FactRejectReason.QUOTE_NOT_FOUND)
            if not any(_fact_evidence_source(key, value, op, clause, [], evidence_quote)
                       == "customer" for clause in quoted_clauses):
                return FactEvidence(source=None, reason=FactRejectReason.VALUE_NOT_IN_QUOTE_WINDOW)
    if key == Slot.BUDGET_VND and type(value) is int \
            and value in customer_budget_floor_amounts(customer_text) \
            and value not in customer_budget_amounts(customer_text):
        return FactEvidence(source=None, reason=FactRejectReason.UNSUPPORTED_FLOOR)
    context_reason = _context_rejection(key, value, op, customer_text, evidence_quote)
    if context_reason is not None:
        return FactEvidence(source=None, reason=context_reason)
    if key == Slot.BLOCKER and op == "set":
        blocker_reason = _blocker_rejection(value, customer_text)
        if blocker_reason is not None:
            return FactEvidence(source=None, reason=blocker_reason)
    if op == "set" and SLOT_SPEC_BY_KEY[key].semantic_gate == "purchase_objection":
        objection_reason = _objection_rejection(customer_text, evidence_quote or "")
        if objection_reason is not None:
            return FactEvidence(source=None, reason=objection_reason)
    source = _fact_evidence_source(key, value, op, customer_text, tool_calls,
                                   evidence_quote)
    return FactEvidence(source=source, reason=None if source is not None else
                        _fact_reject_reason(key, value, op, customer_text, tool_calls),
                        normalized_value=value if source else None,
                        evidence_quote=evidence_quote if source else None)
