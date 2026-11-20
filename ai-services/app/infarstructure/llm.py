
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.configs import Settings


def build_llm(settings: Settings) -> BaseChatModel:
    disable_thinking = settings.llm_model.startswith("gpt-6-luna") or (
        settings.llm_base_url.host == "ollama.com"
        and settings.llm_model.split(":", 1)[0] == "gemma4"
    )
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=str(settings.llm_base_url).rstrip("/"),
        timeout=settings.llm_timeout_seconds,
        use_responses_api=False,
        reasoning_effort="none" if disable_thinking else None,
        temperature=settings.llm_temperature,
        max_completion_tokens=settings.llm_max_tokens,
        seed=settings.llm_seed,
    )
