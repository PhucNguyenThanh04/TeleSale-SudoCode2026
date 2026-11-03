"""Staff console gateway. Browser payloads cannot set the internal actor."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from app.api.deps import CurrentUserId, get_ai_http
from app.database.pg_session import get_pg_session
from app.services.knowledge_service import feedback, internal_request

router = APIRouter(prefix='/api/knowledge', tags=['knowledge'])


def internal_actor(actor):
    if actor.startswith('web-visitor:'):
        raise HTTPException(403, 'Internal staff required')
    return actor


class Feedback(BaseModel):
    session_id: str
    turn_no: int = Field(ge=1)
    rating: bool
    reason: str = Field(min_length=1, max_length=4000)
    correction: str = Field(default='', max_length=8000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class Action(BaseModel):
    action: str
    payload: dict


@router.get('/identity')
async def identity(actor: CurrentUserId):
    return {'actor_id': internal_actor(actor)}


@router.get('/{resource}')
async def list_resource(resource: str, actor: CurrentUserId, offset: int = Query(0, ge=0),
                        limit: int = Query(30, ge=1, le=100), status: str | None = None,
                        source: str | None = None, item_id: str | None = None, ai=Depends(get_ai_http)):
    internal_actor(actor)
    if resource not in {'events', 'gaps', 'revisions', 'regression_cases', 'releases', 'jobs', 'audit', 'verification_runs', 'sources', 'backend_outbox'}:
        raise HTTPException(404, 'Unknown resource')
    params = {'actor_id': actor, 'offset': offset, 'limit': limit}
    params.update({k: v for k, v in {'status': status, 'source': source, 'item_id': item_id}.items() if v})
    return await internal_request(ai, 'GET', '/v1/knowledge/'+resource, params=params)


@router.post('/commands')
async def commands(body: Action, actor: CurrentUserId, ai=Depends(get_ai_http)):
    internal_actor(actor)
    return await internal_request(ai, 'POST', '/v1/knowledge/commands', json={
        'actor_id': actor, 'action': body.action, 'payload': body.payload})


@router.post('/feedback', status_code=202)
async def submit_feedback(body: Feedback, actor: CurrentUserId, db=Depends(get_pg_session)):
    return await feedback(db, internal_actor(actor), body.model_dump())
