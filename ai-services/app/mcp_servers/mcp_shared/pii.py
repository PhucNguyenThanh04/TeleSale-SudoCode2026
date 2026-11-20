
import re

_NUMERIC_PII = re.compile(r"(?<!\d)\d{9,14}(?!\d)")
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_ADDRESS = re.compile(
    r"(?i)\b(?:địa chỉ|dia chi)(?! ĐÃ ẨN\])(?:\s*[:\-]\s*[^\n.!?]+|"
    r"\s+(?!(?:cũ|cu|mới|moi|nhận|nhan|giao|của|cua|ở\s+đâu|o\s+dau|"
    r"nào|nao|để|de|và|va|giúp|giup|nhé|nhe|ạ|a|chưa|chua|không|khong)\b)[^\n.!?]+)"
)
_STREET = re.compile(r"(?i)\b\d+[\w/-]*\s+(?:đường|duong|phố|pho)\b[^\n.!?]*")
_ALLEY = re.compile(r"(?i)\b(?:(?:số\s*)?\d+[\w/-]*\s+(?:ngõ|ngo|ngách|ngach|hẻm|hem)|(?:ngõ|ngo|ngách|ngach|hẻm|hem)\s+\d+[\w/-]*)\b[^\n.!?]*")
_APARTMENT = re.compile(r"(?i)\b(?:căn(?:\s+hộ)?|can(?:\s+ho)?)\s+[A-Z]?\d+[\w/-]*\b[^\n.!?]*")
_INTRODUCED_NAME = re.compile(r"(?i)\b(?:tên tôi là|ten toi la|tôi là|toi la)\s+[A-ZÀ-Ỹ][\wÀ-ỹ]*(?:\s+[A-ZÀ-Ỹ][\wÀ-ỹ]*){0,3}")
_PERSON_NAME = re.compile(r"\b(?:Nguyễn|Trần|Lê|Phạm|Hoàng|Huỳnh|Phan|Vũ|Võ|Đặng|Bùi|Đỗ|Hồ|Ngô|Dương|Lý)\s+[A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,2}\b")

def mask_pii(value: str) -> str:
    value = _EMAIL.sub("[EMAIL ĐÃ ẨN]", value)
    value = _ADDRESS.sub("[ĐỊA CHỈ ĐÃ ẨN]", value)
    value = _STREET.sub("[ĐỊA CHỈ ĐÃ ẨN]", value)
    value = _ALLEY.sub("[ĐỊA CHỈ ĐÃ ẨN]", value)
    value = _APARTMENT.sub("[ĐỊA CHỈ ĐÃ ẨN]", value)
    value = _INTRODUCED_NAME.sub("[TÊN ĐÃ ẨN]", value)
    value = _PERSON_NAME.sub("[TÊN ĐÃ ẨN]", value)
    return _NUMERIC_PII.sub("[SỐ ĐÃ ẨN]", value)



def resolve_redacted_address(text: str) -> str | None:
    matches = [match for pattern in (_ADDRESS, _STREET, _ALLEY, _APARTMENT)
               for match in pattern.finditer(text)]
    values = {re.sub(r'(?i)^(?:địa chỉ|dia chi)\s*[:\-]?\s*', '', match[0]).strip()
              for match in matches if not any(other.start() <= match.start()
                  and other.end() >= match.end() and other.span() != match.span()
                  for other in matches)}
    return next(iter(values)) if len(values) == 1 else None
