import re

_UNCONFIRMED = re.compile(r'(?i)(?:chưa (?:thể )?(?:xác (?:minh|nhận)|có thông tin)|theo ngày.{0,25}(?:khai|cung cấp)|nếu .{0,100}(?:ngày|đơn|mua)|cần (?:xác (?:minh|nhận)|kiểm tra))')
_ENTITLEMENT = re.compile(r'(?i)(?:đủ điều kiện|cam kết|(?:em|shop|bên em)\s+(?:sẽ|đảm bảo)\s+(?:hoàn|đổi|trả)|(?:đơn|anh|chị|bạn|khách).{0,35}\bđược\s+(?:đổi|trả|hoàn|bảo hành))')
_PII_REFUSAL = re.compile(
    r'(?i)\b(?:không (?:được phép |thể )?(?:lưu|ghi nhận|nhắc lại|đọc lại|thu thập))\b'
    r'.{0,90}\b(?:thông tin|tài khoản|ngân hàng|cccd|thẻ|nhạy cảm|cá nhân|dãy số|số tài khoản|biểu mẫu|form)\b'
)


def policy_evidence_for_answer(candidate, calls):
    conditional_explanation = bool(_UNCONFIRMED.search(candidate)) and not _ENTITLEMENT.search(candidate)
    evidence=[]
    for call in calls:
        result=call.get('result',{})
        if call.get('name')!='policy.search' or 'error' in result:
            continue
        for row in result.get('evidence',[]):
            if not isinstance(row,dict) or not isinstance(row.get('content'),str):
                continue
            applicability=row.get('applicability',{})
            status=applicability.get('status','applicable')
            if status=='applicable' or (status=='conditional' and conditional_explanation):
                evidence.append(row)
    return evidence


def policy_clarification_or_refusal(candidate):
    if re.fullmatch(
            r'(?:Dạ[, ]+)?(?:anh/chị|anh|chị) cho em (?:xin|biết) '
            r'(?:tên sản phẩm|mã sản phẩm|mã đơn hàng)(?: ạ)?[.?]?',
            candidate.strip(), re.IGNORECASE):
        return True
    if _PII_REFUSAL.search(candidate) and not (
            _ENTITLEMENT.search(candidate) or re.search(r'\b\d+\s+(?:ngày|tháng|năm)\b', candidate, re.IGNORECASE)):
        return True
    return (bool(_UNCONFIRMED.search(candidate)) or candidate.rstrip().endswith('?')) and not (
        _ENTITLEMENT.search(candidate) or re.search(r'\d',candidate))


def policy_durations_supported(candidate, source_text):
    def durations(text):
        return {(int(n) * (12 if unit == 'năm' else 1),
                 'ngày' if unit == 'ngày' else 'tháng')
                for n, unit in re.findall(r'\b(\d+)\s+(ngày|tháng|năm)\b', text.casefold())}
    if not durations(candidate) <= durations(source_text):
        return False
    universal = re.compile(r'(?i)\b(?:mọi|tất cả|bất kỳ|toàn bộ)\b')
    conditional = re.compile(r'(?i)\b(?:riêng|chỉ|nếu|khi|trừ|đối với|áp dụng cho)\b')
    sources = re.split(r'[.;!?\n]', source_text)
    for clause in re.split(r'[.;!?\n]', candidate):
        if not universal.search(clause) or conditional.search(clause):
            continue
        for duration in durations(clause):
            support = [part for part in sources if duration in durations(part)]
            if support and all(conditional.search(part) for part in support):
                return False
    return True
