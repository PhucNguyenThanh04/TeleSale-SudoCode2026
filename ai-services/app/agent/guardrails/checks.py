from app.mcp_servers.mcp_shared.commerce_evidence import CATALOG_TOOLS

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from app.mcp_servers.mcp_shared.commerce_rules import _search_text
from app.mcp_servers.mcp_shared.pii import mask_pii
from app.mcp_servers.mcp_shared.episode_evidence import evidence_supports
from app.constants import PROFILE_SLOT_KEYS, SLOT_SPEC_BY_KEY, TOOL_ONLY_SLOT_KEYS, Slot
from app.agent.guardrails.skus import known_skus, mentioned_skus
from app.agent.guardrails.promotion_grounding import check_promotion_grounding
from app.agent.guardrails.claims import assertion_text


FALLBACK = ""

_STOCK = re.compile(r"(?i)\b(?:còn hàng|có hàng|sẵn hàng|hết hàng|có sẵn trong kho)\b")
_ORDER = re.compile(r"(?i)\bđã\s+(?:lên|tạo|đặt|chốt)\s+đơn\b")
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
_AREA_NUMBER_WORD = r"(?:không|một|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|mười|mươi|trăm|linh|lẻ|chục|"
_AREA_NUMBER_WORD += r"khong|mot|bon|nam|lam|sau|bay|tam|chin|muoi|tram|le|chuc)"
_SPOKEN_AREA = re.compile(
    rf"(?i)\b({_AREA_NUMBER_WORD}(?:\s+{_AREA_NUMBER_WORD}){{0,6}})\s*{_AREA_UNIT}(?!\w)"
)


def _spoken_integer(words: str) -> int | None:
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
    return _search_text(value)


_ERASURE_ACTION = re.compile(r"\b(?:xoa|go|huy|loai bo)\b|\b(?:dung|khong)\s+(?:tiep tuc\s+)?(?:giu|luu)\b")
_ERASURE_SUBJECT = re.compile(r"\b(?:du lieu|thong tin|ho so)\b")
_ERASURE_DONE = re.compile(r"\bda\s+(?:duoc\s+)?(?:xoa|go|huy|loai bo|xu ly xong)\b|\b(?:xoa|go|huy)\s+(?:xong|het|hoan tat)\b|\bda\s+(?:xu ly|hoan thanh)\s+xong\s+yeu cau\s+xoa\b")
_HANDOFF_DONE = re.compile(
    r"\b(?:da|vua)\s+(?:ban giao|ket noi|noi may|chuyen may)\b"
    r"|\b(?:da|vua)\s+chuyen\b[^.!?]{0,60}\b(?:nhan vien|bo phan|tong dai|nguoi tu van)\b"
    r"|\b(?:chuyen|ban giao|ket noi|noi may)\b[^.!?]{0,50}\b(?:nhan vien|bo phan|tong dai)\b[^.!?]{0,30}\broi\b")




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
    def clean(value: Any, field='') -> Any:
        if isinstance(value, str):
            if field in {'source_hash', 'content_hash'} and re.fullmatch(r'[a-f0-9]{64}', value):
                return value
            return mask_pii(value)
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {
                key: clean(item, key) for key, item in value.items()
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
    if unit.lower() in {"triệu", "tr"} and re.fullmatch(r"\d+[.,]\d+", digits):
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
_BUDGET_CUE = re.compile(r"\b(?:ngan sach|budget|muon chi|dinh chi|co the chi|chi tam|chi khoang|trong tam gia)\b")
_PRICE_AFTER_BUDGET_CUE = re.compile(r"\b(?:gia|shop|cua hang|ben kia|ben khac|doi thu)\b")


def _folded_budget_amount(raw: str) -> int | None:
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
    attributes = item.get("attributes")
    if not isinstance(attributes, dict):
        return "chưa biết"
    value = attributes.get(key)
    if value is True:
        return "có"
    if value is False:
        return "không có"
    features = attributes.get("features")
    if isinstance(features, str):
        folded = _fold_text(features)
        if any(re.search(alias, folded) for alias in _BOOLEAN_FEATURE_ALIASES.get(key, ())):
            return "có"
    return "chưa biết"


def _attribute_claim(sentence: str, start: int, end: int) -> str | None:
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
    catalog_items = [item for call in successful if call["name"] in CATALOG_TOOLS
                     for item in call["result"].get("items", []) if isinstance(item, dict)]
    if _unsupported_attribute_feature(candidate, catalog_items):
        return True
    for sentence in re.split(r"[.!?](?!\d)", candidate):
        folded_sentence = _fold_text(sentence)
        features = list(_PRODUCT_FEATURE.finditer(folded_sentence))
        tds = (re.findall(r'(\d+(?:[.,]\d+)?)\s*ppm\b', folded_sentence)
               if re.search(r'\btds\b', folded_sentence) else [])
        if not features and not tds:
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
        if tds and any(type((item.get('attributes') or {}).get('tds_output_ppm')) not in (int, float)
                       or any(float(value.replace(',', '.')) != item['attributes']['tds_output_ppm']
                              for value in tds) for item in supported_items):
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
    candidate = assertion_text(candidate)
    successful = [call for call in tool_calls if "error" not in call.get("result", {})]
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
    from app.agent.guardrails.policy_grounding import (policy_evidence_for_answer,
        policy_clarification_or_refusal, policy_durations_supported)
    policy_calls = [c for c in successful if c.get('name') == 'policy.search']
    if _POLICY.search(candidate) and not policy_clarification_or_refusal(candidate):
        evidence = policy_evidence_for_answer(candidate, policy_calls)
        if not evidence:
            return 'unsupported_policy_or_internal_claim'
        source_text = ' '.join(row['content'] for row in evidence).casefold()
        if not policy_durations_supported(candidate, source_text):
            return 'unsupported_policy_or_internal_claim'
    return None


def _quote_money_values(result: dict[str, Any]) -> set[int]:
    values = {result.get("final_price_vnd"), result.get("list_price_vnd")}
    promos = result.get("applied_promos")
    if isinstance(promos, list):
        values.update(promo.get("discount_vnd") for promo in promos
                      if isinstance(promo, dict))
    return {value for value in values if type(value) is int}


def _money_evidenced(candidate: str, successful: list[dict[str, Any]], *, focus_sku: str | None = None) -> bool:
    from app.mcp_servers.mcp_shared.basket import basket_money_evidenced
    from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
    previews = [call for call in successful if call.get('name') == 'order.preview_update'
                and call.get('result', {}).get('status') == 'preview' and call['result'].get('estimate') is True]
    if previews:
        values = {value for call in previews for value in _vnd_values(call['result'])}
        if all(amount in values for amount, _, _ in _money_claims(candidate)):
            return True
    baskets = [call for call in successful if call.get('name') == 'pricing.quote_order']
    if baskets:
        basket_skus = {unit['sku'] for call in baskets for unit in call['result'].get('units', [])}
        remaining = []
        for clause in re.split(r'[;!?\n]|\.(?!\d)', candidate):
            if not _money_claims(clause):
                continue
            bound = resolve_claim_skus(clause, successful, focus_sku=focus_sku)
            if not bound or bound & basket_skus or re.search(r'\btong\b|ca don|ca gio', _fold_text(clause)):
                if not basket_money_evidenced(clause, successful):
                    return False
            else:
                remaining.append(clause)
        if not remaining:
            return True
        candidate = '; '.join(remaining)
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
    for clause in re.split(r"[;!?\n]|\.(?!\d)", candidate):
        claims = _money_claims(clause)
        if not claims:
            continue
        if set(_LEGACY_SKU_SIGNAL.findall(clause)) - known_skus(successful):
            return False
        bound = resolve_claim_skus(clause, successful, focus_sku=focus_sku)
        direct_parents = {sku for sku in bound & quotes.keys() if any(
            c.get('name') in CATALOG_TOOLS and any(i.get('sku') == sku for i in c['result'].get('items', []))
            for c in successful)}
        mentioned = direct_parents if len(direct_parents) == 1 else bound
        if not bound and len(quotes) == 1:
            mentioned = set(quotes)
        if len(mentioned) != 1 or not mentioned <= quotes.keys():
            return False
        quote = quotes[next(iter(mentioned))]
        prices = {quote.get(key) for key in ('final_price_vnd', 'list_price_vnd')
                  if type(quote.get(key)) is int}
        actual_discount = (quote['list_price_vnd'] - quote['final_price_vnd']
                           if all(type(quote.get(key)) is int for key in
                                  ('list_price_vnd', 'final_price_vnd')) else None)
        promos = quote.get('applied_promos')
        discounts = {promo.get('discount_vnd') for promo in promos
                     if isinstance(promo, dict) and type(promo.get('discount_vnd')) is int} \
                    if isinstance(promos, list) else set()
        if actual_discount is not None and actual_discount >= 0:
            discounts.add(actual_discount)
        if re.search(r'\btong\b|ca don', _fold_text(clause)):
            selected_call = next(c for c in successful if c.get('name') == 'pricing.get_quote'
                                 and c.get('args', {}).get('sku') == next(iter(mentioned)))
            qty = selected_call.get('args', {}).get('qty', 1)
            total_values = {quote[k] * qty for k in ('final_price_vnd', 'list_price_vnd')
                            if type(quote.get(k)) is int and type(qty) is int}
            if any(kind == 'price' and amount not in total_values for amount, kind, _ in claims):
                return False
            prices |= total_values
        if any(amount not in (discounts if kind == 'discount' else prices)
               for amount, kind, _ in claims):
            return False
        if any(kind == "discount" and negative and amount > 0
               and amount in discounts
               for amount, kind, negative in claims):
            return False
    return True


def _vnd_values(value, field=''):
    if isinstance(value, dict):
        return {amount for key, item in value.items() for amount in _vnd_values(item, key)}
    if isinstance(value, list):
        return {amount for item in value for amount in _vnd_values(item, field)}
    return {value} if field.endswith('_vnd') and type(value) is int and value >= 0 else set()


def _empty_catalog_budget_evidenced(candidate: str, customer_text: str,
                                   money_claims: list[tuple[int, str, bool]],
                                   successful: list[dict[str, Any]]) -> bool:
    searches = [call for call in successful if call.get("name") in CATALOG_TOOLS]
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
    return len(money_claims) == 1 and money_claims[0] == (budget, "price", False)


def _catalog_budget_repetition_evidenced(candidate: str, customer_text: str,
                                        money_claims: list[tuple[int, str, bool]],
                                        successful: list[dict[str, Any]]) -> bool:
    searches = [call for call in successful if call.get("name") in CATALOG_TOOLS]
    if not searches or len(money_claims) != 1:
        return False
    last = searches[-1]
    if not isinstance(last.get("result", {}).get("items"), list):
        return False
    budget = last.get("args", {}).get("max_price_vnd")
    if (type(budget) is not int or budget not in customer_budget_amounts(customer_text)
            or money_claims[0] != (budget, "price", False)):
        return False
    folded = _fold_text(candidate)
    matches = list(_REPEATED_BUDGET.finditer(folded))
    if len(matches) != 1 or _money_claims(matches[0].group()) != money_claims:
        return False
    if re.search(r"\b(?:khong|chua)\s+(?:co|tim thay)\b", folded):
        return False
    clause_start = max(folded.rfind(mark, 0, matches[0].start()) for mark in ".!?;,") + 1
    clause_end = min((pos for mark in ".!?;," if (pos := folded.find(mark, matches[0].end())) >= 0),
                     default=len(folded))
    return not _PRICE_CONTEXT.search(folded[clause_start:clause_end])


def check_answer(candidate: str, tool_calls: list[dict[str, Any]],
                 customer_text: str = "", *, focus_sku: str | None = None) -> tuple[str, str | None]:
    if not candidate.strip():
        return FALLBACK, "empty_answer"
    answer = candidate
    candidate = assertion_text(candidate)
    if _customer_erasure_completion_claim(candidate):
        return FALLBACK, "customer_erasure_unverified"
    if _INTERNAL.search(candidate) or _PRICE_REFERENCE.search(candidate):
        return FALLBACK, "unsupported_policy_or_internal_claim"
    successful = [
        call
        for call in tool_calls
        if "error" not in call.get("result", {})
    ]
    policy_claim = bool(candidate.strip() and (_POLICY.search(candidate) or _POLICY.search(customer_text)))
    from app.agent.guardrails.policy_grounding import (policy_evidence_for_answer,
        policy_clarification_or_refusal, policy_durations_supported)
    policy_chunks = policy_evidence_for_answer(candidate, successful)
    if policy_clarification_or_refusal(candidate):
        policy_claim = False
    if policy_claim:
        if not policy_chunks:
            return FALLBACK, "unsupported_policy_or_internal_claim"
        source_text = " ".join(chunk["content"] for chunk in policy_chunks)
        if not policy_durations_supported(candidate, source_text):
            return FALLBACK, "unsupported_policy_or_internal_claim"
    evidenced_skus = known_skus(successful)
    if _SUPERLATIVE.search(candidate):
        return FALLBACK, "unsupported_comparison"
    if _unsupported_feature(candidate, successful):
        return FALLBACK, "unsupported_product_spec"
    customer_budgets = customer_budget_amounts(customer_text)
    def budget_repetition(match):
        amounts = _money_claims(match.group('amount'))
        if len(amounts) == 1 and amounts[0][0] in customer_budgets:
            return ''
        return match.group()
    money_candidate = re.sub(
        r'(?:^|(?<=[.!?;]))\s*(?:(?:Dạ|Vâng)[, ]+)?(?:với |theo )?'
        r'(?:ngân sách của (?:anh/chị|anh|chị|bạn)|(?:anh/chị|anh|chị|bạn) muốn giữ ngân sách)\s+'
        r'(?:là\s+)?(?P<amount>\d[\d.,]*\s*(?:triệu|tr|nghìn|ngàn|k|đồng|đ|vnd))\b',
        budget_repetition, candidate, flags=re.IGNORECASE)
    money_claims = _money_claims(money_candidate)
    if (money_claims and 'gia niem yet' not in _fold_text(candidate)
            and _empty_catalog_budget_evidenced(candidate, customer_text, money_claims, successful)):
        return FALLBACK, 'final_budget_unverified'
    policy_amounts = (_money_claims(" ".join(chunk["content"] for chunk in policy_chunks))
                      if policy_claim else [])
    policy_values = {amount for amount, _, _ in policy_amounts}
    policy_literal = re.sub(r'^Theo thông tin chính sách đã kiểm tra:\s*', '', candidate)
    policy_money_clauses = [clause.strip() for clause in
        re.split(r'[;!?\n]|\.(?!\d)', policy_literal) if _money_claims(clause)]
    exact_policy_quote = bool(policy_claim and policy_money_clauses and all(
        any(' '.join(re.sub(r'[*`_]', '', clause).split()) in
            ' '.join(re.sub(r'[*`_]', '', chunk['content']).split())
            for chunk in policy_chunks)
        for clause in policy_money_clauses))
    if money_claims and not (_money_evidenced(money_candidate, successful, focus_sku=focus_sku) or
                             exact_policy_quote or
                             policy_claim and not re.search(r"(?i)\bgiá(?:\s+bán)?\b", candidate)
                             and all(amount in policy_values
                                     for amount, _, _ in money_claims) or
                             _empty_catalog_budget_evidenced(candidate, customer_text,
                                                              money_claims, successful) or
                             _catalog_budget_repetition_evidenced(candidate, customer_text,
                                                                  money_claims, successful)):
        return FALLBACK, "price_without_quote"
    if _STOCK.search(candidate) or _STOCK_QTY.search(candidate):
        from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
        checks = [call for call in successful if call['name'] == 'inventory.check']
        checks.extend({'name': 'inventory.check', 'args': {'sku': call['result']['replacement_inventory']['sku']},
                       'result': call['result']['replacement_inventory']}
                      for call in successful if call.get('name') == 'order.preview_update'
                      and call.get('result', {}).get('status') == 'preview'
                      and call['result'].get('estimate') is True and call['result'].get('replacement_inventory')
                      and not any(c.get('args', {}).get('sku') == call['result']['replacement_inventory']['sku']
                                  and all(c['result'].get(key) == call['result']['replacement_inventory'].get(key)
                                          for key in ('in_stock', 'qty')) for c in checks))
        for clause in re.split(r'[;!?\n]|\.(?!\d)', candidate):
            if not (_STOCK.search(clause) or _STOCK_QTY.search(clause)):
                continue
            claimed_skus = mentioned_skus(clause, evidenced_skus)
            unverified_legacy_skus = set(_LEGACY_SKU_SIGNAL.findall(clause)) - claimed_skus
            bound = resolve_claim_skus(clause, successful, focus_sku=focus_sku)
            selected = [c for c in checks if not bound or c.get('args', {}).get('sku') in bound]
            if len(bound) > 1 and not any(c.get('args', {}).get('sku') in {
                    item.get('sku') for catalog in successful if catalog.get('name') in CATALOG_TOOLS
                    for item in catalog['result'].get('items', [])} for c in selected):
                return FALLBACK, 'stock_sku_mismatch'
            if len(selected) != 1 or unverified_legacy_skus:
                return FALLBACK, 'stock_sku_mismatch'
            stock = selected[0]['result'].get('in_stock')
            negative_stock = bool(re.search(r'hết hàng|(?:không|chưa)\s+(?:còn hàng|có hàng|có sẵn trong kho)', clause, re.I))
            if _STOCK.search(clause) and (type(stock) is not bool or negative_stock == stock):
                return FALLBACK, 'stock_result_mismatch'
            if any(int(qty) != selected[0]['result'].get('qty') for qty in _STOCK_QTY.findall(clause)):
                return FALLBACK, 'stock_quantity_mismatch'
    asserted_order = _ORDER.search(candidate) or re.search(
        r'(?i)đã\s+ghi nhận\s+đơn hàng|đơn hàng.{0,30}đang được xử lý', candidate)
    if asserted_order and not any(
        call["name"] == "order.create" and call["result"].get("status") == "created"
        for call in successful
    ):
        return FALLBACK, "order_creation_unverified"
    if re.search(r'(?i)đã\s+(?:đặt|tạo|lên|xếp)\s+lịch(?: hẹn)?(?: gọi lại)?', candidate) and not any(
        call['name'] == 'schedule.callback' and call['result'].get('callback_id')
        for call in successful
    ):
        return FALLBACK, 'callback_unverified'
    promotion_reason = check_promotion_grounding(candidate, tool_calls, focus_sku=focus_sku)
    if promotion_reason:
        return FALLBACK, promotion_reason
    if _DELIVERY.search(candidate):
        orders = [call["result"] for call in successful if call["name"] == "order.create"
                  and call["result"].get("status") == "created"]
        delivery_verified = len(orders) == 1 and str(orders[0].get("estimated_delivery")) in candidate
        if not orders and not re.search(r'cam kết|đảm bảo|chắc chắn', candidate, re.IGNORECASE):
            from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
            clauses = [c for c in re.split(r'[;!?\n]|\.(?!\d)', candidate) if _DELIVERY.search(c)]
            delivery_verified = bool(clauses)
            for clause in clauses:
                skus = resolve_claim_skus(clause, successful, focus_sku=focus_sku)
                quotes = [c for c in successful if c['name'] == 'pricing.get_quote'
                          and c.get('args', {}).get('sku') in skus]
                dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', clause)
                if (not re.search(r'\bdự kiến\b', clause, re.IGNORECASE)
                        or len(skus) != 1 or len(quotes) != 1 or len(dates) != 1
                        or dates[0] != quotes[0]['result'].get('estimated_delivery')
                        or re.search(r'\d+\s*(?:ngày|giờ)', clause)):
                    delivery_verified = False
        if not delivery_verified:
            return FALLBACK, "delivery_unverified"
    if any(call['name'] == 'order.status' for call in successful):
        for clause in re.split(r'[;!?\n]|\.(?!\d)', candidate):
            folded = _fold_text(clause)
            if (re.search(r'\bchua (?:duoc )?(?:xac nhan va )?(?:ban giao|xuat kho|giao di)\b|'
                          r'\bvan con o kho\b|\bchua cap nhat (?:thong tin|trang thai) hoan tat giao hang\b', folded)
                    and not re.search(r'\bneu\b', folded)):
                return FALLBACK, 'order_status_unverified'
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
    return mask_pii(answer.strip()), None




class FactRejectReason(StrEnum):

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


def _quote_present(quote: str, customer_text: str) -> bool:
    def light(text: str) -> str:
        return " ".join(unicodedata.normalize("NFC", text).casefold().split())
    return light(quote) in light(customer_text)


def _normalize_slot_value(key: str, value: Any, customer_text: str,
                          evidence_quote: str | None) -> tuple[Any, str | None, FactRejectReason | None]:
    spec = SLOT_SPEC_BY_KEY.get(key)
    if spec is None:
        return value, None, FactRejectReason.UNKNOWN_KEY
    types = spec.value_type if isinstance(spec.value_type, tuple) else (spec.value_type,)
    if type(value) not in types:
        return value, None, FactRejectReason.TYPE_INVALID
    if isinstance(value, str) and (not value.strip() or mask_pii(value) != value):
        return value, None, (FactRejectReason.EMPTY_VALUE if not value.strip()
                             else FactRejectReason.PII_VALUE)
    if evidence_quote is not None and (
            not isinstance(evidence_quote, str) or not evidence_quote.strip()
            or len(evidence_quote) > 200 or mask_pii(evidence_quote) != evidence_quote
            or not _quote_present(evidence_quote, customer_text)):
        return value, None, FactRejectReason.QUOTE_NOT_FOUND
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
    if key not in PROFILE_SLOT_KEYS or _PII_KEY.search(key) or type(value) not in {str, int, float, bool}:
        return None
    if isinstance(value, str) and (not value.strip() or mask_pii(value) != value):
        return None
    spec = SLOT_SPEC_BY_KEY[key]
    if op == "delete" or spec.evidence_source == "customer":
        if (not isinstance(evidence_quote, str) or not evidence_quote.strip()
                or not _quote_present(evidence_quote, customer_text)):
            return None
        if op == "delete" or type(value) is bool or value in spec.allowed_values:
            return "customer"
        if key == Slot.ROOM_AREA_M2:
            supported = _room_area_evidenced(value, evidence_quote)
        elif type(value) in {int, float}:
            supported = bool(re.search(r"(?<![\d.,])" + re.escape(str(value))
                + r"(?![\d.,])", evidence_quote)) or value in {
                    amount for amount, _kind, _negative in _money_claims(evidence_quote)}
        else:
            supported = (bool(re.search(r"(?<!\w)" + re.escape(_fold_text(str(value)))
                + r"(?!\w)", _fold_text(evidence_quote)))
                or evidence_supports(str(value), evidence_quote))
        return "customer" if supported else None
    for call in tool_calls:
        if "error" in call.get("result", {}):
            continue
        name = call["name"]
        result = safe_tool_result(call["result"])
        supported = False
        if key == Slot.PRODUCT_ADVISED and name in CATALOG_TOOLS | {"inventory.check", "pricing.get_quote"}:
            supported = value == result.get("sku") or (
                isinstance(value, str) and isinstance(result.get("sku"), str)
                and result["sku"].startswith(value + "-")
            ) or (
                name in CATALOG_TOOLS
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
        elif key == Slot.VARIANT_SKU and name in CATALOG_TOOLS:
            supported = any(value == variant.get("variant_sku")
                            for item in result.get("items", []) if isinstance(item, dict)
                            for variant in item.get("variants", []) if isinstance(variant, dict))
        elif key == Slot.VARIANT_SKU and name in {"inventory.check", "pricing.get_quote"}:
            supported = (isinstance(value, str) and value == result.get("sku")
                         and value.count("-") >= 4)
        elif key == Slot.VARIANT_SKU and name == "order.create":
            supported = result.get("status") == "created" and value == call.get("args", {}).get("sku")
        elif key == Slot.IN_STOCK and name == "inventory.check":
            supported = value is result.get("in_stock")
        elif key == Slot.ALT_SUGGESTED and name == "inventory.check":
            supported = isinstance(value, str) and value == result.get("successor_sku")
        elif key == Slot.CALLBACK_SCHEDULED and name == "schedule.callback":
            supported = value is True and result.get("status") in {"scheduled", "ok", "created"}
        elif key == Slot.OWNED_SKU and name == "crm.get_customer":
            supported = isinstance(value, str) and any(
                value in {order.get("sku"), order.get("variant_sku")}
                for order in result.get("orders", []) if isinstance(order, dict))
        if supported:
            return f"tool:{name}"
    return None


def fact_evidence(
    key: str, value: Any, op: str, customer_text: str, tool_calls: list[dict[str, Any]],
    evidence_quote: str | None = None,
) -> FactEvidence:
    if key not in PROFILE_SLOT_KEYS:
        return FactEvidence(source=None, reason=FactRejectReason.UNKNOWN_KEY)
    if _PII_KEY.search(key):
        return FactEvidence(source=None, reason=FactRejectReason.PII_KEY)
    if op == "set":
        value, evidence_quote, domain_reason = _normalize_slot_value(
            key, value, customer_text, evidence_quote)
        if domain_reason is not None:
            return FactEvidence(source=None, reason=domain_reason)
    source = _fact_evidence_source(key, value, op, customer_text, tool_calls,
                                   evidence_quote)
    return FactEvidence(source=source, reason=None if source is not None else
                        (FactRejectReason.TOOL_EVIDENCE_MISSING if key in TOOL_ONLY_SLOT_KEYS
                         else FactRejectReason.QUOTE_NOT_FOUND),
                        normalized_value=value if source else None,
                        evidence_quote=evidence_quote if source else None)
