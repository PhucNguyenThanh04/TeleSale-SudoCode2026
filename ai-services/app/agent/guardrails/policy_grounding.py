"""Policy evidence eligibility, keeping conditional explanations distinct from entitlement."""
import re

_UNCONFIRMED = re.compile(r'(?i)(?:chưa (?:thể )?(?:xác (?:minh|nhận)|có thông tin)|theo ngày.{0,25}(?:khai|cung cấp)|nếu .{0,100}(?:ngày|đơn|mua)|cần (?:xác (?:minh|nhận)|kiểm tra))')
_ENTITLEMENT = re.compile(r'(?i)(?:đủ điều kiện|cam kết|(?:em|shop|bên em)\s+(?:sẽ|đảm bảo)\s+(?:hoàn|đổi|trả)|(?:đơn|anh|chị|bạn|khách).{0,35}\bđược\s+(?:đổi|trả|hoàn|bảo hành))')


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
    return (bool(_UNCONFIRMED.search(candidate)) or candidate.rstrip().endswith('?')) and not (
        _ENTITLEMENT.search(candidate) or re.search(r'\d',candidate))
