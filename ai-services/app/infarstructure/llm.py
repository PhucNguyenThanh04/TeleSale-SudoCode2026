"""Build the LangChain chat model used by LangGraph nodes."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.configs import Settings
from app.infarstructure.local_llm import LocalChatOpenAI


def build_llm(settings: Settings) -> BaseChatModel:
    """Configure OpenAI-compatible Chat Completions without sending a request."""
    disable_thinking = settings.llm_model.startswith("gpt-6-luna") or (
        settings.llm_base_url.host == "ollama.com"
        and settings.llm_model.split(":", 1)[0] == "gemma4"
    )
    model_class = LocalChatOpenAI if settings.llm_backend == "local" else ChatOpenAI
    options = ({"context_window": settings.local_llm_context_window}
               if settings.llm_backend == "local" else {})
    return model_class(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=str(settings.llm_base_url).rstrip("/"),
        timeout=(settings.local_llm_timeout_seconds if settings.llm_backend == "local"
                 else settings.llm_timeout_seconds),
        use_responses_api=False,
        # Ollama maps "none" to disabled thinking for supported boolean models.
        reasoning_effort="none" if disable_thinking else None,
        temperature=settings.llm_temperature,
        max_completion_tokens=settings.llm_max_tokens,
        seed=settings.llm_seed,
        **options,
    )
