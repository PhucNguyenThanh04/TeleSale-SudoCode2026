"""Small deterministic checks around external model input and output."""

import json
import re
from typing import Any

from app.mcp_servers.mcp_shared.pii import mask_pii
from app.constants import PROFILE_SLOT_KEYS, TOOL_ONLY_SLOT_KEYS, Slot
from app.agent.skus import known_skus, mentioned_skus


FALLBACK = "Dạ, hiện em chưa kiểm tra được thông tin này. Em sẽ nhờ nhân viên hỗ trợ mình ạ."

_MONEY = re.compile(r"(?i)\b(?:\d[\d.,]*\s*(?:triệu|tr|nghìn|ngàn|k|đồng|đ|vnd|₫)|giá\s+(?:là\s+)?\d)")
_STOCK = re.compile(r"(?i)\b(?:còn hàng|có hàng|sẵn hàng|hết hàng)\b")
_ORDER = re.compile(r"(?i)\bđã\s+(?:lên|tạo|đặt|chốt)\s+đơn\b")
_AMOUNT = re.compile(r"(?i)(\d[\d.,]*)\s*(triệu|tr|nghìn|ngàn|k|đồng|đ|vnd|₫)")
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
    r"(?i)\bngân sách\s+(?:(?:tầm|khoảng|chỉ|là|cỡ)\s+)?"
    r"(?P<amount>\d[\d.,]*\s*(?:triệu|tr|nghìn|ngàn|k|đồng|đ|vnd|₫))"
)
_PRODUCT_FEATURE = re.compile(r"(?i)\b(?:HEPA(?:\s*H\d+)?|PM\s*2[.,]5)\b")
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


def _without_confirmed_budget(candidate: str, customer_text: str) -> str:
    customer_budgets = {_money_amount(match.group("amount")) for match in _BUDGET.finditer(customer_text)}
    customer_budgets.discard(None)
    return _BUDGET.sub(
        lambda match: " " if _money_amount(match.group("amount")) in customer_budgets else match.group(),
        candidate,
    )


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


def _unsupported_feature(candidate: str, successful: list[dict[str, Any]]) -> bool:
    catalog_items = [item for call in successful if call["name"] == "catalog.search"
                     for item in call["result"].get("items", []) if isinstance(item, dict)]
    for sentence in re.split(r"[.!?](?!\d)", candidate):
        features = _PRODUCT_FEATURE.findall(sentence)
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
            needle = re.sub(r"\s+", "", feature).casefold().replace(",", ".")
            for item in supported_items:
                attributes = json.dumps(item.get("attributes", {}), ensure_ascii=False).casefold()
                attributes = re.sub(r"\s+", "", attributes).replace(",", ".")
                if needle not in attributes:
                    return True
    return False


def valid_catalog_quote(sku: str, result: Any, *, promotions: bool) -> bool:
    """Check one SKU's dated quote before a catalog-wide answer uses it."""
    if not isinstance(result, dict) or result.get("sku") != sku \
            or type(result.get("final_price_vnd")) is not int:
        return False
    if not promotions:
        return True
    list_price = result.get("list_price_vnd")
    promos = result.get("applied_promos")
    final_price = result["final_price_vnd"]
    if type(list_price) is not int or list_price < final_price \
            or not isinstance(promos, list) or not isinstance(result.get("freeship"), bool):
        return False
    if any(not isinstance(promo, dict) or type(promo.get("discount_vnd")) is not int
           or promo["discount_vnd"] < 0 for promo in promos):
        return False
    return sum(promo["discount_vnd"] for promo in promos) == list_price - final_price


def has_money_claim(text: str) -> bool:
    return bool(_money_claims(text))


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


def check_answer(candidate: str, tool_calls: list[dict[str, Any]],
                 customer_text: str = "") -> tuple[str, str | None]:
    """Return a verified answer and a stable, non-sensitive rejection reason."""
    if not candidate.strip():
        return FALLBACK, "empty_answer"
    if _INTERNAL.search(candidate) or _POLICY.search(candidate) or _PRICE_REFERENCE.search(candidate):
        return FALLBACK, "unsupported_policy_or_internal_claim"
    successful = [
        call
        for call in tool_calls
        if "error" not in call.get("result", {})
    ]
    evidenced_skus = known_skus(successful)
    claimed_skus = mentioned_skus(candidate, evidenced_skus)
    unverified_legacy_skus = set(_LEGACY_SKU_SIGNAL.findall(candidate)) - claimed_skus
    if _SUPERLATIVE.search(candidate):
        return FALLBACK, "unsupported_comparison"
    if _unsupported_feature(candidate, successful):
        return FALLBACK, "unsupported_product_spec"
    money_claims = _money_claims(candidate)
    if money_claims and not _money_evidenced(candidate, successful):
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
    if key not in PROFILE_SLOT_KEYS or _PII_KEY.search(key) or not isinstance(value, (str, int, float, bool)):
        return None
    if isinstance(value, str) and (not value.strip() or mask_pii(value) != value):
        return None
    tool_only_keys = TOOL_ONLY_SLOT_KEYS
    if op == "delete":
        return "customer" if re.search(r"(?i)\b(?:xóa|bỏ|không còn)\b", customer_text) and key in customer_text else None
    if isinstance(value, bool) and key not in tool_only_keys:
        if key == Slot.HAS_CHILDREN and value and re.search(r"(?i)\b(?:bé nhỏ|con nhỏ|có con)\b", customer_text):
            return "customer"
    elif key not in tool_only_keys:
        direct = str(value).lower() in customer_text.lower()
        normalized_money = set()
        for digits, unit in re.findall(r"(?i)\b(\d+(?:[.,]\d+)?)\s*(triệu|tr|nghìn|ngàn|k)\b", customer_text):
            number = float(digits.replace(",", "."))
            normalized_money.add(int(number * (1_000_000 if unit.lower() in {"triệu", "tr"} else 1_000)))
        has_slot_cue = (
            key != Slot.BUDGET_VND or bool(re.search(r"(?i)\b(?:ngân sách|budget|chi khoảng|tầm)\b", customer_text))
        )
        if has_slot_cue and (direct or value in normalized_money):
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
        elif key == Slot.ORDER_ID and name == "order.create":
            supported = result.get("status") == "created" and value == result.get("order_id")
        elif key == Slot.IN_STOCK and name == "inventory.check":
            supported = value is result.get("in_stock")
        if supported:
            return f"tool:{name}"
    return None
