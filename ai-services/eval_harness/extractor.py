"""Trace Extractor Engine for AI TeleSale SudoCode 2026.

Extracts questions, claims, and facts used from agent outputs and turn state
to construct standardized evaluation traces adhering to BTC schema.
"""

from __future__ import annotations

import re
from typing import Any

def _money_claims(text: str) -> list[tuple[int, str, bool]]:
    """Eval-local amounts: runtime guardrail behavior is deliberately independent."""
    text = re.sub(r"(?<!\w)(\d+)\s*(?:triệu|tr)(\d{1,3})(?!\w)",
                  lambda m: str(int(m[1]) * 1000000 + int(m[2]) * 10 ** (6 - len(m[2]))) + "đ", text, flags=re.I)
    result = []
    pattern = r"(?<![\w/])(\d+(?:[.,]\d+)*)(?:\s*(triệu|tr|nghìn|ngàn|k|đồng|đ|vnd))?(?![\w/])"
    previous = 0
    for match in re.finditer(pattern, text, re.I):
        number, unit = match.group(1), (match.group(2) or "").lower()
        if not unit and not re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+|\d{6,}", number):
            continue
        if unit in {"triệu", "tr", "nghìn", "ngàn", "k"}:
            amount = int(float(number.replace(",", ".")) * (1000000 if unit in {"triệu", "tr"} else 1000))
        else:
            amount = int(number.replace(".", "").replace(",", ""))
        context = text[previous:match.start()]
        discount = bool(re.search(r"giảm(?: giá)?(?: thêm)?\s*$|chiết khấu\s*$", context, re.I))
        result.append((amount, "discount" if discount else "price", False))
        previous = match.end()
    return result


def _is_inspection_narrative(text: str) -> bool:
    return '?' not in text and not re.search(r"[,;]", text) and bool(re.match(
        r"\s*(?:dạ[,]?\s*)?(?:em|tôi|shop) (?:sẽ|đang) (?:kiểm tra|xem|tìm hiểu)\b", text, re.I))


# Question detection patterns
CONFIRM_PATTERNS = [
    re.compile(r"(đúng không|phải không|có phải|chuẩn chưa|đúng chưa|xác nhận lại)\b", re.IGNORECASE),
    re.compile(r"^dạ anh/chị chọn .*, đúng không ạ", re.IGNORECASE),
]

SLOT_QUESTION_PATTERNS = [
    ("room_area_m2", re.compile(r"(bao nhiêu mét|diện tích|m2|m²|rộng bao nhiêu)", re.IGNORECASE)),
    ("has_children", re.compile(r"(có trẻ nhỏ|trẻ em|bé nhỏ|bé sơ sinh|con nhỏ)", re.IGNORECASE)),
    ("budget_vnd", re.compile(r"(ngân sách|tầm tiền|tầm giá|khoảng bao nhiêu tiền)", re.IGNORECASE)),
    ("color", re.compile(r"(màu gì|thích màu|chọn màu|màu sắc|màu nào)", re.IGNORECASE)),
    ("size", re.compile(r"(cỡ|size|kích cỡ)", re.IGNORECASE)),
    ("product_advised", re.compile(r"(máy nào|sản phẩm nào|quan tâm mẫu nào|chọn loại nào|mẫu (?:giày |máy )?nào|(?:chốt|chọn|quan tâm(?: đến)?|muốn lấy) (?:mẫu|máy|sản phẩm)\b|(?:tên|mã) (?:máy|sản phẩm)\b|có muốn (?:lấy|mua|chọn) (?:mẫu|sản phẩm|máy|loại))", re.IGNORECASE)),
    ("order_id", re.compile(r"mã đơn|đơn hàng nào", re.I)),
    ("address", re.compile(r"địa chỉ|giao (?:tới|đến) đâu", re.I)),
    ("payment", re.compile(r"thanh toán|chuyển khoản|\bCOD\b", re.I)),
    ("promo_code", re.compile(r"mã (?:khuyến mãi|ưu đãi)", re.I)),
    ("purchase_consent", re.compile(r"(?:lên|tạo|đặt) đơn", re.I)),
    ("quantity", re.compile(r"số lượng|mỗi loại (?:một|\d+)", re.I)),
    ("stock_check_consent", re.compile(r"kiểm tra tồn kho", re.I)),
    ("return_reason", re.compile(r"lý do (?:cụ thể|trả hàng)", re.I)),
    ("product_requirements", re.compile(r"yêu cầu đặc biệt", re.I)),
    ("customer_name", re.compile(r"(tên là gì|xin phép gọi anh/chị là|tên của anh/chị)", re.IGNORECASE)),
]

# Claims extraction patterns
HUMAN_CLAIM_PATTERNS = [
    re.compile(r"(em là người thật|tôi là người thật|không phải ai|không phải bot|người thật nói chuyện)", re.IGNORECASE),
]


_DIGITS = {"không":0,"một":1,"mốt":1,"hai":2,"ba":3,"bốn":4,"tư":4,
           "năm":5,"lăm":5,"sáu":6,"bảy":7,"tám":8,"chín":9}
_NUMBER_WORDS = "|".join((*_DIGITS,"mười","mươi","trăm","nghìn","ngàn","triệu","linh","lẻ","rưỡi"))
_SPOKEN_NUMBER = re.compile(r"(?<!\w)(?:" + _NUMBER_WORDS + r")(?:\s+(?:" + _NUMBER_WORDS + r"))*(?!\w)",re.I)


def numeric_text(text):
    def replace(match):
        words=match.group().lower().split()
        if not any(w in _DIGITS or w in {'mười', 'mươi', 'trăm'} for w in words):
            return match.group()
        if not any(w in {"nghìn","ngàn","triệu"} for w in words) and not re.match(r"\s*(?:đồng|ngày|tháng)\b",text[match.end():],re.I):
            return match.group()
        total=group=0
        unit = 0
        for w in words:
            if w in _DIGITS:
                group+=_DIGITS[w]
            elif w=="trăm":
                group*=100
            elif w in {"mười","mươi"}:
                group=group//10*10+(group%10 or 1)*10
            elif w in {"nghìn","ngàn","triệu"}:
                unit = {"nghìn":1000,"ngàn":1000,"triệu":1000000}[w]
                total+=group*unit
                group=0
            elif w == 'rưỡi' and unit:
                total += unit // 2
        return str(total+group) + ('đ' if unit else '')
    return _SPOKEN_NUMBER.sub(replace,text)


def _question_candidates(agent_text: str) -> list[dict]:
    candidates = []
    # Keep lists inside a request intact; discard comma-separated context only
    # before the first request. Numeric punctuation is not a sentence boundary.
    for sentence in re.split(r"(?<=[?!;\n])\s*|(?<!\d)\.(?!\d)\s*", agent_text):
        sentence = sentence.strip(" *#-\n")
        if not sentence:
            continue
        request = re.search(
            r"bao nhiêu|\bgì\b|phải không|đúng không|nào\b|chưa (?:ạ|chị|anh)|"
            r"xong chưa|(?:cho (?:em )?(?:xin|biết))|xin (?:chị|anh) (?:cho|cung cấp)", sentence, re.I)
        if "?" not in sentence and not request:
            continue
        if re.search(r'[“”"«»]|(?:khách|anh ấy|chị ấy) (?:hỏi|nói)', sentence, re.I):
            candidates.append(_candidate("question", sentence, disposition="excluded", reason="reported_speech"))
            continue
        narrative = "?" not in sentence and bool(re.search(
            r"(?:không|chưa) (?:có|còn|phát sinh).*\bnào\b|"
            r"\bkhi nào\b.*(?:\bcứ\b|(?:anh|chị|mình) (?:báo|nhắn) em nhé)", sentence, re.I))
        if ("?" not in sentence and re.search(
                r"(?:không|chưa) (?:tìm )?thấy(?: có)?.*\bnào\b", sentence, re.I)
                and not re.search(r"cho (?:em|tôi|shop) (?:xin|biết)|vui lòng|cung cấp|xin (?:anh|chị)|"
                                  r"(?:anh|chị|mình|bạn)\s+(?:có thể\s+)?(?:gửi|đọc|báo|cho)", sentence, re.I)):
            narrative = True
        if _is_inspection_narrative(sentence) or narrative or (
                '?' not in sentence and re.search(r'bất cứ lúc nào', sentence, re.I)):
            candidates.append(_candidate("question", sentence, disposition="excluded", reason="narrative"))
            continue
        target = sentence
        if request:
            before = sentence[:request.start()]
            # The request's own noun phrase precedes the interrogative.
            if "," in before and not any(p.search(before.split(",")[-1]) for p in CONFIRM_PATTERNS):
                target = sentence[before.rfind(",") + 1:].strip()
                if any(p.search(target) for p in CONFIRM_PATTERNS) and not any(p.search(target) for _, p in SLOT_QUESTION_PATTERNS):
                    target = sentence
        asked = re.split(r"\bđể (?:em|tôi|shop|bên em)\b", target, maxsplit=1, flags=re.I)[0]
        confirm = any(p.search(asked) for p in CONFIRM_PATTERNS)
        blocker = re.search(r"trao đổi|bàn với|cân nhắc|hỏi (?:chồng|vợ|người)|quyết định|đồng ý", asked, re.I)
        matches = [(m.start(), slot) for slot, pat in SLOT_QUESTION_PATTERNS if (m := pat.search(asked))]
        if not re.search(r'nào|\bgì\b|bao nhiêu|\bhay\b', asked, re.I) and re.search(
                r'chốt\s+(?:mẫu|máy|sản phẩm) này|vẫn\s+(?:lấy|chọn|giữ)|'
                r'chốt (?:lấy|mua).*(?:em|shop) (?:lên|tạo|đặt) đơn', asked, re.I):
            confirm = True
        if re.search(r"\bmàu\b", asked, re.I) and not any(slot == "color" for _, slot in matches):
            matches.append((re.search(r"\bmàu\b", asked, re.I).start(), "color"))
        quote_confirmation = re.search(
            r"(?:đồng ý(?:\s+với)?|xác nhận(?:\s+lại)?)\s+(?:mức\s+)?(?:báo\s+)?giá\b", asked, re.I)
        if quote_confirmation:
            matches.append((quote_confirmation.start(), 'price_quoted_vnd'))
            confirm = True
        elif consent := re.search(r'đồng ý điều chỉnh (?:mức chi|ngân sách)', asked, re.I):
            matches = [(consent.start(), 'budget_consent')]
        elif requirement := re.search(r'có phải yêu cầu bắt buộc', asked, re.I):
            matches = [(requirement.start(), 'product_requirements')]
        elif blocker and (not any(slot == 'product_advised' for _, slot in matches)
                          or re.search(r'(?:chọn|chốt) mẫu này', asked, re.I)
                          and not re.search(r'nào|\bgì\b|\bhay\b', asked, re.I)):
            matches = [(blocker.start(), "blocker")]
        generic = bool(re.search(r"(?:hỗ trợ|giúp|cần|thắc mắc|xử lý tiếp).*(?:gì|không)|"
                                 r"có (?:câu hỏi|thắc mắc)|làm rõ điều kiện|khi nào.*(?:muốn|cần) đặt hàng", asked, re.I))
        if not matches:
            matches = [(0, "other")]
        for _, slot in sorted(set(matches)):
            uncertainty = ["unresolved_slot"] if slot == "other" and not generic else []
            if slot != "other" and not confirm and not request and not re.search(
                    r"\b(?:có|muốn|cần)\b.*không|\bhay\b", target, re.I):
                uncertainty.append("unresolved_question_type")
            projection = {"slot": slot, "type": "confirm" if confirm and slot != "other" else "open", "text": target}
            candidates.append(_candidate("question", target, projection=projection,
                reason="generic_question" if generic and slot == "other" else "resolved" if not uncertainty else uncertainty[0],
                uncertainty=uncertainty, qualifiers={"recognized_question_type": "confirm"} if slot == "other" and confirm else {}))
    return candidates


def _policy_version_projections(clause: str) -> list[dict]:
    """Preserve replacement roles instead of treating every mentioned version as current."""
    versions = list(re.finditer(r"\b20\d{2}-\d{2}\b(?!-\d)", clause))
    if not versions or not re.search(r"chính sách|phiên bản|bản cũ|thay thế|hiện.*(?:dùng|áp dụng)|trước đây.*dùng", clause, re.I):
        return []
    if re.search(r"không (?:phải|thay thế)|chưa thay thế|có thể|hoặc|đơn.*(?:trước|sau)", clause, re.I):
        return []
    replacement = re.search(r"thay thế", clause, re.I)
    passive = re.search(r"(?:được|bị) thay thế(?: bởi)?", clause, re.I)
    if len(versions) > 2 or (len(versions) > 1 and replacement is None):
        return []
    result = []
    for version in versions:
        historical = bool(re.search(r"trước đây|lần trước|chính sách cũ|bản cũ", clause, re.I))
        if passive:
            historical = version.start() < passive.start()
        elif replacement:
            historical = version.start() > replacement.start()
        result.append({'field': ('historical_' if historical else '') + 'policy_version',
                       'value': version[0], 'text': clause.strip()})
    return result


def _claim_projections(agent_text: str, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract verifiable factual claims from agent text and tool calls."""
    claims = []
    if not agent_text:
        agent_text = ""

    # A self-assertion is different from questions, quotations or reported speech.
    for clause in re.split(r"[.!?;\n]", agent_text):
        if not clause.strip() or any(c in clause for c in ('“', '”', '"', '«')):
            continue
        if re.search(r"phải không|đúng không|khách (?:hỏi|nói)|nếu|không (?:phải )?(?:là )?người thật", clause, re.I):
            continue
        # The question mark belongs to the complete sentence, not the split clause.
        if clause.strip() + "?" in agent_text or re.search(re.escape(clause.strip()) + r"\s*\?", agent_text):
            continue
        if re.search(r"(?:em|tôi|mình)\s+(?:là người thật|không phải (?:là )?(?:ai|bot)\b)", clause, re.I):
            claims.append({"field": "is_human", "value": True, "text": clause.strip()})
            break

    # Only speech supplies claims. Tools never repair or invent their truth.
    for clause in re.split(r"\.(?!\d)|[!;\n]|\bnhưng\b|,\s*(?!\d)", agent_text):
        if "?" in clause or re.search(r"\bnếu\b|phải không|đúng không", clause, re.I):
            continue
        historical = bool(re.search(r"lần trước|trước đây", clause, re.I)) and not re.search(r"hiện|hôm nay|đang", clause, re.I)
        if re.search(r"giá|\bchỉ\b|\bcòn\b", clause, re.IGNORECASE):
            priced = re.sub(r"không phải.+?\bmà(?: là)?\s*", "", clause, flags=re.I)
            priced = re.split(r"\bchứ không(?: phải)?\b", priced, flags=re.I)[0]
            if re.search(r"không (?:phải|có)\s+(?:là\s+)?(?:giá|\d)", priced, re.I):
                priced = ""
            priced = numeric_text(priced)
            # Remove only the attributed budget amount, preserving any selling
            # price before or after it in the same clause.
            priced = re.sub(
                r'\b(?:ngân sách|mức chi)\s+(?:của\s+(?:anh|chị|mình|bạn)\s+)?'
                r'(?:(?:tầm|khoảng|tối đa|là|chỉ)\s+)*'
                r'\d[\d.,]*(?:\s*(?:triệu|tr|nghìn|ngàn|k|đồng|đ|vnd)\b)?',
                '', priced, flags=re.I)
            for amount, kind, _ in _money_claims(priced):
                if amount >= 0:
                    field = "discount_vnd" if kind == "discount" else "list_price_vnd" if re.search(r"niêm yết|giá gốc", clause, re.I) else "price_vnd"
                    if historical:
                        field = "historical_" + field
                    claims.append({"field": field, "value": amount, "source": "text", "text": clause.strip()})
        codes = re.findall(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b", clause)
        codes = [code for code in codes if not code.startswith(("SKU-", "OD-"))]
        if codes or re.search(r"khuyến mãi|giảm giá|ưu đãi|tặng|biếu", clause, re.IGNORECASE):
            inactive = bool(re.search(
                r"(?:đã\s+)?hết\s+(?:hạn|hiệu lực|khuyến mãi|chương trình)|"
                r"không\s+còn|chưa\s+có|không\s+có|không\s+(?:được\s+)?tặng", clause, re.I))
            fields = [f"promo_{code}_active" for code in codes] if codes else ["promo_active"]
            if historical:
                fields = [field.removesuffix("_active") + "_historical" for field in fields]
            claims.extend({"field": field, "value": not inactive, "source": "text", "text": clause.strip()}
                          for field in fields)

    # Stock statements have the same polarity/time boundary as offer claims.
    for clause in re.split(r"\.(?!\d)|[!;\n]|\bnhưng\b|,\s*(?!\d)", agent_text):
        if "?" in clause or re.search(r"\bnếu\b", clause, re.I):
            continue
        historical = bool(re.search(r"lần trước|trước đây", clause, re.I)) and not re.search(r"hiện|hôm nay|đang", clause, re.I)
        negative = bool(re.search(r"không\s+(?:còn|có)\s+hàng|hết hàng|tạm hết|(?:không|chưa) có sẵn trong kho", clause, re.I))
        positive = bool(re.search(r"còn hàng|sẵn hàng|có sẵn trong kho", clause, re.I))
        if negative or positive:
            stock_field = "new_size_in_stock" if re.search(r"size mới|size đổi|cỡ mới", clause, re.I) else "in_stock"
            claims.append({"field": "historical_" + stock_field if historical else stock_field,
                           "value": not negative, "source": "text", "text": clause.strip()})
    lower_text = agent_text.lower()
    if "ngừng bán" in lower_text:
        claims.append({"field": "product_status", "value": "discontinued", "source": "text"})

    # Policy facts use BTC field names. Only explicit, unconditional speech counts.
    for clause in re.split(r"\.(?!\d)|[!;\n]|,\s*(?!\d)", agent_text):
        if "?" in clause or re.search(r"\bnếu\b|phải không|đúng không", clause, re.I):
            continue
        historical = bool(re.search(r"lần trước|trước đây", clause, re.I)) and not re.search(r"hiện|hôm nay|đang", clause, re.I)
        historical = historical or bool(re.search(r"chính sách cũ|bản cũ", clause, re.I))
        prefix = "historical_" if historical else ""
        patterns = [
            ("delivery_days", r"giao\s*(?:trong vòng|trong|khoảng|mất)?\s*(\d+)\s*ngày", int),
            ("return_days", r"đổi\s*(?:(?:hoặc\s+)?trả)?\s*(?:sản phẩm\s*)?(?:cho các đơn hàng mới\s*)?(?:là\s*)?(?:trong vòng|trong|tối đa)?\s*(?:\d+\s*→\s*)?(\d+)\s*ngày", int),
            ("warranty_months", r"bảo hành\s*(?:chính hãng\s*)?(?:trong|tới|đến)?\s*(\d+)\s*tháng", int),
            ("restock_date", r"(?:hàng về|về hàng|nhập hàng)\s*(?:ngày)?\s*(20\d{2}-\d{2}-\d{2})", str),
        ]
        claims.extend(_policy_version_projections(clause))
        for field, pattern, cast in patterns:
            match = re.search(pattern, numeric_text(clause), re.I)
            if match:
                claims.append({"field": prefix + field, "value": cast(match.group(1)), "text": clause.strip()})
        if re.search(r"phí đổi|phí (?:đổi trả|đổi size)|đổi (?:trả|size|cỡ).*miễn phí", clause, re.I):
            money = _money_claims("Giá " + numeric_text(clause))
            if money:
                claims.append({"field": prefix + "exchange_fee_vnd", "value": money[0][0], "text": clause.strip()})
            elif re.search(r"miễn phí|không (?:mất|thu|tính) phí", clause, re.I):
                claims.append({"field": prefix + "exchange_fee_vnd", "value": 0, "text": clause.strip()})
        if re.search(r"freeship|miễn phí (?:ship|vận chuyển|giao hàng)|không (?:được )?miễn phí (?:ship|vận chuyển|giao hàng)", clause, re.I):
            negative = bool(re.search(r"(?:không|chưa)\s+(?:được\s+)?(?:miễn phí|freeship)|hết hiệu lực", clause, re.I))
            claims.append({"field": prefix + "freeship", "value": not negative, "text": clause.strip()})
        if re.search(r"chính sách cũ.*(?:hết hiệu lực|thay thế)", clause, re.I):
            claims.append({"field": "old_policy_superseded", "value": True, "text": clause.strip()})

    return claims


def _candidate(kind: str, text: str, *, projection: dict | None = None,
               disposition: str = "emitted", reason: str = "resolved",
               uncertainty: list[str] | None = None, qualifiers: dict | None = None) -> dict:
    return {"kind": kind, "text": text, "disposition": disposition,
            "reason": reason, "uncertainty": list(uncertainty or []),
            "projection": projection, "qualifiers": dict(qualifiers or {})}


def _claim_clauses(text: str):
    for sentence in re.split(r"\.(?!\d)|[!;\n]|\bnhưng\b", text):
        # A leading if-clause governs the consequent across its comma.
        if re.match(r"\s*(?:nếu|lần (?:đổi )?đầu|từ lần đổi)", sentence, re.I):
            yield sentence
            continue
        for clause in re.split(r",\s*(?!\d)", sentence):
            # Explicit independent predicates, not product lists. Keep temporal
            # and conditional scopes together rather than invent an inheritance.
            if re.search(r"\bnếu\b|lần trước|trước đây|chính sách cũ", clause, re.I):
                yield clause
            else:
                yield from re.split(r"\s+và\s+(?=(?:giá|phí|tổng tiền|tổng đơn|bảo hành|đổi trả|miễn phí|freeship)\b)", clause, flags=re.I)


def _claim_candidates(agent_text: str) -> list[dict]:
    candidates = []
    # Clause-local extraction prevents conditions/negation leaking to a separate
    # assertion. Commas inside amounts and periods inside numbers are retained.
    for clause in _claim_clauses(agent_text):
        clause = clause.strip(" *#-")
        if not clause:
            continue
        factual = bool(re.search(r"giá|tổng (?:tiền|đơn)|giảm|miễn phí|freeship|giao|đổi|bảo hành|còn hàng|hết hàng|có sẵn trong kho|ưu đãi|khuyến mãi|tặng|người thật|không phải bot|ngừng bán|chính sách|phiên bản|không có hàng|mã [A-Z0-9]+-", clause, re.I))
        factual = factual or bool(re.search(r"20\d{2}-\d{2}", clause) and re.search(r"thay thế|hiện.*dùng|trước đây.*dùng|đơn.*(?:trước|sau)", clause, re.I))
        if not factual:
            continue
        if "?" in clause or re.search(r"phải không|đúng không", clause, re.I):
            # The question candidate represents this request; it is not also an assertion.
            continue
        if re.search(r'[“”"«»]|khách (?:nói|hỏi)', clause, re.I):
            candidates.append(_candidate("claim", clause, disposition="excluded", reason="reported_speech"))
            continue
        if _is_inspection_narrative(clause):
            candidates.append(_candidate("claim", clause, disposition="excluded", reason="not_assertion"))
            continue
        no_assertion = re.fullmatch(
            r'(?:Theo (?:thông tin )?chính sách(?: đã kiểm tra| hiện tại)?(?::\s*(?:Phí vận chuyển|Giá bán|Điều kiện đổi trả|Bảo hành mở rộng|Hoàn tiền|\d{2}/\d{2}/\d{4}\s*—\s*Bảo hành))?'
            r'|Về (?:chế độ )?bảo hành|Về điều kiện (?:đổi trả|đổi hàng)'
            r'|Khi cần bảo hành|Về quy định giao (?:hàng|lại)|Về yêu cầu đổi áo của (?:anh|chị)'
            r'|Để tham khảo trước khi mua: Điều kiện đổi trả'
            r'|Giá bán|\d{2}/\d{2}/\d{4}\s*—\s*Bảo hành'
            r'|Em gửi (?:anh|chị) giá và tình trạng kho của hai sản phẩm(?: ạ)?:'
            r'|Báo giá cần được xác nhận lại trước khi tạo đơn)', clause, re.I)
        no_assertion = no_assertion or (not _money_claims(numeric_text(clause)) and re.match(
            r'(?:Em|Tôi) chưa (?:xác minh (?:được|đủ)|có thông tin)\b'
            r'|(?:Anh|Chị) (?:chờ|đợi) em.*để (?:em )?kiểm tra\b', clause, re.I))
        if no_assertion:
            candidates.append(_candidate('claim', clause, disposition='excluded', reason='not_assertion'))
            continue
        conditional = re.search(r"\bnếu\b|lần\b.{0,60}?\bđầu(?: tiên)?|từ lần đổi|chỉ (?:áp dụng|dành cho)|đơn\s+(?:hàng\s+)?(?:từ|trên)\s*\**\d", clause, re.I)
        if conditional and re.search(r"thì\s+(?:anh|chị|khách|tôi|mình)\s+(?:sẽ )?(?:mua|chọn|cân nhắc)", clause, re.I):
            candidates.append(_candidate("claim", clause, disposition="excluded", reason="hypothetical"))
            continue
        conditional = conditional or (re.search(r"đơn.*(?:trước|sau)", clause, re.I) if re.search(r"20\d{2}-\d{2}", clause) else None)
        if conditional:
            candidates.append(_candidate("claim", clause, disposition="excluded", reason="qualified_not_representable",
                qualifiers={"condition": clause[conditional.start():]}))
            continue
        variant = re.search(r"(?:size|cỡ)\s+(\d+)\b", clause, re.I)
        if variant and re.search(r"còn hàng|hết hàng|không có hàng|có sẵn trong kho", clause, re.I):
            candidates.append(_candidate("claim", clause, disposition="excluded", reason="qualified_not_representable",
                qualifiers={"size": int(variant[1])}))
            continue
        if re.search(r"phí (?:giao hàng|vận chuyển|ship)\s*\d", numeric_text(clause), re.I):
            candidates.append(_candidate("claim", clause, disposition="excluded", reason="unsupported_mapping",
                qualifiers={"category": "shipping_fee"}))
            continue
        if re.search(r"miễn phí thu hộ\s*\(?COD\b", clause, re.I):
            candidates.append(_candidate("claim", clause, disposition="excluded", reason="unsupported_mapping",
                qualifiers={"category": "cod_fee"}))
            continue
        calendar_delivery = bool(re.search(r"\bngày\s+\d{1,2}[/\-]\d{1,2}\b|\b20\d{2}-\d{2}-\d{2}\b", clause, re.I) and re.search(r"\bgiao\b", clause, re.I))
        if calendar_delivery or re.search(r"tổng (?:tiền|đơn|giá)|giao (?:vào )?ngày\s+\d{1,2}[/\-]\d{1,2}|đổi mới", clause, re.I):
            candidates.append(_candidate("claim", clause, disposition="excluded", reason="unsupported_mapping",
                qualifiers={"category": "total" if re.search(r"tổng", clause, re.I) else "calendar_delivery" if re.search(r"giao", clause, re.I) else "replacement"}))
            continue
        parsed = re.sub(r"\*\*|__|`", "", clause)
        projections = _claim_projections(parsed, [])
        for projection in projections:
            projection['text'] = clause
        if re.search(r"\bgiảm\s+(?:thêm\s+)?\d", numeric_text(clause), re.I) and not re.search(r"giá", clause, re.I):
            projections = [{"field": "discount_vnd", "value": amount, "text": clause}
                for amount, kind, _ in _money_claims(numeric_text(clause)) if kind == "discount"]
        candidates.extend(_candidate("claim", c.get("text", clause), projection=c,
            qualifiers={"temporal": "historical"} if c["field"].startswith("historical_") or c["field"].endswith("_historical") else {}) for c in projections)
        if not projections and not re.search(r"không (?:phải )?(?:là )?người thật|không (?:phải|có)\s+(?:là\s+)?(?:giá|\d)", clause, re.I):
            candidates.append(_candidate("claim", clause, disposition="unresolved", reason="unresolved_claim", uncertainty=["unresolved_claim"]))
    return candidates


def extract_detailed(agent_text: str) -> dict:
    """Speech-only extraction. IDs/context/truth are attached by callers later."""
    candidates = _question_candidates(agent_text) + _claim_candidates(agent_text)
    for index, candidate in enumerate(candidates):
        candidate["candidate_id"] = f"{candidate['kind']}-{index}"
    return {"questions": [c["projection"] for c in candidates if c["kind"] == "question" and c["disposition"] == "emitted"],
            "claims": [c["projection"] for c in candidates if c["kind"] == "claim" and c["disposition"] == "emitted"],
            "candidates": candidates}


def extract_questions(agent_text: str) -> list[dict[str, Any]]:
    return extract_detailed(agent_text)["questions"]


def extract_claims(agent_text: str, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Retained argument for callers; business observations never rewrite speech.
    return extract_detailed(agent_text)["claims"]


def build_trace_row(
    scenario_id: str,
    call_name: str,
    turn_idx: int,
    user_text: str,
    agent_text: str,
    tool_calls: list[dict[str, Any]],
    memory_writes: list[dict[str, Any]],
    facts_used: list[str],
    latency_ms: float,
    call_brief_latency_ms: float | None = None,
) -> dict[str, Any]:
    """Construct one trace row matching BTC reference_eval structure."""
    annotations = extract_detailed(agent_text)
    questions = annotations["questions"]
    claims = annotations["claims"]

    return {
        "scenario_id": scenario_id,
        "call": call_name,
        "turn": turn_idx,
        "user_text": user_text,
        "agent_text": agent_text,
        "tool_calls": tool_calls,
        "memory_writes": memory_writes,
        "facts_used": facts_used,
        "questions": questions,
        "claims": claims,
        "latency": {
            "total_ms": round(latency_ms, 1),
            "ttft_ms": round(latency_ms, 1),  # non-streaming total
        },
        "call_brief_latency_ms": round(call_brief_latency_ms, 1) if call_brief_latency_ms else None,
    }
