"""Knowledge settings use the same .env and environment precedence as the service."""
import os
from app.configs import get_settings


def enabled():
    override = os.getenv('KNOWLEDGE_ENABLED')
    return override.lower() == 'true' if override is not None else get_settings().knowledge_enabled


def configured_url(name):
    value = os.getenv(name)
    if value:
        return value
    secret = getattr(get_settings(), name.lower(), None)
    return secret.get_secret_value() if secret else None


def pinned_release():
    return os.getenv('KNOWLEDGE_RELEASE_ID') or get_settings().knowledge_release_id
