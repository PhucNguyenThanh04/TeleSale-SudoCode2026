
import re

_NUMBER_BODY = r"\+?\d(?:[ .\t-]?\d){8,}"
_NUMERIC_PII = re.compile(r"(?<![\w-])" + _NUMBER_BODY + r"(?![\w-])")
_LABELED_NUMBER = re.compile(
    r"(?i)\b(?:cccd|cmnd|sđt|sdt|số điện thoại|so dien thoai|phone|stk|"
    r"số tài khoản|so tai khoan|tài khoản|tai khoan|số thẻ|so the)"
    r"\s*[:=-]?\s*(?P<number>" + _NUMBER_BODY + r")(?!\w)"
)
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_ADDRESS = re.compile(
    r"(?i)\b(?:địa chỉ|dia chi)(?! ĐÃ ẨN\])(?:\s*[:\-]\s*[^\n.!?]+|"
    r"\s+(?!(?:cũ|cu|mới|moi|nhận|nhan|giao|của|cua|ở\s+đâu|o\s+dau|"
    r"nào|nao|để|de|và|va|giúp|giup|nhé|nhe|ạ|a|chưa|chua|không|khong|"
    r"vừa|vua|đã|da|được|duoc|trước|truoc|hôm|hom|theo|vẫn|van|như|nhu)\b)[^\n.!?]+)"
)
_STREET = re.compile(r"(?i)\b\d+[\w/-]*\s+(?:đường|duong|phố|pho)\b[^\n.!?]*")
_ALLEY = re.compile(r"(?i)\b(?:(?:số\s*)?\d+[\w/-]*\s+(?:ngõ|ngo|ngách|ngach|hẻm|hem)|(?:ngõ|ngo|ngách|ngach|hẻm|hem)\s+\d+[\w/-]*)\b[^\n.!?]*")
_APARTMENT = re.compile(r"(?i)\b(?:căn(?:\s+hộ)?|can(?:\s+ho)?)\s+[A-Z]?\d+[\w/-]*\b[^\n.!?]*")
_INTRODUCED_NAME = re.compile(r"(?i)\b(?:tên tôi là|ten toi la|tôi là|toi la)\s+[A-ZÀ-Ỹ][\wÀ-ỹ]*(?:\s+[A-ZÀ-Ỹ][\wÀ-ỹ]*){0,3}")
_PERSON_NAME = re.compile(r"\b(?:Nguyễn|Trần|Lê|Phạm|Hoàng|Huỳnh|Phan|Vũ|Võ|Đặng|Bùi|Đỗ|Hồ|Ngô|Dương|Lý)\s+[A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,2}\b")
_ADDRESS_CLAUSE = (
    r"(?:lấy|lay|mua|chọn|chon|thanh toán|thanh toan|trả bằng|tra bang|"
    r"nhưng|nhung|không|khong|chưa|chua|nếu|neu|"
    r"(?:chỉ|chi)\s+(?:mua|lấy|lay|tạo|tao|giao|nhận|nhan|khi|nếu|neu)|"
    r"(?:tôi|toi|mình|minh|anh|chị|em)\s+(?:muốn|muon|cần|can|lấy|lay|mua|chọn|chon|chỉ|chi|không|khong|chưa|chua)|"
    r"giao (?:chỗ|cho|đó|do|trước|truoc|sau)|"
    r"số lượng|so luong|payment|quantity|only|but)\b"
)
_ADDRESS_END = re.compile(
    r"(?i);|,\s*(?=" + _ADDRESS_CLAUSE + r")|\s+(?:và|va|nhưng|nhung)\s+(?=" + _ADDRESS_CLAUSE + r")"
    r"|\s+(?=(?:lấy|lay|mua|chọn|chon)\s+(?:\d+|một|mot|hai|ba|bốn|bon|năm|nam|sáu|sau|bảy|bay|tám|tam|chín|chin|mười|muoi)\s+"
    r"(?:cái|cai|chiếc|chiec|máy|may|đôi|doi|bộ|bo|sản phẩm|san pham)\b)"
    r"|\s+(?=(?:thanh toán|thanh toan)\s+(?:momo|cod|bank|zalopay|chuyển khoản|chuyen khoan)\b)"
)


def _address_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for pattern in (_ADDRESS, _STREET, _ALLEY, _APARTMENT):
        offset = 0
        while match := pattern.search(text, offset):
            boundary = _ADDRESS_END.search(match[0])
            value = match[0][:boundary.start()] if boundary else match[0]
            end = match.start() + len(value.rstrip(' ,;]'))
            if end > match.start():
                spans.append((match.start(), end))
            offset = max(match.start() + 1, end if boundary else match.end())
    merged = []
    for start, end in sorted(set(spans)):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged

def mask_pii(value: str) -> str:
    value = _EMAIL.sub("[EMAIL ĐÃ ẨN]", value)
    for start, end in reversed(_address_spans(value)):
        value = value[:start] + '[ĐỊA CHỈ ĐÃ ẨN]' + value[end:]
    value = _INTRODUCED_NAME.sub("[TÊN ĐÃ ẨN]", value)
    value = _PERSON_NAME.sub("[TÊN ĐÃ ẨN]", value)
    value = _LABELED_NUMBER.sub(
        lambda match: match[0][:match.start('number') - match.start()] + '[SỐ ĐÃ ẨN]', value)

    def mask_number(match):
        tail = value[match.end():]
        if re.match(r'\s*(?:đồng|dong|vnd|₫|đ)(?!\w)', tail, re.I):
            return match[0]
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:\s+\d{4}-\d{2}-\d{2})*', match[0]):
            return match[0]
        return '[SỐ ĐÃ ẨN]'

    return _NUMERIC_PII.sub(mask_number, value)



def resolve_redacted_address(text: str) -> str | None:
    values = {re.sub(r'(?i)^(?:địa chỉ|dia chi)\s*[:\-]?\s*', '', text[start:end]).strip()
              for start, end in _address_spans(text)}
    return next(iter(values)) if len(values) == 1 else None


def private_delivery_context(text: str, source_turn_id: str, source_on: str) -> dict | None:
    if not _address_spans(text):
        return None
    return {'address': resolve_redacted_address(text), 'source_turn_id': source_turn_id,
            'source_on': source_on, 'source_customer_text': mask_pii(text)}
