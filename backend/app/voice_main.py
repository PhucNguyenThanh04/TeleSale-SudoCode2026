"""Standalone demo entrypoint: uvicorn app.voice_main:app --app-dir backend."""

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.voice import router
from app.configs import VoiceSettings
from app.services.voice_speech import SpeechClient


def create_app(settings: VoiceSettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings or VoiceSettings()
        headers = ({"X-AI-Internal-Token": config.ai_internal_token.get_secret_value()}
                   if config.ai_internal_token else {})
        async with httpx.AsyncClient(
            base_url=config.ai_service_url, headers=headers,
            timeout=httpx.Timeout(config.ai_service_timeout_seconds),
        ) as ai_http, httpx.AsyncClient(
            base_url=config.speech_http_url,
            timeout=httpx.Timeout(config.speech_timeout_seconds,
                                  connect=config.speech_connect_timeout_seconds),
        ) as speech_http:
            app.state.voice_settings = config
            app.state.ai_http = ai_http
            app.state.voice_speech = SpeechClient(
                config.speech_listen_url, speech_http, config.speech_voice,
                config.speech_connect_timeout_seconds,
            )
            try:
                yield
            finally:
                del app.state.voice_speech
                del app.state.ai_http
                del app.state.voice_settings

    app = FastAPI(title="TeleSale Voice Demo Gateway", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    app.mount("/assets", StaticFiles(directory=frontend), name="voice-assets")

    @app.get("/", include_in_schema=False)
    async def voice_site():
        return FileResponse(frontend / "index.html")

    return app


app = create_app()
