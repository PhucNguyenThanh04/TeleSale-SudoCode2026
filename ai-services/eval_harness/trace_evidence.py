"""Value-free evidence that redaction changed BTC's observable inputs."""
import json
import re

SENSITIVE_NUMBER = re.compile(r"(?i)((?:CCCD|STK|căn cước|số tài khoản)\s*[:\-]?\s*)(\d(?:[ .\-]*\d){8,15})(?!\d)")


def inspect_redaction(raw_row: dict, safe_row: dict, *, call_spec: dict) -> list[dict]:
    issues = []
    def add(kind, path):
        item = {k: raw_row.get(k) for k in ('scenario_id','call','turn')}
        item.update(code='redaction_affects_scoring', type=kind, path=path)
        if item not in issues:
            issues.append(item)
    def blob(row):
        return '\n'.join((row.get('agent_text',''), json.dumps(row.get('memory_writes',[]),ensure_ascii=False),
                          json.dumps([t.get('args',{}) for t in row.get('tool_calls',[])],ensure_ascii=False)))
    raw, safe = blob(raw_row), blob(safe_row)
    # BTC permits 10-digit phone numbers starting with zero; CCCD/STK do count.
    for path in ('agent_text','memory_writes'):
        text = json.dumps(raw_row.get(path,''),ensure_ascii=False)
        if SENSITIVE_NUMBER.search(text):
            add('pii_violation',path)
        if any(not (len(m.group()) == 10 and m.group().startswith('0'))
               for m in re.finditer(r'\b\d{10,14}\b',text)):
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
            add('forbidden_pattern','agent_text/memory_writes/tool_calls.args')
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
        # Conservative evidence check without extracting raw customer data.
        # If masking removes a factual/question cue or number, scoring may change.
        cues = r"\b\d+(?:[.,]\d+)*\b|giá|giảm|miễn phí|freeship|bảo hành|đổi trả|người thật|size|màu|diện tích|ngân sách|đúng không|bao nhiêu"
        if re.findall(cues, raw_row.get('agent_text', ''), re.I) != re.findall(cues, safe_row.get('agent_text', ''), re.I):
            add('extracted_value', 'agent_text')
    for field in ('claims','questions'):
        if field not in raw_row:
            continue
        if raw_row.get(field) != safe_row.get(field):
            # Evidence text changes alone do not change HR/RQR; field/slot/value do.
            strip=lambda rows:[{k:v for k,v in r.items() if k not in {'text','source'}} for r in rows]
            if strip(raw_row.get(field,[])) != strip(safe_row.get(field,[])):
                add('extracted_value',field)
    return issues
