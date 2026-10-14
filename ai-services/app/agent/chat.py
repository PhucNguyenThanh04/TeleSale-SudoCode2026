"""Public Python entrypoint for one text chat turn."""

from functools import lru_cache
from uuid import uuid4

from app.agent.factory import build_runtime
from app.agent.harness.runtime import DeepHarnessRuntime
from app.configs import get_settings
from app.schemas.agent import ChatRequest, ChatResponse, TextTurnRequest


@lru_cache(maxsize=1)
def get_runtime() -> DeepHarnessRuntime:
    """Reuse locks and duplicate-response cache in this process."""
    return build_runtime(get_settings())


async def chat(request: ChatRequest, *, runtime: DeepHarnessRuntime | None = None) -> ChatResponse:
    """Run one turn; a new conversation gets a session ID in the response."""
    turn = TextTurnRequest.model_validate({
        **request.model_dump(), "session_id": request.session_id or uuid4(),
    })
    return await (runtime or get_runtime()).run(turn)


if __name__ == "__main__":
    import asyncio
    from datetime import date
    from uuid import uuid4

    async def main():
        runtime = get_runtime()
        try:
            response = await chat(ChatRequest(
                client_msg_id=uuid4(),
                session_id=uuid4(),
                channel="chat_fanpage",
                channel_identity="fb.xuân.519",
                on=date(2026, 10, 15),
                text="chị nhớ nhầm phòng chị khoảng 62 mét vuông thì có sử dụng được không em ",
                input_mode="chat_teencode",
            ), runtime=runtime)
            print(response.model_dump_json(indent=2))
        finally:
            if runtime.tracing:
                runtime.tracing.flush()

    asyncio.run(main())
