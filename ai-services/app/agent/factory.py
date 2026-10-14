"""Assemble the active agent, harness, memory and MCP adapters."""

from app.agent.harness.observability import configure_agent_logging
from app.agent.harness.runtime import DeepHarnessRuntime
from app.agent.harness.tracing import LangfuseTracing
from app.agent.mcp.gateway import MCPGateway
from app.agent.memory.store import MCPMemoryStore
from app.configs import Settings
from app.infarstructure.llm import build_llm


def build_runtime(settings: Settings) -> DeepHarnessRuntime:
    """Build the production Deep Agent runtime using the three MCP servers."""
    configure_agent_logging(settings.log_level)
    if not all((settings.mcp_catalog_url, settings.mcp_order_url,
                settings.mcp_memory_url, settings.mcp_internal_token)):
        raise RuntimeError("Configure all three MCP URLs and MCP_INTERNAL_TOKEN")
    gateway = MCPGateway(settings.mcp_catalog_url, settings.mcp_order_url,
                         settings.mcp_memory_url,
                         settings.mcp_internal_token.get_secret_value())
    memory = MCPMemoryStore(gateway, max_episodes=settings.memory_max_episodes)
    return DeepHarnessRuntime(build_llm(settings), gateway, memory,
                              max_tool_calls=settings.agent_max_tool_calls,
                              prompt_history_turns=settings.agent_prompt_history_turns,
                              guardrails_enabled=settings.agent_guardrails_enabled,
                              tracing=LangfuseTracing(settings) if settings.langfuse_enabled else None)
