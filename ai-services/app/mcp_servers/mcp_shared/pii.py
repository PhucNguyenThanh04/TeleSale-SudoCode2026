"""Shared deterministic masking before model, memory and traces."""

import re

_NUMERIC_PII = re.compile(r"(?<!\d)\d{9,14}(?!\d)")
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_ADDRESS = re.compile(r"(?i)\b(?:địa chỉ|dia chi)\s*[:\-]?\s*[^\n.!?]+")
_STREET = re.compile(r"(?i)\b\d+[\w/-]*\s+(?:đường|duong|phố|pho)\b[^\n.!?]*")
_INTRODUCED_NAME = re.compile(r"(?i)\b(?:tên tôi là|ten toi la|tôi là|toi la)\s+[A-ZÀ-Ỹ][\wÀ-ỹ]*(?:\s+[A-ZÀ-Ỹ][\wÀ-ỹ]*){0,3}")

def mask_pii(value: str) -> str:
    value = _EMAIL.sub("[EMAIL ĐÃ ẨN]", value)
    value = _ADDRESS.sub("[ĐỊA CHỈ ĐÃ ẨN]", value)
    value = _STREET.sub("[ĐỊA CHỈ ĐÃ ẨN]", value)
    value = _INTRODUCED_NAME.sub("[TÊN ĐÃ ẨN]", value)
    return _NUMERIC_PII.sub("[SỐ ĐÃ ẨN]", value)

