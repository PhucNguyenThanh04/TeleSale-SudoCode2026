import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.agent.harness.authorization import authorize_write
from app.agent.harness.context import load_context, prompt_context
from app.agent.harness.policy import prepare_tool_call
from app.agent.harness.state import Decision
from app.agent.memory.store import MCPMemoryStore
from app.mcp_servers.mcp_memory.services.memory import read, write
from app.schemas.agent import TextTurnRequest


ADDRESS = '12 đường Hoa Mai, Hà Nội'


class Repo:
    supports_private_delivery = True

    def __init__(self):
        self.saved = []
        self.operations = {}

    @asynccontextmanager
    async def transaction(self):
        yield object()

    async def owner(self, *args):
        return None

    async def lock_key(self, *args):
        pass

    async def next_turn(self, *args):
        return len(self.saved) + 1

    async def turn_count(self, *args):
        return len(self.saved)

    async def recent_turns(self, *args):
        return self.saved[-12:]

    async def session_context_turns(self, *args):
        return self.saved

    async def insert_turn(self, conn, session, number, customer_id, channel, on, customer_text,
                          agent_text, client_msg_id, observations, outcome, *, private_delivery=None):
        self.saved.append({'customer_text': customer_text, 'agent_text': agent_text,
            'client_msg_id': client_msg_id, 'private_delivery': private_delivery})

    async def latest_delivery(self, *args, **kwargs):
        return next((row['private_delivery'] for row in reversed(self.saved)
                     if row['private_delivery'] is not None), None)

    async def claim_operation(self, conn, key, digest):
        return self.operations.get(key)

    async def finish_operation(self, conn, key, result):
        self.operations[key] = result


def test_delivery_reference_survives_commit_and_a_new_harness_view_without_entering_prompt():
    async def run():
        from app.mcp_servers.mcp_shared.pii import private_delivery_context
        repo = Repo()
        session, tid = str(uuid4()), str(uuid4())
        source = f'Giao tới địa chỉ {ADDRESS}; tôi sẽ chốt sau.'
        delivery = private_delivery_context(source, tid, '2026-10-15')

        async def invoke(name, args):
            return await (write(repo, **args) if name == 'memory.write' else read(repo, **args))

        store = MCPMemoryStore(SimpleNamespace(invoke=invoke))
        await store.commit_turn(session, None, 'Giao tới [ĐỊA CHỈ ĐÃ ẨN], tôi sẽ chốt sau.',
            'Dạ.', '2026-10-15', 'hotline', tid, private_delivery=delivery)
        request = TextTurnRequest(session_id=session, client_msg_id=uuid4(), channel='hotline',
            channel_identity='0900000000', on='2026-10-15', input_mode='clean',
            text='Chốt đơn và giao địa chỉ vừa cung cấp nhé.')
        state = {'request': request, 'safe_text': request.text, 'customer_id': None,
            'identity_status': 'unknown', 'received_at_monotonic': 0, 'tool_calls': [
                {'name': 'catalog.search', 'args': {'sku': 'ITEM'},
                 'result': {'items': [{'sku': 'ITEM', 'variants': []}]}}]}
        state.update(await load_context(state, store, None, lambda: datetime.now(timezone.utc)))
        visible = json.dumps(prompt_context(state, 6), ensure_ascii=False)
        assert ADDRESS not in visible
        assert state['private_delivery']['address'] == ADDRESS
        state['decision'] = Decision(action='tool', tool_name='pricing.get_quote',
            tool_args={'sku': 'ITEM', 'address': '[ĐỊA CHỈ ĐÃ ẨN]'})
        prepared = prepare_tool_call(state, lambda: datetime.now(timezone.utc))
        assert prepared[1]['address'] == ADDRESS
        assert ADDRESS not in repo.saved[0]['customer_text']
        assert ADDRESS in json.dumps(repo.saved[0]['private_delivery'], ensure_ascii=False)
    asyncio.run(run())


def test_write_reviewer_gets_masked_historical_address_source_and_current_consent():
    async def run():
        from app.mcp_servers.mcp_shared.pii import private_delivery_context
        request = TextTurnRequest(session_id=uuid4(), client_msg_id=uuid4(), channel='hotline',
            channel_identity='0900000000', on='2026-10-15', input_mode='clean',
            text='Tạo đơn và giao chỗ vừa cung cấp nhé.')
        state = {'request': request, 'safe_text': request.text, 'identity_status': 'known',
            'customer_id': 'C1', 'private_delivery': private_delivery_context(
                f'Giao địa chỉ {ADDRESS}', str(uuid4()), '2026-10-15')}

        async def review(messages):
            payload = json.loads(messages[-1].content)
            assert ADDRESS not in messages[-1].content
            context = payload['address_context']
            assert context['source_customer_text'] == 'Giao [ĐỊA CHỈ ĐÃ ẨN]'
            assert context['source_turn_id'] == state['private_delivery']['source_turn_id']
            assert not context['mentioned_in_current_customer_text']
            return {'allowed': True, 'basis': 'customer_request', 'reason': 'authorized',
                    'customer_quote': request.text}

        model = SimpleNamespace(with_structured_output=lambda *a, **kw: SimpleNamespace(ainvoke=review))
        assert await authorize_write(model, state, 'order.create', {'address': ADDRESS}, 6)
    asyncio.run(run())


def test_ambiguous_new_addresses_invalidate_an_older_reference():
    from app.mcp_servers.mcp_shared.pii import private_delivery_context
    record = private_delivery_context('Địa chỉ 12 đường Hoa Mai; địa chỉ 34 đường Hoa Đào',
                                      str(uuid4()), '2026-10-15')
    assert record is not None and record['address'] is None


def test_stale_private_delivery_is_not_reused_as_current_shipping_evidence():
    async def run():
        from app.mcp_servers.mcp_shared.pii import private_delivery_context
        repo = Repo()
        repo.saved = [{'customer_text': 'Dạ', 'agent_text': '', 'client_msg_id': str(uuid4()),
            'private_delivery': private_delivery_context(f'Địa chỉ {ADDRESS}', str(uuid4()), '2026-01-01')}]

        async def invoke(name, args):
            return await read(repo, **args)

        request = TextTurnRequest(session_id=uuid4(), client_msg_id=uuid4(), channel='hotline',
            channel_identity='0900000000', on='2026-10-15', text='Giao chỗ cũ', input_mode='clean')
        context = await load_context({'request': request, 'safe_text': request.text,
            'identity_status': 'unknown', 'customer_id': None, 'tool_calls': []},
            MCPMemoryStore(SimpleNamespace(invoke=invoke)), None, lambda: datetime.now(timezone.utc))
        assert context.get('private_delivery') is None
    asyncio.run(run())
