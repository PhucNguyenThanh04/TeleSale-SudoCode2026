"""Wiring for the explicit one-turn LangGraph."""

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.agent.memory import MemoryStore
from app.agent.nodes import AgentNodes
from app.agent.state import TurnState
from app.agent.tool_gateway import ToolGateway


def build_graph(llm: BaseChatModel, tools: ToolGateway, memory: MemoryStore,
                max_tool_calls: int = 3, prompt_history_turns: int = 6):
    nodes = AgentNodes(llm, tools, memory, max_tool_calls, prompt_history_turns)
    graph = StateGraph(TurnState)
    graph.add_node("accept", nodes.accept)
    graph.add_node("resolve_identity", nodes.resolve_identity)
    graph.add_node("retrieve_context", nodes.retrieve_context)
    graph.add_node("plan", nodes.plan)
    graph.add_node("call_tool", nodes.call_tool)
    graph.add_node("quote_catalog", nodes.quote_catalog)
    graph.add_node("verify", nodes.verify)
    graph.add_node("persist", nodes.persist)
    graph.add_edge(START, "accept")
    graph.add_edge("accept", "resolve_identity")
    graph.add_edge("resolve_identity", "retrieve_context")
    graph.add_edge("retrieve_context", "plan")
    graph.add_conditional_edges("plan", nodes.route_plan, {"call_tool": "call_tool", "verify": "verify"})
    graph.add_conditional_edges("call_tool", nodes.route_tool,
                                {"plan": "plan", "verify": "verify",
                                 "quote_catalog": "quote_catalog"})
    graph.add_edge("quote_catalog", "verify")
    graph.add_edge("verify", "persist")
    graph.add_edge("persist", END)
    return graph.compile()
