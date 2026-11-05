from eval_harness.trace_evidence import inspect_redaction
from eval_harness.reference_adapter import _safe_tool_calls


def test_redaction_preserves_brief_types_and_tool_names():
    tools = [{'id':'t1','name':'handoff.transfer','args':{'brief':{
        'customer_name':'Lan','customer_phone':'0912345678','escalation_reason':'khac',
        'open_questions':['địa chỉ: 12 đường X'], 'price_quoted_vnd':50000,
        'conversation_summary':'địa chỉ: 12 đường X'}}}]
    safe = _safe_tool_calls(tools)
    assert safe[0]['name']=='handoff.transfer' and safe[0]['id']=='t1'
    brief=safe[0]['args']['brief']
    assert brief['escalation_reason']=='khac'
    assert brief['price_quoted_vnd']==50000
    assert isinstance(brief['open_questions'],list)
    assert 'Lan' not in str(brief) and '0912345678' not in str(brief)


def test_pii_or_scored_args_redaction_is_never_a_clean_run():
    raw={'scenario_id':'X','call':'call_1','turn':1,'agent_text':'STK 123456789012',
         'tool_calls':[{'name':'order.create','args':{'address':'12 đường X'}}], 'memory_writes':[]}
    safe={**raw,'agent_text':'STK [SỐ ĐÃ ẨN]', 'tool_calls':_safe_tool_calls(raw['tool_calls'])}
    issues=inspect_redaction(raw,safe,call_spec={'success_if':{'args_match':{'address':'12 đường X'}}})
    assert issues and all(x['code']=='redaction_affects_scoring' for x in issues)
    assert '123456789012' not in str(issues) and '12 đường X' not in str(issues)


def test_memory_provenance_remapping_alone_does_not_invalidate_scoring():
    raw={'scenario_id':'X','call':'call_1','turn':1,'memory_writes':[
        {'key':'size','value':41,'op':'set','source':'langmem:old:t1'}]}
    safe={**raw,'memory_writes':[{**raw['memory_writes'][0],'source':'call_1#turn1'}]}
    assert inspect_redaction(raw,safe,call_spec={'memory_expectation':{'size':41}})==[]


def test_accepted_writes_mask_known_name_and_numeric_pii():
    from eval_harness.reference_adapter import public_memory_writes
    writes=[{'key':'bank_account','value':123456789012,'op':'set','evidence_quote':'Lan cung cấp STK 123456789012'}]
    result=public_memory_writes('call_1',1,writes,customer_name='Lan')
    assert 'Lan' not in str(result) and '123456789012' not in str(result)


def test_forbidden_speech_and_changed_scored_arg_remain_invalid_even_if_wrong():
    raw={'scenario_id':'X','call':'call_1','turn':1,'agent_text':'Lan',
         'tool_calls':[{'name':'order.create','args':{'address':'private address'}}]}
    safe={**raw,'agent_text':'[TÊN ĐÃ ẨN]', 'tool_calls':_safe_tool_calls(raw['tool_calls'])}
    issues=inspect_redaction(raw,safe,call_spec={'success_if':{'forbidden_claims':['Lan'],
        'tool_called':'order.create','args_match':{'address':'expected other address'}}})
    assert {i['type'] for i in issues} >= {'forbidden_speech','scored_args'}


def test_short_address_memory_and_nested_brief_are_masked_by_field_path():
    from eval_harness.reference_adapter import public_memory_writes
    writes=[{'key':'address','value':'12 Lê Lợi','op':'set','evidence_quote':'Giao tới 12 Lê Lợi'}]
    assert '12 Lê Lợi' not in str(public_memory_writes('call_1',1,writes))
    tool={'name':'handoff.transfer','args':{'brief':{'facts_confirmed':{'address':'12 Lê Lợi'}}}}
    assert '12 Lê Lợi' not in str(_safe_tool_calls([tool]))


def test_spaced_account_number_is_masked_without_reporting_clean():
    from eval_harness.reference_adapter import trace_line
    issues=[]
    row=trace_line('r','full','X','call_1',1,'chào','Số tài khoản: 1234 5678 9012',[],[],[],10,None,'clean',safety_issues=issues)
    assert '1234 5678 9012' not in row['agent_text']
    assert any(i['type']=='pii_violation' for i in issues)
