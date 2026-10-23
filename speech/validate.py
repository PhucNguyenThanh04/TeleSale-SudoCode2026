"""Kiểm kịch bản hội thoại tự viết trước khi tạo audio: ``python -m speech validate --dialogues <file>...``.

Ba lớp kiểm, theo thứ tự nguồn chuẩn của BTC (schema/mock_tools/reference_eval):

1. Định dạng — cùng format ``asr/ground_truth.json`` + trường riêng của nhóm (``split``, ``call_date``,
   ``tool_context``, ``checks``); nhãn chỉ dùng khóa entity BTC; entity hội thoại = gộp entity các lượt.
2. Dạng nói — ``text`` là đúng chữ người đọc nói ra (số bằng chữ, không ký hiệu); giá trị nhãn phải được nói
   ra trong chính lượt đó (đọc qua bộ chuẩn hóa ITN của pipeline).
3. Sự thật — giá/KM/tồn kho/bảo hành/phí… khớp ``eval/mock_tools.py`` của BTC tại ``call_date`` của từng hội
   thoại; mục ``checks`` gọi thẳng tool BTC cho các khẳng định không gắn nhãn (KM chưa bắt đầu, hết hạn…).

``error`` phải sửa trước khi tạo audio; ``warn`` cần người đọc lại; ``info`` chỉ để báo cáo.
"""
from __future__ import annotations

import inspect
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import ModuleType

from .btc import load_catalog, load_mock_tools, read_json
from .team import KH, TEAM_VOICE_RE, VOICE_FIELDS, is_template
from .entities import _AMOUNT_RE, _FREE_RE, _PAYMENTS, Product, _amount_value, extract_entities, match_tokens
from .normalize import normalize_text
from .textutil import btc_norm, fold
from .tts import DEFAULT_ELEVEN_MODEL, credits_per_char

# Khóa entity có trong asr/ground_truth.json BTC và đề bài (mục 3.1–3.3).
ENTITY_KEYS = frozenset({
    "sku", "price_vnd", "room_area_m2", "blocker", "order_id", "has_children", "budget_vnd", "promo_expiry",
    "delivery_days", "payment", "warranty_months", "competitor_price_vnd", "return_days", "min_free_ship_vnd",
    "bulky_fee_vnd", "phone", "size_old", "color", "size_new", "exchange_fee_vnd", "in_stock"})
MONEY_KEYS = frozenset({"price_vnd", "budget_vnd", "competitor_price_vnd", "min_free_ship_vnd", "bulky_fee_vnd",
                        "exchange_fee_vnd"})
INT_KEYS = MONEY_KEYS | {"room_area_m2", "delivery_days", "warranty_months", "return_days"}
BOOL_KEYS = frozenset({"has_children", "in_stock"})
BLOCKERS = frozenset({"can hoi chong", "can hoi vo", "so sanh gia"})
SPLITS = frozenset({"dev", "holdout"})
TTS_ENGINES = frozenset({"elevenlabs", "vieneu", "edge", "files"})

# Chính sách BTC (policy/van-chuyen-thanh-toan.md, doi-tra-bao-hanh.md) và mock_tools.py.
FREE_SHIP_DEFAULT_VND = 2_000_000          # VC-02, mock: freeship nếu giá ≥ 2 triệu
BULKY_FEE_VND = 30_000                     # VC-02: hàng cồng kềnh ngoài nội thành
BULKY_HINTS = ("may loc nuoc", "xe day", "ghe o to")
EXCHANGE_FEES_VND = frozenset({0, 30_000, 60_000})  # DT-03: lần đầu miễn phí, lần 2+ 30k/chiều (mock: 60k)
COD_LIMIT_VND = 10_000_000                 # VC-04, mock order_create
DELIVERY_DAYS = frozenset({2, 3, 4, 5, 7})  # cận trên các khung VC-01
RETURN_DAYS = {"thoi-trang": frozenset({7})}  # DT-01; gia dụng/mẹ bé: 7 ngày đổi trả, 30 ngày đổi mới lỗi NSX
RETURN_DAYS_DEFAULT = frozenset({7, 30})

# Ước lượng thời lượng: tốc độ edge-tts đo trên dataset cũ (nhật ký bước 15) + khoảng nghỉ trung bình synth.
SYLLABLES_PER_S = 4.3
TURN_GAP_S = 0.525
LEAD_S = 0.3
TURNS_RANGE = (7, 10)
SECONDS_RANGE = (45.0, 75.0)

_PHONE_FORMAT = re.compile(r"^0\d{9}$")
_ORDER_FORMAT = re.compile(r"^OD\d{6}$")
_MOCK_ORDER_RANGE = re.compile(r"^OD6\d{5}$")  # mock order_create sinh OD600001+
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")
_BAD_CHARS_RE = re.compile(r"[^\w\s,.?!…;:'’\-–]|_")
_SYLLABLE_RE = re.compile(r"[^\W\d_]+")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
# Size chữ đọc kiểu Việt (luật chuẩn hóa chưa đổi về chữ cái — xem giới hạn trong nhật ký).
_SIZE_LETTERS = {"S": ("size ét",), "M": ("size em", "size mờ"), "L": ("size lờ", "size eo"),
                 "XL": ("size ích xờ lờ", "size ích eo", "size ếch eo")}
# Ngữ cảnh biến thể lấy từ lời thoại khi lượt không gắn nhãn size/màu (vd hỏi mua mới, không phải đổi size).
_CTX_SIZE_RE = re.compile(r"\bsize (\d{2}|xl|s|m|l)\b")
_CTX_COLOR_RE = re.compile(r"\bmau (den|trang|xam|navy|be)\b")


@dataclass
class Issue:
    level: str          # error | warn | info
    dialogue: str
    turn: int | None
    message: str

    def __str__(self) -> str:
        where = self.dialogue + (f"#{self.turn}" if self.turn is not None else "")
        return f"[{self.level.upper()}] {where}: {self.message}"


@dataclass
class DialogueStats:
    id: str
    file: str
    split: str | None
    noisy: bool
    engine: str | None
    n_turns: int
    syllables: int
    est_s: float
    chars: int
    credits: float
    oracle: tuple[int, int] = (0, 0)
    roundtrip_diff: int = 0


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    stats: list[DialogueStats] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warn"]


class _Sink:
    def __init__(self, report: Report, dialogue: str):
        self.report, self.dialogue = report, dialogue

    def __call__(self, level: str, message: str, turn: int | None = None) -> None:
        self.report.issues.append(Issue(level, self.dialogue, turn, message))


# ---------------------------------------------------------------------------
# Dữ liệu tham chiếu
# ---------------------------------------------------------------------------

@dataclass
class Reference:
    data_dir: Path
    catalog: tuple[Product, ...]
    products: dict[str, dict]
    holidays: frozenset[str]
    known_phones: frozenset[str]
    known_orders: frozenset[str]

    @classmethod
    def load(cls, data_dir: Path) -> "Reference":
        mock = load_mock_tools(data_dir)
        phones, orders = set(), set()
        for customer in mock.CRM:
            phones.add(customer["phone"])
            orders.update(o["order_id"] for o in customer.get("orders", []))
        gt_path = data_dir / "asr" / "ground_truth.json"
        if gt_path.is_file():
            for dialogue in read_json(gt_path)["dialogues"]:
                for turn in dialogue["turns"]:
                    entities = turn.get("entities") or {}
                    if entities.get("phone"):
                        phones.add(entities["phone"])
                    if entities.get("order_id"):
                        orders.add(entities["order_id"])
        return cls(data_dir, load_catalog(data_dir), {p["sku"]: p for p in mock.PRODUCTS},
                   frozenset(mock.HOLIDAYS), frozenset(phones), frozenset(orders))

    def fresh_mock(self, overlay: list[dict] | None = None) -> ModuleType:
        mock = load_mock_tools(self.data_dir)
        if overlay:
            mock.CRM = list(mock.CRM) + list(overlay)  # CRM giả lập trong bộ nhớ, không sửa file BTC
        return mock


# ---------------------------------------------------------------------------
# Tiện ích
# ---------------------------------------------------------------------------

def _iso(value) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def syllables(text: str) -> int:
    return len(_SYLLABLE_RE.findall(text.replace(KH, "anh")))


def estimate_seconds(texts: list[str]) -> float:
    return LEAD_S + len(texts) * TURN_GAP_S + sum(syllables(t) for t in texts) / SYLLABLES_PER_S


def merge_turn_entities(turns: list[dict]) -> dict:
    merged: dict = {}
    for turn in turns:
        merged.update(turn.get("entities") or {})
    return merged


def _numbers(written: str) -> set[float]:
    return {float(n.replace(",", ".")) for n in _NUMBER_RE.findall(written)}


def _active(promo: dict, on: str) -> bool:
    return promo["start"] <= on <= promo["end"]


def _promo_targets(mock: ModuleType, promo: dict, sku: str) -> bool:
    parent, _ = mock._parent(sku)
    if parent is None:
        return False
    targets = promo["applies_to"]
    return ("*" in targets or parent["sku"] in targets
            or any(t.startswith("category:") and parent["category"].startswith(t.split(":", 1)[1]) for t in targets))


def _subset(expected, actual) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(expected) == len(actual)
                and all(_subset(e, a) for e, a in zip(expected, actual)))
    return expected == actual


def _codes(items: list) -> set[str]:
    return {i["promo_code"] if isinstance(i, dict) else i for i in items or []}


# ---------------------------------------------------------------------------
# Lớp 1 — định dạng
# ---------------------------------------------------------------------------

def _check_header(source: dict, file: str, report: Report) -> tuple[str, tuple[str, str] | None, str | None]:
    sink = _Sink(report, file)
    ref = source.get("reference_date", "2026-10-15")
    if _iso(ref) is None:
        sink("error", f"reference_date không phải ngày ISO: {ref!r}")
    window = source.get("call_date_range")
    if window is not None and not (isinstance(window, list) and len(window) == 2 and all(_iso(x) for x in window)):
        sink("error", "call_date_range phải là [ngày đầu, ngày cuối] dạng ISO")
        window = None
    engine = source.get("tts_engine")
    if engine is not None and engine not in TTS_ENGINES:
        sink("error", f"tts_engine {engine!r} không thuộc {sorted(TTS_ENGINES)}")
    if not isinstance(source.get("dialogues"), list) or not source["dialogues"]:
        sink("error", "thiếu danh sách dialogues")
    return ref, (tuple(window) if window else None), engine


def _check_format(d: dict, sink: _Sink, ref_date: str, window, holidays: frozenset[str]) -> None:
    if d.get("split") not in SPLITS:
        sink("error", f"split phải là {sorted(SPLITS)} (dev để chỉnh pipeline, holdout chỉ chấm cuối)")
    if not isinstance(d.get("noisy"), bool):
        sink("error", "noisy phải là true/false")
    call_date = d.get("call_date")
    when = _iso(call_date)
    if when is None:
        sink("error", f"call_date thiếu hoặc không phải ngày ISO: {call_date!r}")
    else:
        if call_date < ref_date:
            sink("error", f"call_date {call_date} trước reference_date {ref_date}")
        if window and not (window[0] <= call_date <= window[1]):
            sink("error", f"call_date {call_date} ngoài call_date_range {list(window)}")
        if call_date in holidays:
            sink("error", f"call_date {call_date} là ngày nghỉ toàn công ty (LN-02) — không có cuộc gọi")
        if when.weekday() == 6:
            sink("warn", f"call_date {call_date} là Chủ nhật: chỉ nhận đơn, không xử lý đổi trả/khiếu nại (LN-01)")

    if is_template(d):
        keys = [d.get(fields[0]) for fields in VOICE_FIELDS.values()]
        for key in keys:
            if not (isinstance(key, str) and TEAM_VOICE_RE.match(key)):
                sink("error", f"khóa giọng {key!r} phải là tv1, tv2 hoặc tv3")
        if keys[0] == keys[1]:
            sink("error", "nhân viên và khách không được cùng một giọng")
        for _, region_field, gender_field in VOICE_FIELDS.values():
            if region_field in d or gender_field in d:
                sink("warn", f"bản mẫu không nên ghi sẵn {region_field}/{gender_field} — điền từ team_voices.json")
    else:
        for _, region_field, gender_field in VOICE_FIELDS.values():
            if d.get(region_field) not in ("bac", "trung", "nam"):
                sink("error", f"{region_field} phải là bac, trung hoặc nam")
            if d.get(gender_field) not in ("f", "m"):
                sink("error", f"{gender_field} phải là f hoặc m")

    turns = d.get("turns")
    if not isinstance(turns, list) or not turns:
        sink("error", "thiếu turns")
        return
    for position, turn in enumerate(turns, start=1):
        if turn.get("idx") != position:
            sink("error", f"idx phải liên tục từ 1 (gặp {turn.get('idx')!r} ở vị trí {position})", position)
        if turn.get("speaker") not in ("A", "C"):
            sink("error", "speaker phải là A (nhân viên) hoặc C (khách)", position)
        if not isinstance(turn.get("text"), str) or not turn["text"].strip():
            sink("error", "text rỗng", position)
        if "tts_text" in turn and not (isinstance(turn["tts_text"], str) and turn["tts_text"].strip()):
            sink("error", "tts_text rỗng", position)
        if not isinstance(turn.get("entities", {}), dict):
            sink("error", "entities phải là object", position)
    if "n_turns" in d and d["n_turns"] != len(turns):
        sink("error", f"n_turns {d['n_turns']} ≠ số lượt {len(turns)}")
    if "full_text" in d and d["full_text"] != " ".join(t.get("text", "") for t in turns):
        sink("error", "full_text khác nối text các lượt — bỏ full_text đi, synth tự sinh")
    if not TURNS_RANGE[0] <= len(turns) <= TURNS_RANGE[1]:
        sink("warn", f"{len(turns)} lượt, ngoài khoảng {TURNS_RANGE[0]}–{TURNS_RANGE[1]} như dữ liệu BTC")


# ---------------------------------------------------------------------------
# Lớp 2 — dạng nói và nhãn
# ---------------------------------------------------------------------------

def _check_spoken(turn: dict, sink: _Sink, template: bool) -> None:
    idx = turn.get("idx")
    for name in ("text", "tts_text"):
        text = turn.get(name)
        if not isinstance(text, str):
            continue
        if unicodedata.normalize("NFC", text) != text:
            sink("error", f"{name} chưa ở dạng Unicode NFC", idx)
        if re.search(r"\d", text):
            sink("error", f"{name} có chữ số — viết số bằng chữ như lời nói ({text!r})", idx)
        for placeholder in _PLACEHOLDER_RE.findall(text):
            if placeholder != KH or not template:
                sink("error", f"{name} có chỗ trống {placeholder} (chỉ bản mẫu clone được dùng {KH})", idx)
        bad = sorted(set(_BAD_CHARS_RE.findall(_PLACEHOLDER_RE.sub("", text))))
        if bad:
            sink("error", f"{name} có ký tự không đọc được thành lời: {''.join(bad)!r}", idx)
    text = turn.get("text", "")
    if isinstance(text, str) and text != text.lower():
        sink("warn", "text nên viết thường như ground truth BTC (chữ hoa chỉ dùng trong tts_text)", idx)


def _check_labels(turn: dict, sink: _Sink, ref: Reference, written: str) -> None:
    idx = turn.get("idx")
    low = written.lower()
    tokens = set(match_tokens(written))
    for key, value in (turn.get("entities") or {}).items():
        if key not in ENTITY_KEYS:
            sink("error", f"khóa entity {key!r} không có trong bộ nhãn BTC", idx)
            continue
        if key in BOOL_KEYS:
            if not isinstance(value, bool):
                sink("error", f"{key} phải là true/false", idx)
            continue
        if key in INT_KEYS and (isinstance(value, bool) or not isinstance(value, int)):
            sink("error", f"{key} phải là số nguyên (đồng/ngày/tháng/m2)", idx)
            continue
        if key == "phone" and not (isinstance(value, str) and _PHONE_FORMAT.match(value)):
            sink("error", f"phone {value!r} phải là chuỗi 10 số bắt đầu bằng 0", idx)
            continue
        if key == "order_id" and not (isinstance(value, str) and _ORDER_FORMAT.match(value)):
            sink("error", f"order_id {value!r} phải dạng OD + 6 số", idx)
            continue
        if key == "promo_expiry" and _iso(value) is None:
            sink("error", f"promo_expiry {value!r} phải là ngày ISO như BTC (2026-10-22)", idx)
            continue
        if key == "payment" and value not in dict(_PAYMENTS):
            sink("error", f"payment {value!r} phải thuộc {sorted(dict(_PAYMENTS))}", idx)
            continue
        if key == "blocker" and value not in BLOCKERS:
            sink("warn", f"blocker {value!r} ngoài các giá trị BTC dùng {sorted(BLOCKERS)}", idx)
        if key == "sku":
            product = ref.products.get(value)
            if product is None:
                sink("error", f"sku {value!r} không có trong catalog (nhãn dùng SKU gốc, không dùng SKU biến thể)", idx)
                continue
            if product["attributes"].get("discontinued"):
                sink("error", f"sku {value} đã ngừng bán — nhãn phải là sản phẩm đang tư vấn", idx)
        if key == "phone" and value in ref.known_phones:
            sink("error", f"SĐT {value} trùng CRM/ground truth BTC — dùng số giả khác", idx)
        if key == "order_id":
            if value in ref.known_orders:
                sink("error", f"mã đơn {value} trùng CRM/ground truth BTC — dùng mã giả khác", idx)
            elif _MOCK_ORDER_RANGE.match(value):
                sink("warn", f"mã đơn {value} nằm trong dải mock order_create sinh ra (OD6xxxxx)", idx)

        spoken = _spoken_in_turn(key, value, low, tokens, ref)
        if spoken is False:
            level = "warn" if key in ("sku", "size_old", "size_new", "color", "payment") else "error"
            sink(level, f"nhãn {key}={value!r} không thấy được nói ra trong lượt này (dạng viết: {written!r})", idx)


def _spoken_in_turn(key: str, value, low: str, tokens: set[str], ref: Reference) -> bool | None:
    numbers = _numbers(low)
    if key in MONEY_KEYS:
        if value == 0:
            return bool(_FREE_RE.search(low))
        amounts = {_amount_value(m) for m in _AMOUNT_RE.finditer(low)}
        amounts |= {int(n) for n in re.findall(r"(?<![\d.,])\d{4,}(?![\d.,])", low)}  # "1161000" không kèm đơn vị
        return value in amounts
    if key == "phone":
        return value in re.sub(r"[\s.\-]", "", low)
    if key == "order_id":
        return value.lower() in re.sub(r"[\s\-]", "", low)
    if key in ("room_area_m2", "delivery_days", "return_days"):
        return float(value) in numbers
    if key == "warranty_months":
        return float(value) in numbers or (value % 12 == 0 and float(value // 12) in numbers)
    if key == "promo_expiry":
        when = date.fromisoformat(value)
        return bool(re.search(rf"(?<!\d){when.day}\s*(?:tháng\s*|/){when.month}(?!\d)", low))
    if key in ("size_old", "size_new"):
        spoken_letters = _SIZE_LETTERS.get(str(value).upper(), ())
        return str(value).lower() in tokens or any(re.search(rf"\b{s}\b", low) for s in spoken_letters)
    if key == "color":
        return value in tokens
    if key == "payment":
        return bool(dict(_PAYMENTS)[value].search(low))
    if key == "sku":
        product = next((p for p in ref.catalog if p.sku == value), None)
        if product is None:
            return None
        distinctive = ({product.brand} | set(product.model)) - {"smart"}
        return bool(tokens & distinctive)
    return None


# ---------------------------------------------------------------------------
# Lớp 3 — sự thật theo mock_tools BTC tại call_date
# ---------------------------------------------------------------------------

@dataclass
class _Context:
    sku: str | None = None
    size: int | str | None = None
    color: str | None = None
    price: int | None = None


def _resolve(mock: ModuleType, ctx: _Context) -> tuple[str | None, bool]:
    """SKU gốc trong nhãn + size/màu đã nói → (SKU để gọi tool, đã xác định được biến thể?)."""
    if ctx.sku is None:
        return None, False
    product = mock._BY_SKU.get(ctx.sku)
    if not product or not product["variants"]:
        return ctx.sku, True
    matches = [v for v in product["variants"]
               if (ctx.size is None or str(v["size"]).upper() == str(ctx.size).upper())
               and (ctx.color is None or v["color"] == ctx.color)]
    if len(matches) == 1:
        return matches[0]["variant_sku"], True
    return ctx.sku, False


def _quote(mock: ModuleType, sku: str, on: str, tool_context: dict) -> dict:
    basket = [s for s in tool_context.get("basket_skus", []) if s != sku]
    return mock.pricing_get_quote(sku, on, 1, tool_context.get("customer_phone"), tool_context.get("address"),
                                  basket or None)


def _check_facts(d: dict, sink: _Sink, ref: Reference) -> None:
    on = d.get("call_date")
    if _iso(on) is None:
        return
    tool_context = d.get("tool_context") or {}
    overlay = tool_context.get("crm_overlay") or []
    for customer in overlay:
        if customer.get("phone") in ref.known_phones:
            sink("error", f"crm_overlay dùng SĐT {customer.get('phone')} trùng CRM/ground truth BTC")
        for order in customer.get("orders", []):
            if order.get("order_id") in ref.known_orders:
                sink("error", f"crm_overlay dùng mã đơn {order.get('order_id')} trùng CRM/ground truth BTC")
    mock = ref.fresh_mock(overlay)
    ctx = _Context()
    for turn in d.get("turns", []):
        idx, labels = turn.get("idx"), turn.get("entities") or {}
        if labels.get("sku") in mock._BY_SKU:
            if labels["sku"] != ctx.sku:
                ctx.size = ctx.color = None
            ctx.sku = labels["sku"]
        _variant_from_text(turn, ctx)
        for key in ("size_old", "size_new"):  # size_new sau cùng → đang nói về size mới
            if key in labels:
                ctx.size = labels[key]
        if "color" in labels:
            ctx.color = labels["color"]
        _check_turn_facts(labels, idx, ctx, mock, on, tool_context, sink)
        if isinstance(labels.get("price_vnd"), int):
            ctx.price = labels["price_vnd"]
    for number, check in enumerate(d.get("checks") or [], start=1):
        _run_check(check, number, mock, on, tool_context, sink)


def _variant_from_text(turn: dict, ctx: _Context) -> None:
    """Size/màu nói đúng một lần trong lượt → cập nhật ngữ cảnh (nhắc nhiều giá trị thì giữ nguyên)."""
    written = fold(normalize_text(str(turn.get("text", "")).replace(KH, "anh")).written)
    sizes = {m.upper() for m in _CTX_SIZE_RE.findall(written)}
    colors = set(_CTX_COLOR_RE.findall(written))
    if len(sizes) == 1:
        size = sizes.pop()
        ctx.size = int(size) if size.isdigit() else size
    if len(colors) == 1:
        ctx.color = colors.pop()


def _check_turn_facts(labels: dict, idx, ctx: _Context, mock: ModuleType, on: str, tool_context: dict,
                      sink: _Sink) -> None:
    target, resolved = _resolve(mock, ctx)
    product = mock._BY_SKU.get(ctx.sku) if ctx.sku else None
    category = product["category"] if product else ""

    for key in ("size_old", "size_new", "color"):
        if key in labels and product is not None:
            field_name = "color" if key == "color" else "size"
            options = {str(v[field_name]).upper() for v in product["variants"]}
            if str(labels[key]).upper() not in options:
                sink("error", f"{ctx.sku} không có {field_name} {labels[key]!r} (có: {sorted(options) or 'không biến thể'})",
                     idx)

    if "price_vnd" in labels and isinstance(labels["price_vnd"], int):
        if target is None:
            sink("warn", "có price_vnd nhưng chưa có sku trong ngữ cảnh — không kiểm được giá", idx)
        else:
            quote = _quote(mock, target, on, tool_context)
            allowed = {quote["list_price_vnd"], quote["final_price_vnd"]}
            if labels["price_vnd"] not in allowed:
                sink("error", f"giá {labels['price_vnd']:,} không khớp {target} ngày {on}: niêm yết "
                              f"{quote['list_price_vnd']:,}, giá cuối {quote['final_price_vnd']:,} "
                              f"(KM áp: {sorted(_codes(quote['applied_promos']))})", idx)

    if "in_stock" in labels and isinstance(labels["in_stock"], bool):
        if target is None or not resolved:
            sink("warn", f"có in_stock nhưng chưa xác định sản phẩm/biến thể ({ctx.sku}, size {ctx.size}, "
                         f"màu {ctx.color})", idx)
        else:
            stock = mock.inventory_check(target, on)
            if stock.get("in_stock") != labels["in_stock"]:
                sink("error", f"tồn kho {target} ngày {on}: {stock} ≠ nhãn in_stock={labels['in_stock']}", idx)

    if "promo_expiry" in labels and _iso(labels["promo_expiry"]):
        active = [p for p in mock.PROMOS if _active(p, on) and (ctx.sku is None or _promo_targets(mock, p, ctx.sku))]
        ends = {p["end"]: p["promo_code"] for p in active}
        if labels["promo_expiry"] not in ends:
            sink("error", f"promo_expiry {labels['promo_expiry']} không là ngày hết hạn của KM đang chạy ngày {on}"
                          f"{' cho ' + ctx.sku if ctx.sku else ''}: {ends}", idx)

    if "warranty_months" in labels and product is not None:
        months = product["attributes"].get("warranty_months")
        if months != labels["warranty_months"]:
            sink("error", f"bảo hành {ctx.sku} theo catalog là {months} tháng, nhãn {labels['warranty_months']}", idx)

    if "return_days" in labels:
        allowed = RETURN_DAYS.get(category.split("/")[0], RETURN_DAYS_DEFAULT)
        if labels["return_days"] not in allowed:
            sink("error", f"return_days {labels['return_days']} không khớp chính sách ({sorted(allowed)})", idx)

    if "min_free_ship_vnd" in labels:
        allowed = {FREE_SHIP_DEFAULT_VND}
        for promo in mock.PROMOS:
            if promo["type"] == "freeship" and promo.get("min_order_vnd") and _active(promo, on) and (
                    ctx.sku is None or _promo_targets(mock, promo, ctx.sku)):
                allowed.add(promo["min_order_vnd"])
        if labels["min_free_ship_vnd"] not in allowed:
            sink("error", f"ngưỡng freeship {labels['min_free_ship_vnd']:,} không đúng ngày {on} (hợp lệ: "
                          f"{sorted(allowed)})", idx)

    if "bulky_fee_vnd" in labels:
        if labels["bulky_fee_vnd"] != BULKY_FEE_VND:
            sink("error", f"phụ phí cồng kềnh là {BULKY_FEE_VND:,} (VC-02)", idx)
        elif product is not None and not any(h in fold(product["name"]) or h.replace(" ", "-") in category
                                             for h in BULKY_HINTS):
            sink("warn", f"{ctx.sku} không thuộc nhóm cồng kềnh (máy lọc nước, xe đẩy, ghế ô tô)", idx)

    if "exchange_fee_vnd" in labels and labels["exchange_fee_vnd"] not in EXCHANGE_FEES_VND:
        sink("error", f"phí đổi {labels['exchange_fee_vnd']:,} không khớp DT-03 ({sorted(EXCHANGE_FEES_VND)})", idx)

    if "delivery_days" in labels and labels["delivery_days"] not in DELIVERY_DAYS:
        sink("error", f"delivery_days {labels['delivery_days']} không là cận trên khung giao VC-01 "
                      f"({sorted(DELIVERY_DAYS)})", idx)

    if labels.get("payment") == "COD" and ctx.price and ctx.price > COD_LIMIT_VND:
        sink("error", f"COD không nhận đơn trên {COD_LIMIT_VND:,} (giá đang nói {ctx.price:,})", idx)


_TOOLS = {"catalog.search": "catalog_search", "inventory.check": "inventory_check",
          "pricing.get_quote": "pricing_get_quote", "order.create": "order_create", "order.status": "order_status",
          "order.update": "order_update", "schedule.callback": "schedule_callback",
          "crm.get_customer": "crm_get_customer"}


def _run_check(check: dict, number: int, mock: ModuleType, on: str, tool_context: dict, sink: _Sink) -> None:
    """``{"tool", "args", "expect", "applied", "not_applied", "expired", "ineligible", "why", "turn"}``."""
    tool, turn = check.get("tool"), check.get("turn")
    label = f"check {number} ({tool})"
    if not check.get("why"):
        sink("warn", f"{label}: thiếu 'why' (khẳng định nào trong lời thoại cần kiểm)", turn)
    args = dict(check.get("args") or {})
    try:
        if tool == "delivery.eta":  # ngày giao dự kiến như order_create trả về
            result = mock._eta(args.get("on", on), args.get("address", tool_context.get("address")))
        elif tool in _TOOLS:
            func = getattr(mock, _TOOLS[tool])
            if "on" in inspect.signature(func).parameters:
                args.setdefault("on", on)
            result = func(**args)
        else:
            sink("error", f"{label}: tool không có trong mock BTC ({sorted(_TOOLS) + ['delivery.eta']})", turn)
            return
    except TypeError as err:
        sink("error", f"{label}: tham số sai — {err}", turn)
        return
    if "expect" in check and not _subset(check["expect"], result):
        sink("error", f"{label}: kết quả {result} không khớp expect {check['expect']}", turn)
    if isinstance(result, dict):
        for field_name, source, must in (("applied", "applied_promos", True), ("not_applied", "applied_promos", False),
                                         ("expired", "expired_promos", True),
                                         ("ineligible", "ineligible_promos", True)):
            for code in check.get(field_name) or []:
                if (code in _codes(result.get(source))) != must:
                    sink("error", f"{label}: {code} {'không ' if must else ''}nằm trong {source} = "
                                  f"{sorted(_codes(result.get(source)))}", turn)


# ---------------------------------------------------------------------------
# Báo cáo
# ---------------------------------------------------------------------------

def _oracle(d: dict, ref: Reference, written: list[str]) -> tuple[int, int]:
    """Bộ trích entity của pipeline trên chính lời thoại đúng (trần trên khi ASR không sai)."""
    expected = d.get("entities") or {}
    when = _iso(d.get("call_date")) or date(2026, 10, 15)
    found, _ = extract_entities(written, ref.catalog, reference_date=when)
    return sum(1 for k, v in expected.items() if str(found.get(k)) == str(v)), len(expected)


def validate(sources: list[tuple[str, dict]], ref: Reference) -> Report:
    report = Report()
    seen: dict[str, str] = {}
    for file, source in sources:
        ref_date, window, engine = _check_header(source, file, report)
        for d in source.get("dialogues") or []:
            did = str(d.get("id") or "?")
            sink = _Sink(report, did)
            if did in seen:
                sink("error", f"id trùng với {seen[did]}")
            seen[did] = file
            _check_format(d, sink, ref_date, window, ref.holidays)
            turns = d.get("turns") if isinstance(d.get("turns"), list) else []
            template = is_template(d)
            written = []
            for turn in turns:
                _check_spoken(turn, sink, template)
                text = str(turn.get("text", "")).replace(KH, "anh")
                written.append(normalize_text(text).written)
                _check_labels(turn, sink, ref, written[-1])
            if turns and (d.get("entities") or {}) != merge_turn_entities(turns):
                sink("error", f"entities hội thoại {d.get('entities')} ≠ gộp entity các lượt "
                              f"{merge_turn_entities(turns)} (BTC: giá trị lượt sau ghi đè)")
            _check_facts(d, sink, ref)

            spoken = [str(t.get("tts_text") or t.get("text", "")) for t in turns]
            est = estimate_seconds(spoken)
            if turns and not SECONDS_RANGE[0] <= est <= SECONDS_RANGE[1]:
                sink("warn", f"ước tính {est:.0f} s, ngoài khoảng {SECONDS_RANGE[0]:.0f}–{SECONDS_RANGE[1]:.0f} s")
            chars = sum(len(t.replace(KH, "chị")) for t in spoken)
            credits = chars * credits_per_char(DEFAULT_ELEVEN_MODEL) if engine == "elevenlabs" else 0.0
            diff = 0
            for turn in turns:
                text = str(turn.get("text", "")).replace(KH, "anh")
                if normalize_text(text).spoken != btc_norm(text):
                    diff += 1
            report.stats.append(DialogueStats(
                did, file, d.get("split"), bool(d.get("noisy")), engine, len(turns),
                sum(syllables(t) for t in spoken), round(est, 1), chars, credits,
                _oracle(d, ref, written) if turns else (0, 0), diff))
    return report


def format_report(report: Report) -> str:
    lines = ["| id | file | split | nhiễu | lượt | âm tiết | ~giây | ký tự | credit | oracle entity | khác round-trip |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in report.stats:
        lines.append(f"| {s.id} | {Path(s.file).name} | {s.split} | {'có' if s.noisy else ''} | {s.n_turns} | "
                     f"{s.syllables} | {s.est_s:.0f} | {s.chars} | {s.credits:.0f} | {s.oracle[0]}/{s.oracle[1]} | "
                     f"{s.roundtrip_diff} |")
    by_file: dict[str, list[DialogueStats]] = {}
    for s in report.stats:
        by_file.setdefault(Path(s.file).name, []).append(s)
    lines.append("")
    for name, items in by_file.items():
        lines.append(f"- {name}: {len(items)} hội thoại, {sum(s.n_turns for s in items)} lượt, "
                     f"~{sum(s.est_s for s in items) / 60:.1f} phút, {sum(s.chars for s in items)} ký tự, "
                     f"{sum(s.credits for s in items):.0f} credit, oracle "
                     f"{sum(s.oracle[0] for s in items)}/{sum(s.oracle[1] for s in items)}")
    lines.append("")
    lines += [str(i) for i in report.issues if i.level != "info"]
    lines.append(f"\n{len(report.errors)} lỗi, {len(report.warnings)} cảnh báo.")
    return "\n".join(lines)
