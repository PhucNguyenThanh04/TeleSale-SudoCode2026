"""LangChain ReAct implementation using the same business tools and harness."""

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel

from app.agent.implementations.business_agent import (
    BusinessOnlyMiddleware, BusinessTools, _SYSTEM_PROMPT,
)


def build_react_agent(model: BaseChatModel, tools: BusinessTools):
    return create_agent(model=model, tools=tools.langchain_tools(),
                        system_prompt=_SYSTEM_PROMPT,
                        middleware=[BusinessOnlyMiddleware()])
