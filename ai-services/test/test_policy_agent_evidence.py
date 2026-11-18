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
    from app.agent.guardrails.checks import FALLBACK
    from test_text_harness_contract import turn_state, nodes
    state = turn_state('Chính sách bảo hành thế nào?')
    state.update(agent_draft='Cloudflare hết quota ạ.',
        tool_calls=[{'name':'policy.search','args':{},'result':{
            'retrieval_status':'unavailable','error':'knowledge_unavailable','evidence':[]}}])
    node, _ = nodes()
    from langchain_core.messages import AIMessage
    node.llm.ainvoke.return_value = AIMessage(content=FALLBACK)
    result = asyncio.run(node.verify_agent(state))
    assert result['agent_text'] == FALLBACK
    assert node.llm.ainvoke.await_count == 1


def test_mixed_tool_failure_can_repair_the_current_answer_using_supported_evidence():
    import asyncio
    from langchain_core.messages import AIMessage
    from test_text_harness_contract import turn_state, old_lamp_reads, nodes
    state = turn_state('Đèn bàn Aurora giá bao nhiêu?')
    state.update(agent_draft='Đèn bàn Aurora giá 500000đ.', tool_calls=old_lamp_reads(state))
    state['tool_calls'].append({'name':'policy.search','args':{},'result':{
        'retrieval_status':'unavailable','error':'knowledge_unavailable','evidence':[]}})
    node, _ = nodes()
    node.llm.ainvoke.return_value = AIMessage(content='Đèn bàn Aurora giá 199000đ.')
    result = asyncio.run(node.verify_agent(state))
    assert result['agent_text'] == 'Đèn bàn Aurora giá 199000đ.'
    assert node.llm.ainvoke.await_count == 1
    assert 'quota' not in result['agent_text']
