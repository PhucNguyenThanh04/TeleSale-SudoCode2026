"""Connection-bound M1 text demo through the same harness as voice."""
import asyncio
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.auth import authenticated_socket, bind_start, current_user
from app.schemas.chat import AITextTurnResponse
from app.schemas.voice import Start
from app.schemas.timeline import TimelineQuery, TimelineResponse
from app.services.text_stream import stream_text_turn

router = APIRouter()


class TextCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event: Literal['text']
    client_msg_id: UUID
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class MemoryChange(BaseModel):
    field: str
    action: Literal['added', 'updated', 'deleted']
    value: str | int | bool | None = None
    scope_id: str = ''


class MemoryUpdate(BaseModel):
    turn_saved: bool = False
    status: Literal['pending', 'completed', 'failed', 'not_applicable', 'unavailable'] = 'unavailable'
    changes: list[MemoryChange] = Field(default_factory=list)


@router.post('/api/chat/timeline', response_model=TimelineResponse)
async def memory_timeline(query: TimelineQuery, request: Request, response: Response,
                          user=Depends(current_user)):
    try:
        start = bind_start(Start(event='start', channel=query.channel,
                                 channel_identity='account-bound', on=query.on), user)
    except ValueError:
        raise HTTPException(403, 'Channel is not available for this account') from None
    try:
        upstream = await request.app.state.ai_http.post('/v1/chat/sessions/timeline', json={
            **query.model_dump(mode='json'), 'channel_identity': start.channel_identity})
        upstream.raise_for_status()
        result = TimelineResponse.model_validate(upstream.json())
        if (result.session_id != query.session_id or result.timeline.offset != query.offset
                or result.timeline.limit != query.limit):
            raise ValueError('Timeline identity or pagination changed')
    except Exception:
        raise HTTPException(503, 'Chưa tải được lịch sử tương tác. Vui lòng thử lại.') from None
    response.headers['Cache-Control'] = 'no-store'
    return result


@router.websocket('/api/chat/stream')
async def text_chat(socket: WebSocket, user=Depends(current_user)):
    await authenticated_socket(socket, lambda: run_text_chat(socket, user))


async def run_text_chat(socket: WebSocket, user):
    await socket.accept()
    tasks = set()
    lock = asyncio.Lock()

    async def send(event, **payload):
        async with lock:
            await socket.send_json({'event': event, **payload})

    async def track_memory(payload, initial):
        update = initial
        try:
            async with asyncio.timeout(60):
                while True:
                    response = await socket.app.state.ai_http.post('/v1/chat/turns/memory', json=payload)
                    response.raise_for_status()
                    result = response.json()
                    if any(result.get(key) != payload[key] for key in ('session_id', 'client_msg_id')):
                        raise ValueError('memory_identity_changed')
                    update = MemoryUpdate.model_validate(result['memory_update']).model_dump()
                    if update['status'] != 'pending':
                        break
                    await asyncio.sleep(1)
        except TimeoutError:
            update = {**initial, 'changes': []}
        except Exception:
            update = {'turn_saved': initial.get('turn_saved', False), 'status': 'unavailable', 'changes': []}
        await send('memory_update', client_msg_id=payload['client_msg_id'],
                   memory_update=update, tracking_finished=True)

    try:
        async with asyncio.timeout(socket.app.state.voice_settings.voice_start_timeout_seconds):
            start = bind_start(Start.model_validate(await socket.receive_json()), user)
        session_id = str(uuid4())
        identity = {'session_id': session_id, 'channel': start.channel,
                    'channel_identity': start.channel_identity, 'on': start.on.isoformat()}
        try:
            response = await socket.app.state.ai_http.post('/v1/chat/sessions/prepare', json=identity)
            response.raise_for_status()
            prepared = response.json()
            if prepared.get('session_id') != session_id or not isinstance(prepared.get('call_brief'), (dict, type(None))):
                raise ValueError('prepared_session_changed')
        except Exception:
            await send('error', code='session_preparation_failed', fatal=True)
            return
        await send('ready', session_id=session_id, call_brief=prepared.get('call_brief'))
        while True:
            payload = await socket.receive_json()
            if payload == {'event': 'end'}:
                break
            try:
                command = TextCommand.model_validate(payload)
            except ValidationError:
                await send('error', code='invalid_text_command', fatal=False)
                continue
            client_msg_id = str(command.client_msg_id)
            try:
                async for event in stream_text_turn(socket.app.state.ai_http, {**identity,
                        'client_msg_id': client_msg_id, 'text': command.text,
                        'input_mode': 'clean', 'delivery_mode': 'text'}):
                    if event['event'] == 'delta':
                        await send('agent_delta', client_msg_id=client_msg_id, session_id=session_id,
                                   text=event['text'], seq=event['seq'])
                    else:
                        raw = event
                reply = AITextTurnResponse.model_validate(raw)
                if str(reply.session_id) != session_id or str(reply.client_msg_id) != client_msg_id:
                    raise ValueError('harness_identity_changed')
                update = MemoryUpdate.model_validate(raw.get('memory_update') or {}).model_dump()
            except Exception:
                await send('error', code='harness_failed', fatal=False, client_msg_id=client_msg_id)
                continue
            await send('agent_reply', **reply.model_dump(mode='json'), memory_update=update)
            if update.get('status') == 'pending':
                task = asyncio.create_task(track_memory({**identity, 'client_msg_id': client_msg_id}, update))
                tasks.add(task)
    except (ValidationError, ValueError, TimeoutError):
        await send('error', code='invalid_session_start', fatal=True)
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await socket.close()
        except RuntimeError:
            pass
