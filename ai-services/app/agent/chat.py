"""Public Python entrypoint for one text chat turn."""

from functools import lru_cache
from uuid import uuid4

from app.agent.memory import MCPMemoryStore
from app.agent.observability import configure_agent_logging
from app.agent.runtime import HarnessRuntime
from app.agent.tool_gateway import MCPGateway
from app.configs import Settings, get_settings
from app.infarstructure.llm import build_llm
from app.schemas.agent import ChatRequest, ChatResponse, TextTurnRequest


def build_runtime(settings: Settings) -> HarnessRuntime:
    """Build the production agent using the three MCP servers."""
    configure_agent_logging(settings.log_level)
    if not all((settings.mcp_catalog_url, settings.mcp_order_url,
                settings.mcp_memory_url, settings.mcp_internal_token)):
        raise RuntimeError("Configure all three MCP URLs and MCP_INTERNAL_TOKEN")
    gateway = MCPGateway(settings.mcp_catalog_url, settings.mcp_order_url,
                         settings.mcp_memory_url,
                         settings.mcp_internal_token.get_secret_value())
    memory = MCPMemoryStore(gateway, max_episodes=settings.memory_max_episodes)
    return HarnessRuntime(build_llm(settings), gateway, memory,
                          max_tool_calls=settings.agent_max_tool_calls,
                          prompt_history_turns=settings.agent_prompt_history_turns)


@lru_cache(maxsize=1)
def get_runtime() -> HarnessRuntime:
    """Reuse locks and duplicate-response cache in this process."""
    return build_runtime(get_settings())


async def chat(request: ChatRequest, *, runtime: HarnessRuntime | None = None) -> ChatResponse:
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
        response = await chat(ChatRequest(
            client_msg_id=uuid4(),
            session_id="84c277f8-e25d-43df-8ede-5dd2f026e126",
            channel="chat_fanpage",
            channel_identity="fb.dasdsa.aa1ss",
            on=date(2026, 9, 15),
            text="Ok em lên đơn cho anh, thanh toán COD nhé.",
            input_mode="chat_teencode",
        ))
        print(response.model_dump_json(indent=2))

    asyncio.run(main())
