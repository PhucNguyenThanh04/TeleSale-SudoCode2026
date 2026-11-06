"""Deep Agent implementation for the common business tool contract."""

from deepagents import create_deep_agent
from langchain_core.language_models.chat_models import BaseChatModel

from app.agent.implementations.tool_names import model_tool_instructions
from app.agent.implementations.business_agent import (
    BusinessOnlyMiddleware, BusinessTools, _SYSTEM_PROMPT,
)


def build_deep_agent(model: BaseChatModel, tools: BusinessTools, system_prompt: str | None = None):
    return create_deep_agent(model=model, tools=tools.langchain_tools(),
                             system_prompt=model_tool_instructions(system_prompt or _SYSTEM_PROMPT),
                             middleware=[BusinessOnlyMiddleware(tools)])
