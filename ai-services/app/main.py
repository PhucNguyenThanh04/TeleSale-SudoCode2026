"""ASGI entrypoint for the text AI service."""
from app.knowledge.config import enabled, configured_url, pinned_release

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI

from app.agent.chat import get_runtime
from app.agent.harness.observability import configure_agent_logging
from app.api.chat import router as chat_router
from app.api.knowledge import router as knowledge_router
from app.configs import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_agent_logging(settings.log_level)
    if not settings.ai_internal_token:
        raise RuntimeError("AI_INTERNAL_TOKEN is required for the chat endpoint")
    app.state.harness = get_runtime()
    if configured_url("KNOWLEDGE_DATABASE_URL"):
        from app.knowledge.repo import KnowledgeRepo
        app.state.knowledge_repo = KnowledgeRepo(configured_url("KNOWLEDGE_DATABASE_URL"))
    try:
        yield
    finally:
        if app.state.harness.tracing:
            app.state.harness.tracing.shutdown()
        if getattr(app.state, "knowledge_repo", None):
            await app.state.knowledge_repo.close()
            del app.state.knowledge_repo
        del app.state.harness


app = FastAPI(title=settings.app_name, version="0.1.0", debug=settings.debug, lifespan=lifespan)
app.include_router(chat_router)

app.include_router(knowledge_router)
