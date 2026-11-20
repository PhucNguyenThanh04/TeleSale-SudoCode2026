
from functools import lru_cache
from uuid import uuid4

from app.agent.factory import build_runtime
from app.agent.harness.runtime import AgentHarnessRuntime
from app.configs import get_settings
from app.schemas.agent import ChatRequest, ChatResponse, TextTurnRequest


@lru_cache(maxsize=1)
def get_runtime() -> AgentHarnessRuntime:
    return build_runtime(get_settings())


async def chat(request: ChatRequest, *, runtime: AgentHarnessRuntime | None = None) -> ChatResponse:
    turn = TextTurnRequest.model_validate({
        **request.model_dump(), "session_id": request.session_id or uuid4(),
    })
    return await (runtime or get_runtime()).run(turn)




async def main() -> None:
    request = ChatRequest(
        client_msg_id=uuid4(),
        session_id="2e83a0f3-f321-98a5-b9d6-9eba9eea1a38",
        channel="hotline",
        channel_identity="0981933190",
        on="2026-10-15",
        text="Alo, hôm trước chị có gọi hỏi máy lọc không khí đó em.",
        input_mode="clean",
    )
    runtime = get_runtime()
    try:
        response = await chat(request, runtime=runtime)
        print(response.model_dump_json(indent=2), flush=True)
    finally:
        if runtime.tracing:
            runtime.tracing.shutdown()


if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
