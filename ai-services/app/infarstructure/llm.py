"""Build the LangChain chat model used by LangGraph nodes."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.configs import Settings


def build_llm(settings: Settings) -> BaseChatModel:
    """Configure OpenAI-compatible Chat Completions without sending a request."""
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=str(settings.llm_base_url).rstrip("/"),
        timeout=settings.llm_timeout_seconds,
        use_responses_api=False,
        # Luna requires non-reasoning mode for Chat Completions tool calls.
        reasoning_effort="none" if settings.llm_model.startswith("gpt-6-luna") else None,
        temperature=settings.llm_temperature,
        max_completion_tokens=settings.llm_max_tokens,
        seed=settings.llm_seed,
    )
