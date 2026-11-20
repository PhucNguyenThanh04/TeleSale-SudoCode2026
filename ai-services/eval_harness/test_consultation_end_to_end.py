from eval_harness.test_support import VoiceLifecycleStub
import asyncio
from copy import deepcopy
from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.agent.implementations.business_agent import BusinessTools
from app.agent.harness.agent_nodes import AgentNodes
from app.mcp_servers.mcp_memory.services.langmem_admission import admit_episode_candidate
from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta
from app.schemas.langmem import CustomerCallEpisodeCandidate
from eval_harness.benchmark_runner import run_configuration
from eval_harness.turn_diagnostics import verify_turn_diagnostics


class Runtime(VoiceLifecycleStub):
    def __init__(self, sku, name, price, *, new_price=None):
        self.sku,self.name,self.price=sku,name,price
        self.new_price=new_price
        self.memory=SimpleNamespace(include_prior=True,namespace='')
        self.states={};self.sessions={};self.episodes={};self.trades=[]
        self.nodes=AgentNodes(None,None,None,8,6)


    def state_for(self,request):return self.states[str(request.client_msg_id)]




def test_changed_quote_requires_customer_confirmation_before_write(tmp_path):
    runtime=Runtime('SKU-ASTER','Aster',900000,new_price=950000)
    scenarios={'DIFFERENT-ID':{'calls':{'call_1':{'customer_turns':['Tư vấn máy, ngân sách 1 triệu.','Tôi chọn Aster để xem giá.']},
        'call_2':{'customer_turns':['Lên đơn Aster giá 900.000đ.']}}}}
    asyncio.run(run_configuration(scenarios=scenarios,config='full',runtime=runtime,run_id='scripted',out=tmp_path/'trace.jsonl',
        wait_for_jobs=AsyncMock(),capture_writes=AsyncMock(return_value={})))
    assert runtime.trades==[]
