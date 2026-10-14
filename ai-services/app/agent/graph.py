"""Wiring for the explicit one-turn LangGraph."""

from datetime import datetime
from typing import Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.agent.memory.store import MemoryStore
from app.agent.harness.deep_nodes import DeepAgentNodes
from app.agent.harness.state import TurnState
from app.agent.mcp.gateway import ToolGateway
from app.constants import DEFAULT_MAX_TOOL_CALLS, DEFAULT_PROMPT_HISTORY_TURNS


def build_graph(llm: BaseChatModel, tools: ToolGateway, memory: MemoryStore,
                max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
                prompt_history_turns: int = DEFAULT_PROMPT_HISTORY_TURNS,
                clock: Callable[[], datetime] | None = None,
                guardrails_enabled: bool = True):
    """Production outer graph; Deep Agent owns the inner model/tool loop."""
    nodes = DeepAgentNodes(llm, tools, memory, max_tool_calls, prompt_history_turns, clock)
    nodes.guardrails_enabled = guardrails_enabled
    graph = StateGraph(TurnState)
    graph.add_node("accept", nodes.accept)
    graph.add_node("resolve_identity", nodes.resolve_identity)
    graph.add_node("retrieve_context", nodes.retrieve_context)
    graph.add_node("run_deep_agent", nodes.run_deep_agent)
    graph.add_node("verify", nodes.verify_deep)
    graph.add_node("persist", nodes.persist_deep)
    graph.add_edge(START, "accept")
    graph.add_edge("accept", "resolve_identity")
    graph.add_edge("resolve_identity", "retrieve_context")
    graph.add_edge("retrieve_context", "run_deep_agent")
    graph.add_edge("run_deep_agent", "verify")
    graph.add_edge("verify", "persist")
    graph.add_edge("persist", END)
    return graph.compile()
