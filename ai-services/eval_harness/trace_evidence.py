import json
import re

SENSITIVE_NUMBER = re.compile(
    r"(?i)\b((?:CCCD|CMND|STK|căn cước|can cuoc|số tài khoản|so tai khoan)\s*[:\-]?\s*)"
    r"(\d(?:[ .\-]*\d){8,15})(?!\d)")
_SENSITIVE_FIELDS = {'cccd', 'national_id', 'bank_account', 'account_number', 'cmnd', 'stk'}
_MONEY_FIELDS = {'budget_vnd', 'max_price_vnd', 'price_vnd', 'price_quoted_vnd', 'competitor_price_vnd'}
_CURRENCY_NUMBER = re.compile(r'(?i)\b\d+(?:[.,]\d+)*\s*(?:đồng|dong|vnd|₫|đ)(?!\w)')


def contains_sensitive_pii(value, *, field=''):
    field = field.casefold()
    if field in _SENSITIVE_FIELDS and re.search(r'\d', str(value)):
        return True
    if field in _MONEY_FIELDS and type(value) is int:
        return False
    if isinstance(value, list):
        return any(contains_sensitive_pii(item) for item in value)
    if isinstance(value, dict):
        fact_key = value.get('key')
        return any(contains_sensitive_pii(item, field=fact_key if key == 'value' and isinstance(fact_key, str)
                                          else str(key)) for key, item in value.items())
    text = json.dumps(value, ensure_ascii=False)
    if SENSITIVE_NUMBER.search(text):
        return True
    numbers = re.sub(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', '[UUID]', text, flags=re.I)
    numbers = _CURRENCY_NUMBER.sub('', numbers)
    return any(not (len(m[0]) == 10 and m[0].startswith('0'))
               for m in re.finditer(r'\b\d{10,14}\b', numbers))


def inspect_redaction(raw_row: dict, safe_row: dict, *, call_spec: dict) -> list[dict]:
    issues = []
    def add(kind, path):
        item = {k: raw_row.get(k) for k in ('scenario_id','call','turn')}
        item.update(code='redaction_affects_scoring', type=kind, path=path)
        if item not in issues:
            issues.append(item)
    def blob(row):
        return '\n'.join((row.get('agent_text',''), json.dumps(row.get('memory_writes',[]),ensure_ascii=False)))
    raw, safe = blob(raw_row), blob(safe_row)
    for path in ('agent_text','memory_writes'):
        if contains_sensitive_pii(raw_row.get(path, '')):
            add('pii_violation',path)
    si = call_spec.get('success_if') or {}
    if si.get('args_match') and raw_row.get('tool_calls') != safe_row.get('tool_calls'):
        def scored_values(expected, actual):
            if not isinstance(actual,dict):
                return actual
            return {key:scored_values(value, actual.get(key)) if isinstance(value,dict)
                    else actual.get(key) for key,value in expected.items()}
        for index, tool in enumerate(raw_row.get('tool_calls',[])):
            if tool.get('name') != si.get('tool_called'):
                continue
            after = safe_row.get('tool_calls',[])[index]
            if scored_values(si['args_match'],tool.get('args',{})) != scored_values(si['args_match'],after.get('args',{})):
                add('scored_args',f'tool_calls[{index}].args')
    for forbidden in si.get('forbidden_claims',[]):
        if isinstance(forbidden,str) and ((forbidden.lower() in raw_row.get('agent_text','').lower()) !=
                                        (forbidden.lower() in safe_row.get('agent_text','').lower())):
            add('forbidden_speech','agent_text')
    for rx in si.get('trace_must_not_match',[]):
        if bool(re.search(rx,raw)) != bool(re.search(rx,safe)):
            add('forbidden_pattern','agent_text/memory_writes')
    if raw_row.get('agent_text') != safe_row.get('agent_text'):
        for field in ('must_say_any','agent_must_say'):
            values=si.get(field,[])
            if isinstance(values,str):
                values=[values]
            if any((str(v).casefold() in raw_row.get('agent_text','').casefold()) !=
                   (str(v).casefold() in safe_row.get('agent_text','').casefold()) for v in values):
                add('required_speech','agent_text')
    if call_spec.get('memory_expectation'):
        before=json.dumps(raw_row.get('memory_writes',[]),ensure_ascii=False).lower()
        after=json.dumps(safe_row.get('memory_writes',[]),ensure_ascii=False).lower()
        for key,value in call_spec['memory_expectation'].items():
            if key not in {'superseded','must_not_write_to','address_ttl_check','profile_state'}:
                needle=str(value).lower()
                if (needle in before)!=(needle in after):
                    add('memory_checks','memory_writes')
    if 'claims' not in raw_row and raw_row.get('agent_text') != safe_row.get('agent_text'):
        cues = r"\b\d+(?:[.,]\d+)*\b|giá|giảm|miễn phí|freeship|bảo hành|đổi trả|người thật|size|màu|diện tích|ngân sách|đúng không|bao nhiêu"
        if re.findall(cues, raw_row.get('agent_text', ''), re.I) != re.findall(cues, safe_row.get('agent_text', ''), re.I):
            add('extracted_value', 'agent_text')
    for field in ('claims','questions'):
        if field not in raw_row:
            continue
        if raw_row.get(field) != safe_row.get(field):
            strip=lambda rows:[{k:v for k,v in r.items() if k not in {'text','source'}} for r in rows]
            if strip(raw_row.get(field,[])) != strip(safe_row.get(field,[])):
                add('extracted_value',field)
    return issues
