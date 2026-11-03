"""Reviewer permissions are provisioned by an administrator, never by the UI."""
from app.knowledge.schemas import Forbidden


async def require_permission(tx, actor_id, permission='knowledge_review'):
    if not actor_id or actor_id.startswith('web-visitor:'):
        raise Forbidden('Internal reviewer required')
    row = await tx.get('permissions', actor_id)
    if not row or permission not in row.get('permissions', []):
        raise Forbidden('Reviewer permission required')
