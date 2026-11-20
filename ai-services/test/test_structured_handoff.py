from datetime import datetime, timezone

import pytest

from app.agent.harness.handoff_brief import build_handoff_brief
from test_text_harness_contract import turn_state, old_lamp_reads


def source_state():
    state=turn_state('Tôi muốn gặp nhân viên để xác minh cách kết nối thiết bị.')
    state.update(identity_status='known',customer_phone='0900000011',customer_id='C-LOCAL')
    state['session_tool_calls']=old_lamp_reads(state)
    return state


def proposal():
    return {'escalation_reason':'ngoai_pham_vi_tai_lieu',
        'conversation_summary':'Khách cần nhân viên kiểm tra giao thức kết nối thiết bị.',
        'open_questions':['Thiết bị tương thích với bộ điều khiển nào?'],
        'next_action':'Nhân viên liên hệ kỹ thuật để xác minh giao thức.'}


def test_handoff_uses_model_questions_without_inferring_resolutions_or_next_steps():
    state=source_state()
    state['current_episode']={'topics':[{'items':[
        {'kind':'question','text':'Câu hỏi cũ?','status':'open'}]}]}
    candidate=proposal()
    brief=build_handoff_brief(state,candidate,lambda:datetime.now(timezone.utc))
    assert brief.open_questions==candidate['open_questions']
    assert brief.next_action==candidate['next_action']
    assert brief.product_advised is None
    assert state['current_episode']['topics'][0]['items'][0]['status']=='open'


@pytest.mark.parametrize('changes',[
    {'product_advised':'UNKNOWN','price_quoted_vnd':199000},
    {'product_advised':'SKU-LAMP-A','price_quoted_vnd':123456},
    {'product_advised':['SKU-LAMP-A']},
    {'price_quoted_vnd':199000},
    {'escalation_reason':'invented_reason'},
    {'conversation_summary':''},
    {'next_action':''},
])
def test_handoff_rejects_unsupported_commercial_data_or_invalid_model_fields(changes):
    assert build_handoff_brief(source_state(),{**proposal(),**changes},
        lambda:datetime.now(timezone.utc)) is None


def test_handoff_does_not_invent_missing_model_narrative():
    assert build_handoff_brief(source_state(),{'escalation_reason':'khac'},
        lambda:datetime.now(timezone.utc)) is None
