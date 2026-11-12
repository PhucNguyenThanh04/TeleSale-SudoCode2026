"""Review gateway with a server-bound actor and internal AI authentication."""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from typing import Literal


async def reviewer(request: Request):
    config = request.app.state.voice_settings
    if not config.knowledge_reviewer_id.strip():
        raise HTTPException(503, 'Knowledge reviewer is not configured')
    if request.method != 'GET':
        origin = request.headers.get('Origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Same-origin request required')
    return config.knowledge_reviewer_id


router = APIRouter(prefix='/api/knowledge', dependencies=[Depends(reviewer)])
RESOURCES = {'gaps', 'events', 'revisions', 'regression_cases', 'sources', 'releases', 'verification_runs'}


async def forward(request, method, path, **kwargs):
    try:
        response = await request.app.state.ai_http.request(method, path, **kwargs)
        response.raise_for_status()
        return JSONResponse(response.json(), headers={'Cache-Control': 'no-store', 'Vary': 'Authorization'})
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        messages = {401: 'Internal AI authentication failed', 403: 'Reviewer permission denied',
                    404: 'Record not found', 409: 'Record changed; refresh before retrying',
                    422: 'Invalid content, source, reviewed test or release preconditions'}
        raise HTTPException(status if status in messages else 502,
                            messages.get(status, 'Knowledge service unavailable')) from exc
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(502, 'Knowledge service unavailable') from exc


@router.get('/{resource}')
async def records(resource: str, request: Request, actor=Depends(reviewer), offset: int = 0,
                  limit: int = 30, status: str | None = None, source: str | None = None,
                  item_id: str | None = None, gap_id: str | None = None):
    if resource not in RESOURCES:
        raise HTTPException(404, 'Unknown review resource')
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, 'Invalid page')
    params = {'actor_id': actor, 'offset': offset, 'limit': limit}
    params.update({k: v for k, v in {'status': status, 'source': source, 'item_id': item_id,
                                    'gap_id': gap_id}.items() if v is not None})
    return await forward(request, 'GET', '/v1/knowledge/' + resource, params=params)


class ReviewCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['classify', 'create_revision', 'edit_revision', 'edit_test', 'approve', 'reject',
                    'prepare_release', 'activate_release', 'rollback_release']
    payload: dict


@router.post('/commands')
async def command(body: ReviewCommand, request: Request, actor=Depends(reviewer)):
    return await forward(request, 'POST', '/v1/knowledge/commands',
                         json={'actor_id': actor, **body.model_dump()})
