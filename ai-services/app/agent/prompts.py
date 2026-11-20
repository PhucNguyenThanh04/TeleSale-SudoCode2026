
import logging
from functools import lru_cache

from app.configs import get_settings
from app.mcp_servers.mcp_shared.decision_diagnostics import prompt_loaded

SALES_PROMPT = "telesale-sales-agent"
MEMORY_PROMPT = "telesale-langmem-extraction"


@lru_cache(maxsize=1)
def _client():
    from langfuse import Langfuse

    settings = get_settings()
    return Langfuse(public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key.get_secret_value(),
                    base_url=str(settings.langfuse_base_url).rstrip("/"))


def text_prompt(name: str, fallback: str) -> str:
    settings = get_settings()
    if not settings.langfuse_prompts_enabled:
        prompt_loaded(name, fallback, "local")
        return fallback
    try:
        prompt = _client().get_prompt(name, type="text", label="production",
                                              fallback=fallback, fetch_timeout_seconds=2,
                                              max_retries=0)
        compiled = prompt.compile()
        if isinstance(compiled, str) and compiled.strip():
            is_fallback = getattr(prompt, "is_fallback", None)
            prompt_loaded(name, compiled, "fallback" if is_fallback is True else "managed" if is_fallback is False else "unknown", getattr(prompt, "version", None))
            return compiled
    except Exception as exc:
        logging.getLogger(__name__).warning("Langfuse prompt unavailable: %s: %s",
                                            name, type(exc).__name__)
    prompt_loaded(name, fallback, "fallback")
    return fallback
