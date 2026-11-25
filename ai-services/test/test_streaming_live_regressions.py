import asyncio
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessageChunk

from app.agent.harness.streaming import GuardedStream
from test_commerce_evidence import state


def test_short_action_confirmation_does_not_publish_a_generic_acknowledgement():
    async def run():
        current = state('Ok em làm đi nhé.')
        current['history'] = [{'customer': 'Anh muốn đổi sang size lớn hơn.',
                              'agent': 'Mình đồng ý để em cập nhật yêu cầu đổi hàng không ạ?'}]
        sink = AsyncMock(return_value=True)
        stream = GuardedStream(sink)
        await stream.feed(AIMessageChunk(content='Dạ, em sẽ hỗ trợ mình. ', id='confirmation'), current)
        sink.assert_not_awaited()

    asyncio.run(run())
