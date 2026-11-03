"""Release selection belongs to the trusted harness, never model tool args."""
from app.knowledge.config import enabled, pinned_release
from contextlib import contextmanager
from contextvars import ContextVar

_RELEASE = ContextVar('knowledge_release', default=None)
BASE_ONLY = 'btc-only'


def selected_release():
    return _RELEASE.get()


@contextmanager
def release_context(release_id):
    token = _RELEASE.set(release_id)
    try:
        yield
    finally:
        _RELEASE.reset(token)


async def capture_release(dsn):
    """Resolve one release before a paired run; caller holds this ID for both modes."""
    from app.configs import get_settings
    if not enabled() and not get_settings().mcp_knowledge_url:
        return {'release_id': BASE_ONLY, 'manifest_hash': BASE_ONLY}
    from app.mcp_servers.mcp_knowledge.repos.postgres import PolicyRepository
    repo = PolicyRepository(dsn)
    try:
        result = await repo.release_ref(pinned_release())
        if 'error' in result:
            raise ValueError('Knowledge release is unavailable')
        return result
    finally:
        await repo.close()
