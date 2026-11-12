"""Recovery preserves the customer's task and remains free of writes."""
from test_commerce_evidence import state,catalog,quote,stock,bind_history_observations


def test_gift_question_not_price_only_and_unknown_name_not_invented():
    from app.agent.harness.session_nodes import safe_consultation_reply
    s=state('Có tặng gì kèm không?');q=quote()
    q['result']['applied_promos']=[{'type':'gift','promo_code':'GIFT-OFFLINE','gift_sku':'SKU-UNKNOWN-GIFT'}]
    s['session_tool_calls']=[catalog(),q]
    s['history']=[{'customer':'Hỏi Aster.','agent':'Aster giá 900.000đ.'}]
    answer=safe_consultation_reply(s)
    assert 'tặng' in answer and 'Aster' in answer
    assert 'màng lọc' not in answer
    assert s['tool_calls']==[]


def test_missing_variant_not_price_confirmation():
    from app.agent.harness.session_nodes import safe_consultation_reply
    s=state('Lấy Aster, lên đơn nhé.')
    s['session_tool_calls']=[catalog(variants=[{'variant_sku':'SKU-ASTER-40','size':40},
        {'variant_sku':'SKU-ASTER-41','size':41}])]
    answer=safe_consultation_reply(s)
    assert 'size' in answer.lower() and 'xác nhận' not in answer.lower()


def test_missing_fields_are_in_prompt_context_and_recovery_passes_verifier():
    import asyncio
    from app.agent.harness.context import prompt_context
    from app.agent.harness.agent_nodes import AgentNodes
    from app.agent.harness.session_nodes import safe_consultation_reply
    s=state('Lấy Aster, lên đơn nhé.')
    s['session_tool_calls']=[catalog(variants=[{'variant_sku':'SKU-ASTER-40','size':40},
        {'variant_sku':'SKU-ASTER-41','size':41}])]
    assert 'size' in prompt_context(s,6)['consultation']['missing_fields']
    s['agent_draft']=safe_consultation_reply(s)
    answer=asyncio.run(AgentNodes(None,None,None,6,6).verify_agent(s))
    assert 'size' in answer['agent_text'].lower()


def test_expired_promo_explained_from_evidence_and_new_offer_requested():
    import asyncio
    from app.agent.harness.agent_nodes import AgentNodes
    from app.agent.harness.session_nodes import safe_consultation_reply
    s=state('Khuyến mãi OLD-OFFLINE hôm trước còn không?');q=quote()
    q['result']['expired_promos']=['OLD-OFFLINE']
    q['result']['applied_promos']=[{'type':'gift','promo_code':'NEW-OFFLINE','gift_sku':'SKU-GIFT'}]
    s['session_tool_calls']=[catalog(),q]
    s['history']=[{'customer':'Tôi hỏi Aster.','agent':'Aster giá 850.000đ.'}]
    s['agent_draft']=safe_consultation_reply(s)
    assert 'hết hạn' in s['agent_draft']
    verified=asyncio.run(AgentNodes(None,None,None,6,6).verify_agent(s))
    assert 'hết hạn' in verified['agent_text'] and 'tặng' in verified['agent_text']


def test_adverse_offer_change_is_explained_before_confirmation():
    from app.agent.harness.session_nodes import safe_consultation_reply
    s=state('Lấy Aster, lên đơn.')
    s['session_tool_calls']=[catalog(),quote()]
    s['history']=[{'customer':'Tôi chọn Aster.','agent':'Aster giá 900.000đ.'}]
    bind_history_observations(s)
    s['tool_calls']=[quote(price=950000),stock()]
    answer=safe_consultation_reply(s)
    assert ('cao hơn' in answer or 'tăng' in answer) and 'đồng ý' in answer


def test_recovery_diagnostics_recognize_task_aware_helper():
    import asyncio
    from app.agent.harness.agent_nodes import AgentNodes
    from app.agent.harness.observability import capture_diagnostic_events
    s=state('Lấy Aster, lên đơn.')
    s['session_tool_calls']=[catalog(variants=[{'variant_sku':'SKU-ASTER-40','size':40},
        {'variant_sku':'SKU-ASTER-41','size':41}])]
    s['agent_draft']='Em đã tạo đơn OD-INVENTED.'
    with capture_diagnostic_events() as events:
        result=asyncio.run(AgentNodes(None,None,None,6,6).verify_agent(s))
    assert 'size' in result['agent_text']
    assert any(e.get('event')=='recovery_succeeded' and e.get('recovery')=='safe_consultation_reply' for e in events)


def test_unrelated_expired_code_does_not_revoke_current_offer():
    from app.agent.harness.session_nodes import safe_consultation_reply
    s=state('Giá hôm trước còn giảm không?');q=quote()
    q['result']['expired_promos']=['OLD-OTHER']
    q['result']['applied_promos']=[{'type':'fixed','promo_code':'CURRENT-SALE','discount_vnd':10000}]
    s['session_tool_calls']=[catalog(),q]
    s['history']=[{'customer':'Hỏi Aster.','agent':'Aster giá 900.000đ.'}]
    answer=safe_consultation_reply(s)
    assert 'không còn áp dụng' not in answer
    assert '900.000' in answer and '10.000' in answer


def test_price_and_promotion_recovery_answers_both_parts():
    from app.agent.harness.session_nodes import safe_consultation_reply
    s=state('Giá bao nhiêu, có giảm gì không?');q=quote()
    q['result']['applied_promos']=[{'type':'freecod','promo_code':'COD-ZERO','discount_vnd':0}]
    s['session_tool_calls']=[catalog(),q]
    s['history']=[{'customer':'Hỏi Aster.','agent':'Em tư vấn Aster.'}]
    answer=safe_consultation_reply(s)
    assert '900.000' in answer and 'COD' in answer


def test_budget_followup_renders_the_verified_shortlist_not_raw_catalog_order():
    from test_consultation_shortlist import consultation_state, QuoteGateway, clock
    from app.agent.implementations.business_agent import BusinessTools
    from app.agent.harness.session_nodes import safe_catalog_reply
    from app.agent.guardrails.checks import check_answer, check_grounding
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    import asyncio
    s = consultation_state()
    asyncio.run(BusinessTools(QuoteGateway(), s, 6, clock).prepare_consultation())
    answer = safe_catalog_reply(s)
    assert 'Aster Air' in answer and '5.200.000' in answer
    assert 'Beryl Air' not in answer and 'Cedar Air' not in answer
    assert 'có khóa trẻ em' in answer and 'không có khóa trẻ em' not in answer
    assert 'vượt mức chi' in answer and 'đồng ý' in answer
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    decision = derive_consultation(s)
    assert decision.snapshot.selected_sku is None and decision.snapshot.accepted_offer is None
    calls = build_commerce_evidence(s)
    assert check_grounding(answer, calls) is None
    assert check_answer(answer, calls, s['safe_text'])[1] is None


def test_grounded_cheaper_advice_cannot_skip_verified_child_safe_option():
    from test_consultation_shortlist import consultation_state, QuoteGateway, clock
    from app.agent.implementations.business_agent import BusinessTools
    from app.agent.harness.agent_nodes import _task_answer_complete
    import asyncio
    s = consultation_state()
    asyncio.run(BusinessTools(QuoteGateway(), s, 6, clock).prepare_consultation())
    assert not _task_answer_complete('Beryl Air có giá 4.800.000đ, không có khóa trẻ em.', s)
    assert _task_answer_complete(
        'Aster Air có giá 5.200.000đ, có khóa trẻ em. Mẫu này vượt mức chi, mình đồng ý điều chỉnh không ạ?', s)


def test_area_float_and_unverified_quotes_do_not_imply_no_catalog_options():
    from test_consultation_shortlist import consultation_state, QuoteGateway, clock
    from app.agent.implementations.business_agent import BusinessTools
    from app.agent.harness.session_nodes import safe_catalog_reply
    import asyncio
    s = consultation_state('Ngân sách khoảng 5 triệu, phòng 25,5m2.')
    gateway = QuoteGateway(); gateway.fail = True
    asyncio.run(BusinessTools(gateway, s, 6, clock).prepare_consultation())
    answer = safe_catalog_reply(s)
    assert 'chưa' in answer.lower()
    assert 'không có sản phẩm' not in answer.lower()
    assert 'Beryl Air' not in answer and 'Cedar Air' not in answer


def test_over_budget_quote_is_explicit_and_does_not_grant_selection():
    from test_consultation_shortlist import consultation_state, QuoteGateway, clock, products
    from app.agent.implementations.business_agent import BusinessTools
    from app.agent.harness.session_nodes import safe_catalog_reply
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    import asyncio
    items = products()[:1]
    s = consultation_state('Ngân sách khoảng 5 triệu, cần tư vấn.', items=items)
    s['history'][0]['agent'] = 'Em sẽ kiểm tra phương án phù hợp.'
    asyncio.run(BusinessTools(QuoteGateway(items), s, 6, clock).prepare_consultation())
    answer = safe_catalog_reply(s)
    assert '5.200.000đ' in answer and 'vượt mức chi' in answer
    assert 'đồng ý' in answer
    from app.agent.guardrails.checks import check_answer, check_grounding
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    assert check_grounding(answer, build_commerce_evidence(s)) is None
    assert check_answer(answer, build_commerce_evidence(s), s['safe_text'])[1] is None
    d = derive_consultation(s)
    assert d.snapshot.selected_sku is None and d.snapshot.accepted_offer is None


def test_grounded_price_for_wrong_product_scope_is_not_a_complete_advice_answer():
    from test_consultation_shortlist import consultation_state, products
    from app.mcp_servers.mcp_shared.consultation_shortlist import consultation_scope
    from app.agent.harness.agent_nodes import _task_answer_complete
    s = consultation_state()
    s['consultation_scope'] = consultation_scope(s)
    buggy = {'sku': 'SKU-BUGGY', 'name': 'Travel Buggy', 'category': 'stroller',
             'variants': [], 'list_price_vnd': 100000, 'attributes': {}}
    s['tool_calls'] = [{'name': 'catalog.search', 'args': {'query': 'alo'},
        'result': {'items': [buggy, *products()]}}]
    s['tool_calls'] += [{'name': 'pricing.get_quote', 'args': {'sku': sku, 'qty': 1, 'on': '2026-11-05'},
        'result': {'sku': sku, 'final_price_vnd': price}} for sku, price in
        [('SKU-BUGGY', 100000), ('SKU-BERYL', 4800000)]]
    assert not _task_answer_complete('Travel Buggy có giá 100.000đ.', s)
    assert _task_answer_complete('Beryl Air có giá 4.800.000đ.', s)


def test_multiple_quantity_advice_cannot_claim_affordability_with_unknown_budget_basis():
    from test_consultation_shortlist import consultation_state
    from app.agent.harness.agent_nodes import _task_answer_complete
    from app.agent.harness.session_nodes import safe_catalog_reply
    s = consultation_state('Tôi cần 2 chiếc Beryl Air, ngân sách 5 triệu.')
    s['tool_calls'] = [{'name': 'pricing.get_quote',
        'args': {'sku': 'SKU-BERYL', 'qty': 2, 'on': '2026-11-05'},
        'result': {'sku': 'SKU-BERYL', 'final_price_vnd': 4800000}}]
    assert not _task_answer_complete('Beryl Air có giá 4.800.000đ, phù hợp ngân sách của mình.', s)
    assert 'mỗi sản phẩm hay tổng cả đơn' in safe_catalog_reply(s)
    assert _task_answer_complete('Beryl Air giá 4.800.000đ. Ngân sách của mình cho mỗi sản phẩm hay tổng cả đơn ạ?', s)


def test_k0_stock_question_is_not_satisfied_by_a_price_only_reply():
    from app.agent.harness.agent_nodes import _task_answer_complete
    from app.agent.harness.session_nodes import safe_product_reply
    s = state('Aster còn hàng chưa em?')
    s['tool_calls'] = [catalog(), quote(), stock()]
    assert not _task_answer_complete('Aster giá 900.000đ.', s)
    reply = safe_product_reply(s)
    assert 'còn hàng' in reply and '900.000' not in reply
    assert _task_answer_complete(reply, s)
    s['tool_calls'][-1]['args']['on'] = '2026-11-04'
    assert safe_product_reply(s) is None


def test_k0_features_answer_uses_the_focused_catalog_and_never_infers_absence():
    from app.agent.harness.agent_nodes import _task_answer_complete
    from app.agent.harness.session_nodes import safe_product_reply
    s = state('Aster có app với khóa trẻ em không em?')
    c = catalog()
    c['result']['items'][0]['attributes'] = {'child_safe_lock': True, 'features': 'HEPA và app điều khiển'}
    s['tool_calls'] = [c, quote()]
    assert not _task_answer_complete('Aster giá 900.000đ.', s)
    reply = safe_product_reply(s)
    assert 'khóa trẻ em' in reply and 'app' in reply and '900.000' not in reply
    assert _task_answer_complete(reply, s)
    c['result']['items'][0]['attributes'] = {}
    reply = safe_product_reply(s)
    assert 'chưa có thông tin' in reply.lower() and 'không có app' not in reply.lower()


def test_k0_status_reply_uses_current_order_result_instead_of_asking_for_known_id():
    from app.agent.harness.agent_nodes import _task_answer_complete
    from app.agent.harness.session_nodes import safe_order_status_reply
    s = state('Anh hỏi tình trạng đơn đã mua hôm trước. Em tra giúp nhé.')
    s['tool_calls'] = [{'name': 'order.status', 'args': {'order_id': 'OD-OFFLINE'},
                        'result': {'orders': [{'order_id': 'OD-OFFLINE', 'status': 'shipping'}]}}]
    assert not _task_answer_complete('Anh cho em xin mã đơn hàng nhé.', s)
    reply = safe_order_status_reply(s)
    assert 'OD-OFFLINE' in reply and 'đơn đang giao' in reply
    assert _task_answer_complete(reply, s)
    s['tool_calls'] = []
    assert safe_order_status_reply(s) is None
