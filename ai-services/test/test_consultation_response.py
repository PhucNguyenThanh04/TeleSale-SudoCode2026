from test_commerce_evidence import state,catalog,quote,stock,bind_history_observations












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
