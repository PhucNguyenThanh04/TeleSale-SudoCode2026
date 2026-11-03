"""Internal knowledge API; no endpoint is exposed as a model tool."""
import hmac
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from app.configs import get_settings
from app.knowledge.schemas import KnowledgeError
from app.knowledge.events.ingest import record_event
from app.knowledge.services.lifecycle import query, command


async def authenticate(request: Request):
    token = get_settings().ai_internal_token
    if not token or not hmac.compare_digest(request.headers.get('X-AI-Internal-Token', ''), token.get_secret_value()):
        raise HTTPException(401, 'Unauthorized internal caller')


router = APIRouter(prefix='/v1/knowledge', tags=['knowledge'], dependencies=[Depends(authenticate)])


def get_knowledge_repo(request: Request):
    repo = getattr(request.app.state, 'knowledge_repo', None)
    if repo is None:
        raise HTTPException(503, 'Knowledge service is not configured')
    return repo


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    actor_id: str = Field(min_length=1, max_length=200)
    action: str
    payload: dict


class Event(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event: dict
    idempotency_key: str = Field(min_length=1, max_length=200)


@router.get('/{resource}')
async def list_resource(resource: str, actor_id: str, offset: int = 0, limit: int = 30,
                        status: str | None = None, source: str | None = None, item_id: str | None = None,
                        repo=Depends(get_knowledge_repo)):
    try:
        return await query(repo, actor_id, resource, offset, limit, status, source, item_id)
    except KnowledgeError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post('/commands')
async def execute_command(body: Command, repo=Depends(get_knowledge_repo)):
    try:
        return await command(repo, body.actor_id, body.action, body.payload)
    except KnowledgeError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except (KeyError, TypeError):
        raise HTTPException(422, 'Invalid command payload')


@router.post('/events')
async def ingest_event(body: Event, repo=Depends(get_knowledge_repo)):
    try:
        return await record_event(repo, body.event, body.idempotency_key)
    except KnowledgeError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
