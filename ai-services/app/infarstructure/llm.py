"""Build the LangChain chat model used by LangGraph nodes."""

from collections.abc import Generator

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from pydantic import SecretStr

from app.configs import Settings


class _BearerTokenAuth(httpx.Auth):
    """Attach the cloud token without storing it in printable client headers."""

    def __init__(self, token: SecretStr) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._token.get_secret_value()}"
        yield request


def build_llm(settings: Settings) -> BaseChatModel:
    """Configure direct Ollama Cloud access without sending a request."""
    return ChatOllama(
        model=settings.llm_model,
        base_url=str(settings.ollama_base_url).rstrip("/"),
        client_kwargs={
            "auth": _BearerTokenAuth(settings.llm_api_key),
            "timeout": settings.ollama_timeout_seconds,
        },
        temperature=settings.llm_temperature,
        num_predict=settings.llm_max_tokens,
    )
