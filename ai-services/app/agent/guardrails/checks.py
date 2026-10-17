"""Small deterministic checks around external model input and output."""

import json
import re
import unicodedata
from typing import Any

from app.mcp_servers.mcp_shared.pii import mask_pii
from app.constants import PROFILE_SLOT_KEYS, TOOL_ONLY_SLOT_KEYS, Slot
from app.agent.guardrails.skus import known_skus, mentioned_skus


FALLBACK = "Dạ, hiện em chưa kiểm tra được thông tin này. Em sẽ nhờ nhân viên hỗ trợ mình ạ."

_STOCK = re.compile(r"(?i)\b(?:còn hàng|có hàng|sẵn hàng|hết hàng)\b")
_ORDER = re.compile(r"(?i)\bđã\s+(?:lên|tạo|đặt|chốt)\s+đơn\b")
_AMOUNT = re.compile(r"(?i)(?<![\w])(\d[\d.,]*)\s*(triệu|tr|nghìn|ngàn|k|đồng|đ|vnd|₫)")
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
_BUDGET = re.compile(
    r"(?i)\b(?:ngân\s*sách|budget|(?:muốn|định|có thể)\s+chi|chi\s+(?:tầm|khoảng))\s+"
    r"(?:(?:anh|chị|em|tôi|mình|nhà mình)\s+)?"
    r"(?:(?:tầm|khoảng|chỉ|là|cỡ)\s+)?"
    r"(?P<amount>\d[\d.,]*\s*(?:triệu|tr|nghìn|ngàn|k|đồng|đ|vnd|₫))"
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


def customer_budget_amounts(customer_text: str) -> set[int]:
    """Only amounts explicitly framed as the customer's spending limit."""
    amounts = {_money_amount(match.group("amount")) for match in _BUDGET.finditer(customer_text)}
    amounts.discard(None)
    folded = _fold_text(customer_text)
    for match in re.finditer(r"\b(?:ngan sach|budget|muon chi|dinh chi|co the chi|chi tam|chi khoang)\b"
                             r"[^.!?;]{0,28}?\b(\d+(?:[.,]\d+)?\s*(?:trieu|tr|nghin|ngan|k)|"
                             r"[a-z]+\s+trieu(?:\s+(?:ruoi|[a-z]+))?)\b", folded):
        raw = match.group(1)
        number = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(trieu|tr|nghin|ngan|k)", raw)
        if number:
            scale = 1_000_000 if number.group(2) in {"trieu", "tr"} else 1_000
            amounts.add(int(float(number.group(1).replace(",", ".")) * scale))
        else:
            words = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5,
                     "sau": 6, "bay": 7, "tam": 8, "chin": 9}
            spoken = re.fullmatch(r"([a-z]+)\s+trieu(?:\s+(ruoi|[a-z]+))?", raw)
            if spoken and spoken.group(1) in words:
                tail = spoken.group(2)
                if tail is None or tail == "ruoi" or tail in words:
                    amounts.add(words[spoken.group(1)] * 1_000_000 +
                                (500_000 if tail == "ruoi" else
                                 words.get(tail, 0) * 100_000))
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
    """Allow repeating the customer's budget when reporting a verified empty search."""
    searches = [call for call in successful if call.get("name") == "catalog.search"]
    if not searches or searches[-1].get("result", {}).get("items") != []:
        return False
    budget = searches[-1].get("args", {}).get("max_price_vnd")
    if budget not in customer_budget_amounts(customer_text):
        return False
    if not re.search(r"\b(?:khong|chua)\s+(?:co|tim thay)\b", _fold_text(candidate)):
        return False
    return bool(money_claims) and all(amount == budget for amount, _, _ in money_claims)


def check_answer(candidate: str, tool_calls: list[dict[str, Any]],
                 customer_text: str = "") -> tuple[str, str | None]:
    """Return a verified answer and a stable, non-sensitive rejection reason."""
    if not candidate.strip():
        return FALLBACK, "empty_answer"
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


def fact_evidence(
    key: str, value: Any, op: str, customer_text: str, tool_calls: list[dict[str, Any]]
) -> str | None:
    """Accept only facts traceable to this customer turn or a successful tool result."""
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
            direct = bool(re.search(rf"\bmau\s+{re.escape(_fold_text(str(value)))}\b", folded_customer))
        elif key == Slot.SIZE:
            direct = bool(re.search(rf"(?i)\bsize\s*{re.escape(str(value))}\b", customer_text))
        elif key == Slot.COLOR:
            direct = bool(re.search(rf"\bmau\s+{re.escape(_fold_text(str(value)))}\b", folded_customer))
        elif key == Slot.PAYMENT:
            payment = str(value).casefold()
            direct = bool(re.search(r"\b(?:thanh toan|tra|ship)\s+" +
                                    re.escape(payment) + r"\b", folded_customer))
        elif key == Slot.OBJECTION:
            direct = value == "dat_qua" and bool(re.search(r"(?i)\b(?:đắt hơn|đắt quá|giá cao)\b", customer_text))
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
