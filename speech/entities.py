"""Trích entity từ transcript dạng viết (sau ITN) theo khóa của ``asr/ground_truth.json`` BTC.

Luật dựa vào cấu trúc câu telesale (từ ngữ cảnh + đơn vị), không dựa vào câu mẫu cụ thể.
Entity cấp hội thoại gộp theo thứ tự lượt: giá trị nói sau ghi đè giá trị nói trước.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from .textutil import fold

REFERENCE_DATE = date(2026, 10, 15)

# ---------------------------------------------------------------------------
# Catalog → SKU
# ---------------------------------------------------------------------------

_MATCH_TOKEN_RE = re.compile(r"[a-z]+(?:&[a-z]+)*|\d+")
_TOKEN_SYNONYMS = {"lit": "l"}
_DISCONTINUED_RE = re.compile(r"\s*[—–-]\s*ngừng bán.*$", re.I)
_ACCESSORY_HINTS = frozenset({"mang", "loi", "combo", "tat", "tui"})
_TRIGGERS = frozenset({"mau", "may", "con", "ban", "loai", "dong", "chiec", "cai", "doi"})
_GENERIC_MODEL = frozenset({"smart"})
_BEFORE_WINDOW = 5
_AFTER_WINDOW = 6


@dataclass(frozen=True)
class Product:
    sku: str
    brand: str                # token hãng đã gấp dấu, ví dụ "airpure"
    model: tuple[str, ...]    # token sau tên hãng: ("smart", "4", "pro")
    prefix: tuple[str, ...]   # token trước tên hãng: ("may", "loc", "khong", "khi")
    accessory: bool = False   # phụ kiện/combo: chỉ nhận khi phía trước có "màng", "lõi", "combo"…


def match_tokens(text: str) -> list[str]:
    return [_TOKEN_SYNONYMS.get(t, t) for t in _MATCH_TOKEN_RE.findall(fold(text))]


def build_catalog(products: list[dict]) -> tuple[Product, ...]:
    parsed = []
    for item in products:
        tokens = match_tokens(_DISCONTINUED_RE.sub("", item["name"]))
        brand = (match_tokens(item.get("brand", "")) or [""])[0]
        if brand in tokens:
            k = tokens.index(brand)
            model, prefix, named = tuple(tokens[k + 1:]), tuple(tokens[:k]), True
        else:
            model, prefix, named = (), tuple(tokens), False
        looks_accessory = not named or bool(_ACCESSORY_HINTS.intersection(prefix[:2]))
        parsed.append((item["sku"], brand, model, prefix, looks_accessory))
    has_main = {brand for _, brand, _, _, acc in parsed if not acc}
    return tuple(Product(sku, brand, model, prefix, acc and brand in has_main)
                 for sku, brand, model, prefix, acc in parsed)


def _score(product: Product, before: list[str], after: list[str]) -> tuple[float, int] | None:
    if product.accessory and not _ACCESSORY_HINTS.intersection(before):
        return None
    matched, pos = 0, 0
    for tok in product.model:
        if tok in after[pos:]:
            pos = after.index(tok, pos) + 1
            matched += 1
    if product.model and not matched:
        return None
    ratio = matched / len(product.model) if product.model else 1.0
    hits = len(set(product.prefix).intersection(before))
    return ratio + 0.25 * hits, matched


def _pick(scored: list[tuple[tuple, str]]) -> str | None:
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None  # mơ hồ: thà bỏ trống còn hơn đoán sai
    return scored[0][1]


def find_skus(text: str, catalog: tuple[Product, ...], last_brand: str | None = None) -> tuple[list[str], str | None]:
    """Các SKU được nhắc trong câu theo thứ tự xuất hiện, và hãng nhắc gần nhất (giữ qua các lượt)."""
    by_brand: dict[str, list[Product]] = {}
    for product in catalog:
        by_brand.setdefault(product.brand, []).append(product)
    tokens = match_tokens(text)
    found: list[str] = []
    for i, tok in enumerate(tokens):
        if tok in by_brand:
            last_brand = tok
            end = next((j for j in range(i + 1, len(tokens)) if tokens[j] in by_brand), len(tokens))
            after = tokens[i + 1:min(end, i + 1 + _AFTER_WINDOW)]
            before = tokens[max(0, i - _BEFORE_WINDOW):i]
            scored = [(s, p.sku) for p in by_brand[tok] if (s := _score(p, before, after))]
            sku = _pick(scored)
        elif tok in _TRIGGERS and last_brand and i + 1 < len(tokens) and tokens[i + 1] not in by_brand:
            # "mẫu x", "bản pro": không nhắc lại tên hãng, khớp đủ model của hãng vừa nói.
            nxt = tokens[i + 1:i + 4]
            scored = []
            for p in by_brand[last_brand]:
                core = tuple(t for t in p.model if t not in _GENERIC_MODEL)
                if not p.accessory and core and tuple(nxt[:len(core)]) == core:
                    scored.append(((len(core), -len(p.model)), p.sku))
            sku = _pick(scored)
        else:
            continue
        if sku:
            found.append(sku)
    return found, last_brand


# ---------------------------------------------------------------------------
# Tiền
# ---------------------------------------------------------------------------

_SCALE = {"tỷ": 10**9, "tỉ": 10**9, "triệu": 10**6, "tr": 10**6, "nghìn": 10**3, "ngàn": 10**3, "k": 10**3}
_NOT_MONEY_AFTER = (r"ngày|tháng|năm|tuổi|lõi|mét|m|lít|l|%|giờ|phút|cái|máy|đôi|chiếc|người|lần|size|"
                    r"nghìn|ngàn|k|triệu|tr|tỷ|tỉ")
_AMOUNT_RE = re.compile(
    r"(?<![\w.,])(?:"
    r"(?P<num>\d+(?:[.,]\d{1,2})?)\s*(?P<scale>tỷ|tỉ|triệu|tr|nghìn|ngàn|k)(?![^\W\d_])"
    r"(?:\s*(?P<half>rưỡi)"
    r"|\s*(?P<sub>\d{1,3})\s*(?P<subscale>nghìn|ngàn|k)(?![^\W\d_])"
    rf"|\s*(?P<tail>\d{{1,3}})(?![\d.,])(?!\s*(?:{_NOT_MONEY_AFTER})(?![^\W\d_])))?"
    r"|(?P<grouped>\d{1,3}(?:[.,]\d{3})+)(?![\d.,]\d)(?:\s*(?:đồng|đ|₫|vnđ|vnd)(?![^\W\d_]))?"
    r"|(?P<plain>\d+)\s*(?:đồng|đ|₫|vnđ|vnd)(?![^\W\d_])"
    r")"
)
_CLAUSE_BREAK_RE = re.compile(
    r"(?<!\d)[,;](?!\d)|[.?!](?!\d)|\s(?:mà|nhưng|so với|trong khi|với lại)\s"
    # "còn" nối hai vế ("giá 5 triệu còn bên kia…"), trừ khi là động từ: "không còn hàng", "còn size 40 không".
    r"|(?<!không)(?<!vẫn)(?<!chưa)(?<!đang)\scòn\s(?!(?:hàng|size|màu|máy|không|nữa|lại)\b)")
_MONEY_KINDS = (
    ("competitor_price_vnd", re.compile(
        r"bên kia|bên khác|chỗ khác|chỗ kia|shop khác|shop kia|cửa hàng khác|nơi khác|trên mạng|người ta|"
        r"shopee|lazada|tiki|tiktok|đối thủ")),
    ("min_free_ship_vnd", re.compile(
        r"đơn (?:hàng )?(?:từ|trên|tối thiểu)|(?:freeship|miễn phí (?:ship|vận chuyển|giao hàng)) (?:cho )?đơn")),
    ("bulky_fee_vnd", re.compile(r"phụ thu|phụ phí|cồng kềnh")),
    ("exchange_fee_vnd", re.compile(r"phí đổi|đổi (?:size|màu|hàng|sản phẩm|mẫu)\b.*(?:mất|phí|tốn)")),
    ("shipping_fee_vnd", re.compile(r"phí (?:ship|vận chuyển|giao)|tiền (?:ship|vận chuyển)|ship (?:mất|hết|là)")),
    # Giá sau giảm là giá, không phải tiền giảm: "giá sau khi giảm là 5 triệu", "áp voucher xong còn …".
    ("price_vnd", re.compile(
        r"sau (?:khi )?(?:được )?(?:giảm|trừ|áp|chiết khấu|khuyến mãi|ưu đãi)|(?:giảm|trừ|áp\b.*) xong")),
    ("discount_vnd", re.compile(r"giảm|bớt|chiết khấu|voucher|\btrừ\b")),
    ("budget_vnd", re.compile(r"ngân sách|budget|tối đa|không quá")),
)
_BUDGET_TAIL_RE = re.compile(r"\s*(?:đồng\s*)?(?:đổ lại|trở xuống|trở lại|là tối đa|là cùng)")
_BUDGET_VAGUE_RE = re.compile(r"\b(?:tầm|khoảng|dưới|chi|mua)\b")


def _clause_start(text: str, pos: int) -> int:
    start = 0
    for m in _CLAUSE_BREAK_RE.finditer(text, 0, pos):
        start = m.end()
    return start


def _clause_end(text: str, pos: int) -> tuple[int, str]:
    m = _CLAUSE_BREAK_RE.search(text, pos)
    return (m.start(), m.group(0)) if m else (len(text), "")


def _amount_value(m: re.Match) -> int | None:
    if m.group("grouped"):
        digits = re.sub(r"\D", "", m.group("grouped"))
        return None if digits.startswith("0") else int(digits)
    if m.group("plain"):
        return int(m.group("plain"))
    scale = _SCALE[m.group("scale")]
    value = float(m.group("num").replace(",", ".")) * scale
    if m.group("half"):
        value += scale / 2
    elif m.group("sub"):
        value += int(m.group("sub")) * _SCALE[m.group("subscale")]
    elif m.group("tail"):
        tail = m.group("tail")
        value += int(tail) * scale / 10 ** len(tail)  # "5 triệu 2" = 5,2 triệu; "5 triệu 200" = 5,2 triệu
    return round(value)


def _money_kind(text: str, start: int, end: int) -> str:
    clause = text[_clause_start(text, start):start]
    for kind, pattern in _MONEY_KINDS:
        if pattern.search(clause):
            return kind
    if _BUDGET_TAIL_RE.match(text, end):
        return "budget_vnd"
    if "giá" in clause:
        return "price_vnd"
    if _BUDGET_VAGUE_RE.search(clause) and not re.search(r"\b(?:là|có|bán)\b", clause):
        return "budget_vnd"
    return "price_vnd"


# ---------------------------------------------------------------------------
# Các entity khác
# ---------------------------------------------------------------------------

_PHONE_RE = re.compile(r"(?<![\d.,])(?:\+84|0)(?:[\s.-]?\d){8,10}(?!\d)")
_ORDER_RE = re.compile(r"\bod[\s-]?(\d{4,})\b", re.I)
_WARRANTY_RE = re.compile(
    r"bảo hành\s+(?:chính hãng\s+|là\s+|trong\s+|tới\s+|đến\s+|lên tới\s+)?(\d+)\s*(tháng|năm)")
_RETURN_RE = re.compile(
    r"(?:đổi trả|trả hàng|hoàn trả|đổi hàng|đổi mới|1 đổi 1|một đổi một)\s+(?:miễn phí\s+)?"
    r"(?:trong\s+(?:vòng\s+)?|tới\s+|lên tới\s+)?(\d+)\s*ngày")
_DAYS_RE = re.compile(r"(?<![\d.,])(\d+)(?:\s*(?:đến|tới|-|–|hoặc)\s*(\d+))?\s*ngày")
_DELIVERY_RE = re.compile(r"giao|ship|vận chuyển|nhận (?:được )?hàng|nhận máy|tới nơi")
_NOT_DELIVERY_RE = re.compile(r"lấy|thu hồi|đổi trả|trả hàng|hoàn tiền|hoàn trả|bảo hành|dùng thử")
_DELIVERY_AFTER_RE = re.compile(r"\s*(?:làm việc\s*)?(?:là\s*)?(?:nhận|tới nơi|giao|có hàng)")
_EXPIRY_RE = re.compile(
    r"(?:đến hết|tới hết|hết|đến|tới|trước|hạn(?: chót)?(?: là)?)\s+(?:ngày\s+)?(\d{1,2})\s*(?:tháng\s*|/)"
    r"(\d{1,2})(?:\s*(?:năm\s*|/)(\d{4}))?")
_PROMO_RE = re.compile(r"khuyến mãi|ưu đãi|tặng|giảm|voucher|chương trình|quà|sale|freeship|flash")
_AREA_RE = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:m2|m²|mét vuông)(?![^\W\d_])")
_ROOM_METER_RE = re.compile(r"phòng\b[^,.;?!]{0,25}?(?<![\d.,])(\d+)\s*(?:mét|m)(?![^\W\d_²2])")
_CHILD_RE = re.compile(
    r"\bcó\s+(?:\d+\s+|một\s+|hai\s+|ba\s+)?(?:bé|cháu|em bé|con nhỏ|con trai|con gái|trẻ nhỏ|trẻ con)\b"
    r"|\b(?:bé|cháu|con)\s+(?:nhà\s+(?:anh|chị|em|mình)\s+)?\d+\s+tuổi")
_NO_CHILD_RE = re.compile(r"\b(?:không|chưa)\s+có\s+(?:bé|cháu|em bé|con|trẻ)")
_BLOCKERS = (
    ("can hoi chong", re.compile(
        r"hỏi (?:ý kiến |lại |qua |thử )?(?:ông xã|chồng|anh xã)|bàn (?:lại )?với (?:ông xã|chồng)")),
    ("can hoi vo", re.compile(
        r"hỏi (?:ý kiến |lại |qua |thử )?(?:bà xã|vợ|bà nhà)|bàn (?:lại )?với (?:bà xã|vợ)")),
)
_HESITATE_RE = re.compile(
    r"cân nhắc|suy nghĩ (?:thêm|lại)|tham khảo thêm|để (?:anh|chị|em|tôi|mình) (?:xem|tính) (?:lại|thêm)|"
    r"báo lại|so sánh thêm")
_COMPARE_RE = re.compile(r"bên kia|bên khác|chỗ khác|shop khác|cửa hàng khác|rẻ hơn|đắt hơn|mắc hơn|so (?:sánh )?giá")
_PAYMENTS = (
    ("COD", re.compile(r"\bcod\b|(?:thanh toán|trả tiền|trả) (?:khi|lúc) nhận|nhận hàng (?:rồi |xong )?(?:mới )?(?:trả|thanh toán)")),
    ("zalopay", re.compile(r"zalo ?pay")),
    ("momo", re.compile(r"\bmomo\b")),
    ("bank", re.compile(r"chuyển khoản|banking|qua ngân hàng|\bck\b")),
)
_SIZE_VALUE = r"(\d{1,2}|xxl|xl|xs|s|m|l)(?!\w)"
_SIZE_CHANGE_RE = re.compile(r"đổi\s+(?:lên|sang|qua|thành|xuống)\s+(?:size\s+|cỡ\s+|số\s+)?" + _SIZE_VALUE)
_SIZE_RE = re.compile(r"\b(?:size|cỡ)\s+" + _SIZE_VALUE)
_COLOR_RE = re.compile(
    r"\bmàu\s+(xanh (?:navy|dương|lá|than|rêu|ngọc)|đen|trắng|xám|ghi|đỏ|xanh|navy|be|nâu|hồng|vàng|tím|cam|kem|bạc)\b")
_OUT_RE = re.compile(r"hết hàng|tạm hết|đang hết|không còn (?:hàng|size|màu|máy)|hết size|hết màu|chưa có hàng|"
                     r"chưa về hàng|cháy hàng|hết sạch")
_IN_RE = re.compile(r"còn hàng|có sẵn|sẵn hàng|có hàng|vẫn còn (?:size|màu|hàng|máy)|hàng về rồi")
_EXCHANGE_ACTION_RE = re.compile(r"\bđổi (?:size|màu|hàng|sản phẩm|mẫu|sang|lên|qua)\b")
_FREE_RE = re.compile(r"miễn phí|không (?:mất|tính|thu) phí|free\b|0 đồng")
_QUESTION_END_RE = re.compile(
    # Không có "à": ASR hay nghe "ạ" thành "à" ("dạ còn hàng à"); câu hỏi "à" thật thì Whisper thường đặt "?".
    r"(?:\b(?:không|chưa|hả|nhỉ|sao|chứ)\b(?:\s+(?:anh|chị|em|ạ|vậy|thế|nhé|nha|bạn|ha|mình))*)\s*$")


def _is_question(text: str, pos: int) -> bool:
    end, brk = _clause_end(text, pos)
    return brk == "?" or bool(_QUESTION_END_RE.search(text[pos:end]))


def _int_or_float(raw: str) -> int | float:
    value = float(raw.replace(",", "."))
    return int(value) if value.is_integer() else value


def _size(raw: str) -> int | str:
    return int(raw) if raw.isdigit() else raw.upper()


def _promo_expiry(text: str, ref: date) -> str | None:
    result = None
    for m in _EXPIRY_RE.finditer(text):
        if not _PROMO_RE.search(text, 0, m.start()):
            continue
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        try:
            when = date(int(year) if year else ref.year, month, day)
            if not year and when < ref - timedelta(days=60):
                when = date(ref.year + 1, month, day)
        except ValueError:
            continue
        result = when.isoformat()
    return result


@dataclass
class _State:
    brand: str | None = None
    size_old: int | str | None = None
    compared: bool = False


def _turn_entities(text: str, state: _State, catalog: tuple[Product, ...], ref: date) -> dict:
    low = text.lower()
    out: dict = {}

    skus, state.brand = find_skus(text, catalog, state.brand)
    if skus:
        out["sku"] = skus[-1]

    for m in _AMOUNT_RE.finditer(low):
        value = _amount_value(m)
        if value:
            out[_money_kind(low, m.start(), m.end())] = value
    if "competitor_price_vnd" in out or _COMPARE_RE.search(low):
        state.compared = True

    for m in _PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        digits = "0" + digits[2:] if m.group(0).startswith("+84") else digits
        if len(digits) in (10, 11):
            out["phone"] = digits
    if orders := _ORDER_RE.findall(text):
        out["order_id"] = "OD" + orders[-1]
    if warranties := _WARRANTY_RE.findall(low):
        n, unit = warranties[-1]
        out["warranty_months"] = int(n) * (12 if unit == "năm" else 1)
    if returns := _RETURN_RE.findall(low):
        out["return_days"] = int(returns[-1])
    for m in _DAYS_RE.finditer(low):
        clause = low[_clause_start(low, m.start()):m.start()]
        keyword = None
        for keyword in _DELIVERY_RE.finditer(clause):
            pass
        before_ok = keyword is not None and not _NOT_DELIVERY_RE.search(clause, keyword.end())
        if before_ok or (_DELIVERY_AFTER_RE.match(low, m.end()) and not _NOT_DELIVERY_RE.search(clause)):
            out["delivery_days"] = max(int(m.group(1)), int(m.group(2) or 0))
    if expiry := _promo_expiry(low, ref):
        out["promo_expiry"] = expiry

    areas = _AREA_RE.findall(low) or _ROOM_METER_RE.findall(low)
    if areas:
        out["room_area_m2"] = _int_or_float(areas[-1])
    if _NO_CHILD_RE.search(low):
        out["has_children"] = False
    elif any(not _is_question(low, m.start()) for m in _CHILD_RE.finditer(low)):
        out["has_children"] = True

    for label, pattern in _BLOCKERS:
        if pattern.search(low):
            out["blocker"] = label
    if "blocker" not in out and state.compared and _HESITATE_RE.search(low):
        out["blocker"] = "so sanh gia"

    payments = sorted((m.start(), label) for label, pattern in _PAYMENTS for m in pattern.finditer(low))
    if payments and not _is_question(low, payments[-1][0]) and not (
            len({label for _, label in payments}) > 1 and re.search(r"\b(?:hay|hoặc)\b", low)):
        out["payment"] = payments[-1][1]

    changes = list(_SIZE_CHANGE_RE.finditer(low))
    if changes:
        out["size_new"] = _size(changes[-1].group(1))
    change_spans = [m.span(1) for m in changes]
    for m in _SIZE_RE.finditer(low):
        if m.span(1) in change_spans:
            continue
        value = _size(m.group(1))
        if state.size_old is None or value == state.size_old:
            state.size_old = value
            out["size_old"] = value
        elif "size_new" not in out:
            out["size_new"] = value
    if colors := _COLOR_RE.findall(low):
        out["color"] = fold(colors[-1])

    outs = [m.span() for m in _OUT_RE.finditer(low) if not _is_question(low, m.start())]
    ins = [m.span() for m in _IN_RE.finditer(low)
           if not _is_question(low, m.start()) and not any(a <= m.start() < b for a, b in outs)]
    if outs or ins:
        out["in_stock"] = max(ins, default=(-1, -1)) > max(outs, default=(-1, -1))

    if "exchange_fee_vnd" not in out:
        for m in _EXCHANGE_ACTION_RE.finditer(low):
            start, (end, _) = _clause_start(low, m.start()), _clause_end(low, m.end())
            if _FREE_RE.search(low, start, end):
                out["exchange_fee_vnd"] = 0
    return out


_TAG_QUESTION_RE = re.compile(
    r"\s*,?\s*\b(?:đúng|phải)\s+(?:không|chưa)\b(?:\s+(?:anh|chị|em|ạ|vậy|nhỉ|nhé|nha|bạn|ha|mình))*\s*\?*", re.I)
_AFFIRM_RE = re.compile(
    r"\W*(?:(?:dạ|vâng|ừ|ừm|ờ|à|ok|okay)\W+)*(?:đúng|phải|chuẩn|chính xác|ok|okay|ừ|ừm|ờ|vâng|rồi)\b"
    r"(?!\s+(?:không|chưa)\b)", re.I)


def _confirmed(m: re.Match, following: str) -> str:
    reply = m.string[m.end():].strip() or following
    return ". " if _AFFIRM_RE.match(reply) else m.group(0)


def _resolve_confirmations(turns: list[str]) -> list[str]:
    """Câu đọc lại để xác nhận ("…thanh toán COD đúng không ạ?") mà được đáp "đúng rồi" thì coi là câu khẳng định."""
    return [_TAG_QUESTION_RE.sub(lambda m: _confirmed(m, following), text)
            for text, following in zip(turns, [*turns[1:], ""])]


def extract_entities(turns: list[str], catalog: tuple[Product, ...] = (),
                     reference_date: date = REFERENCE_DATE) -> tuple[dict, list[dict]]:
    """``turns``: câu dạng viết theo thứ tự thời gian → (entity cấp hội thoại, entity từng lượt)."""
    state = _State()
    per_turn = [_turn_entities(text, state, catalog, reference_date) for text in _resolve_confirmations(turns)]
    merged: dict = {}
    for entities in per_turn:
        merged.update(entities)
    return merged, per_turn
