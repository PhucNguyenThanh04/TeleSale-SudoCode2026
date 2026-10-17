"""Select an agent implementation without changing the outer harness."""

from typing import Literal

from app.agent.implementations.deep_agent import build_deep_agent
from app.agent.implementations.react_agent import build_react_agent

AgentKind = Literal["deep", "react"]

BUILDERS = {"deep": build_deep_agent, "react": build_react_agent}


def build_agent(kind: AgentKind, model, tools):
    try:
        builder = BUILDERS[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown agent kind: {kind}") from exc
    return builder(model, tools)
