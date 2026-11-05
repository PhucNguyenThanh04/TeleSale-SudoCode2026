from app.agent.guardrails.checks import check_answer


def call(status='applicable',missing=None):
    return {'name':'policy.search','args':{'query':'đổi trả'},'result':{'retrieval_status':'ok',
        'evidence':[{'chunk_id':'DT-01','content':'Đổi trả trong 7 ngày.', 'evidence_type':'business_rule',
        'applicability':{'status':status,'required_context':['order_date'] if status=='conditional' else [],
                         'missing_required_section_ids':missing or []}}]}}


def test_new_evidence_schema_is_used_for_policy_grounding():
    answer='Chính sách đổi trả trong 7 ngày.'
    assert check_answer(answer,[call()])[1] is None
    assert check_answer('Chính sách đổi trả trong 14 ngày.',[call()])[1] is not None


def test_conditional_explanation_cannot_confirm_order_entitlement():
    assert check_answer('Theo ngày anh khai, chính sách đổi trả là 7 ngày; em chưa xác minh quyền lợi của đơn.',[call('conditional')])[1] is None
    assert check_answer('Đơn của anh đủ điều kiện đổi trả trong 7 ngày.',[call('conditional')])[1] is not None
    assert check_answer('Em cam kết hoàn tiền cho đơn này.',[call('conflict')])[1] is not None


def test_missing_exception_does_not_authorize_unqualified_policy():
    assert check_answer('Chính sách đổi trả trong 7 ngày.',[call('conditional',['CL-01'])])[1] is not None


def test_unverified_policy_rights_are_blocked_even_with_optional_checks_disabled():
    import asyncio
    from app.agent.harness.agent_nodes import AgentNodes
    nodes=AgentNodes(None,None,None,5,3)
    nodes.guardrails_enabled=False
    answer='Đơn của anh đủ điều kiện đổi trả trong 7 ngày.'
    result=asyncio.run(nodes.verify_agent({'agent_draft':answer,'safe_text':'đổi trả?',
        'tool_calls':[call('conditional')]}))
    assert result['agent_text']!=answer


def test_operational_policy_failure_has_generic_customer_message():
    import asyncio
    from app.agent.harness.agent_nodes import AgentNodes
    state={'safe_text':'bảo hành?', 'agent_draft':'Cloudflare hết quota ạ.',
        'tool_calls':[{'name':'policy.search','args':{},'result':{
            'retrieval_status':'unavailable','error':'knowledge_unavailable','evidence':[]}}]}
    result=asyncio.run(AgentNodes(None,None,None,5,3).verify_agent(state))
    assert result['agent_text']=='Tạm thời chưa tra cứu được thông tin, vui lòng thử lại sau.'


def test_mixed_tool_failure_preserves_supported_answer():
    import asyncio
    from app.agent.harness.agent_nodes import AgentNodes
    from test_promotion_recovery import _state
    state=_state()
    state['tool_calls'].append({'name':'policy.search','args':{},'result':{
        'retrieval_status':'unavailable','error':'knowledge_unavailable','evidence':[]}})
    result=asyncio.run(AgentNodes(None,None,None,5,3).verify_agent(state))
    assert 'Máy lọc A' in result['agent_text']
    assert 'Tạm thời chưa tra cứu được thông tin, vui lòng thử lại sau.' in result['agent_text']
    assert 'quota' not in result['agent_text']
