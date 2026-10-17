"""Public Python entrypoint for one text chat turn."""

from functools import lru_cache
from uuid import uuid4

from app.agent.factory import build_runtime
from app.agent.harness.runtime import AgentHarnessRuntime
from app.configs import get_settings
from app.schemas.agent import ChatRequest, ChatResponse, TextTurnRequest


@lru_cache(maxsize=1)
def get_runtime() -> AgentHarnessRuntime:
    """Reuse locks and duplicate-response cache in this process."""
    return build_runtime(get_settings())


async def chat(request: ChatRequest, *, runtime: AgentHarnessRuntime | None = None) -> ChatResponse:
    """Run one turn; a new conversation gets a session ID in the response."""
    turn = TextTurnRequest.model_validate({
        **request.model_dump(), "session_id": request.session_id or uuid4(),
    })
    return await (runtime or get_runtime()).run(turn)




async def main() -> None:
    # Chỉnh request này để chạy thử một lượt chat, không cần tham số dòng lệnh.
    request = ChatRequest(
        client_msg_id=uuid4(),
        session_id="3195dd44-b9cc-417e-bde5-b1f6b3e63146",
        channel="zalo_oa",
        channel_identity="zalo_lan79",
        on="2026-10-15",
        text="Ừ để chị hỏi ông xã rồi gọi lại em nhé.",
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
