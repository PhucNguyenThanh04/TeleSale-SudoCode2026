"""ASGI entrypoint for the text AI service."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.chat import get_runtime
from app.agent.observability import configure_agent_logging
from app.api.chat import router as chat_router
from app.configs import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_agent_logging(settings.log_level)
    if not settings.ai_internal_token:
        raise RuntimeError("AI_INTERNAL_TOKEN is required for the chat endpoint")
    app.state.harness = get_runtime()
    try:
        yield
    finally:
        del app.state.harness


app = FastAPI(title=settings.app_name, version="0.1.0", debug=settings.debug, lifespan=lifespan)
app.include_router(chat_router)
