"""Conservative price intent hints; quote evidence remains the output authority."""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class PriceIntent:
    needs_price: bool
    promotion: bool
    broad: bool
    competitor: bool


def normalize_match_text(text: str) -> tuple[str, str]:
    """Return lower-case NFC tokens and their Vietnamese accent-free counterpart."""
    original = unicodedata.normalize("NFC", text).lower()
    folded = unicodedata.normalize("NFD", original.replace("đ", "d"))
    folded = "".join(char for char in folded if unicodedata.category(char) != "Mn")

    def tokens(value: str) -> str:
        return " " + " ".join(re.findall(r"[^\W_]+|%", value, re.UNICODE)) + " "

    return tokens(original), tokens(folded)


def _contains(forms: tuple[str, str], *phrases: str) -> bool:
    for phrase in phrases:
        variants = normalize_match_text(phrase)
        if any(variant in form for form in forms for variant in variants):
            return True
    return False


_MONEY_TOKEN = re.compile(r" \d[\d.,]*\s*(?:k|tr|trieu|nghin|ngan|dong|vnd|d|%) ")
_DISCOUNT_AMOUNT = re.compile(r" (?:giam|giam gia) \d[\d.,]*\s*(?:k|tr|trieu|nghin|ngan|dong|vnd|d|%) ")
_BAO_NHIEU = re.compile(r" (?:bao nhieu|bao nhiu|bn|bnh) ")
_NON_PRICE_UNIT = re.compile(r" (?:\d+\s*)?(?:m2|met|vuong|dien|on|bui|mui|watt|kwh) ")


def detect_price_intent(text: str) -> PriceIntent:
    forms = normalize_match_text(text)
    plain = forms[1]
    competitor = _contains(forms, "bên kia", "bên khác", "shop khác", "đối thủ")
    broad = _contains(forms, "loại nào", "mẫu nào", "máy nào", "sản phẩm nào",
                      "các mẫu", "các loại", "những mẫu", "giá các", "giá những")
    promotion = (_contains(forms, "khuyến mãi", "ưu đãi", "sale", "giảm giá",
                           "giảm %", "mã giảm", "có km", "km gì", "km nào", "đang km")
                 or bool(_DISCOUNT_AMOUNT.search(plain)))
    explicit_price = _contains(forms, "giá", "bao nhiêu tiền", "bao nhiu tiền",
                               "bn tiền", "bnh tiền", "mấy tiền", "hết bao nhiêu",
                               "tổng cộng bao nhiêu", "giá bao nhiêu", "giá bn", "giá bnh")
    # "bao nhiêu" alone describes size, power and filtration as often as money.
    quantity_question = bool(_BAO_NHIEU.search(plain)) and not _NON_PRICE_UNIT.search(plain)
    comparison = competitor and (_MONEY_TOKEN.search(plain) is not None or
                                 _contains(forms, "đắt hơn", "rẻ hơn", "bán"))
    needs_price = promotion or explicit_price or comparison or (
        quantity_question and _contains(forms, "hết", "tổng cộng", "phải trả")
    ) or (broad and not _NON_PRICE_UNIT.search(plain))
    # "gia tăng" is the verb, unlike "giá tăng".
    if _contains((forms[0], forms[0]), "gia tăng") and not promotion and not comparison:
        needs_price = False
    return PriceIntent(needs_price=needs_price, promotion=promotion,
                       broad=broad, competitor=competitor)
