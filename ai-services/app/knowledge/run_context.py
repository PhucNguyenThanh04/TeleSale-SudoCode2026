"""Release selection belongs to the trusted harness, never model tool args."""
from app.knowledge.config import enabled, configured_url, pinned_release
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
    import os
    if not enabled():
        return {'release_id': BASE_ONLY, 'manifest_hash': BASE_ONLY}
    from app.mcp_servers.mcp_catalog.repos.postgres import CatalogRepo
    repo = CatalogRepo(dsn)
    try:
        result = await repo.knowledge_release(pinned_release())
        if 'error' in result:
            raise ValueError('Knowledge release is unavailable')
        return result
    finally:
        await repo.close()
