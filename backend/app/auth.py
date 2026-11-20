import asyncio
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocketException
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection

COOKIE = 'demo_access'
ISSUER = 'telesale-demo'
password_hash = PasswordHash.recommended()
_dummy_hash = password_hash.hash('unused-dummy-password')
router = APIRouter(prefix='/api/auth')


def same_origin(connection: HTTPConnection):
    origin = connection.headers.get('origin')
    expected = f"{connection.url.scheme.replace('ws', 'http')}://{connection.url.netloc}"
    if (origin and origin.rstrip('/') != expected) or connection.headers.get('sec-fetch-site') == 'cross-site':
        if connection.scope['type'] == 'websocket':
            raise WebSocketException(4403, 'Same-origin connection required')
        raise HTTPException(403, 'Same-origin request required')


def auth_config(connection):
    config = connection.app.state.voice_settings
    if not config.demo_jwt_secret:
        raise HTTPException(503, 'Demo authentication is not configured')
    return config


def user_store(connection):
    store = getattr(connection.app.state, 'demo_users', None)
    if store is None:
        raise HTTPException(503, 'Demo account database is not configured')
    return store


def profile(user):
    return {'id': str(user['id']), 'username': user['username'],
            'customer_id': user['customer_id'], 'name': user['name'],
            'identities': {channel: user[field] for channel, field in
                           [('hotline', 'phone'), ('chat_fanpage', 'fb_id'), ('zalo_oa', 'zalo_id')]
                           if user[field]}}


async def current_user(connection: HTTPConnection):
    def unauthorized():
        if connection.scope['type'] == 'websocket':
            return WebSocketException(4401, 'Login required')
        return HTTPException(401, 'Login required')

    if connection.scope['type'] == 'websocket':
        same_origin(connection)
    elif connection.scope['method'] not in {'GET', 'HEAD'}:
        same_origin(connection)
    token = connection.cookies.get(COOKIE)
    if not token:
        raise unauthorized()
    config = auth_config(connection)
    try:
        claims = jwt.decode(token, config.demo_jwt_secret.get_secret_value(), algorithms=['HS256'],
                            issuer=ISSUER, audience=ISSUER,
                            options={'require': ['sub', 'exp', 'iat', 'iss', 'aud']})
    except jwt.InvalidTokenError:
        raise unauthorized() from None
    user = await user_store(connection).by_id(claims['sub'])
    if not user or not user['active']:
        raise unauthorized()
    connection.state.auth_expires = claims['exp']
    connection.state.demo_user = user
    return user


def bind_start(start, user):
    field = {'hotline': 'phone', 'chat_fanpage': 'fb_id', 'zalo_oa': 'zalo_id'}.get(start.channel)
    if not field or not user[field]:
        raise ValueError('Channel is not available for assigned customer')
    return start.model_copy(update={'channel_identity': user[field]})


async def authenticated_socket(socket, run):
    seconds = socket.state.auth_expires - datetime.now(timezone.utc).timestamp()
    task = asyncio.create_task(run())
    try:
        done, _ = await asyncio.wait({task}, timeout=max(0, seconds))
        if task in done:
            await task
        else:
            await socket.close(code=4401, reason='Login expired')
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=1024)


@router.post('/login', dependencies=[Depends(same_origin)])
async def login(body: Login, request: Request, response: Response):
    config = auth_config(request)
    user = await user_store(request).by_username(body.username)
    valid = await run_in_threadpool(password_hash.verify, body.password.get_secret_value(),
                                   user['password_hash'] if user else _dummy_hash)
    if not valid or not user or not user['active']:
        raise HTTPException(401, 'Invalid username or password')
    now = datetime.now(timezone.utc)
    token = jwt.encode({'sub': str(user['id']), 'iat': now,
                        'exp': now + timedelta(minutes=config.demo_jwt_minutes),
                        'iss': ISSUER, 'aud': ISSUER},
                       config.demo_jwt_secret.get_secret_value(), algorithm='HS256')
    response.set_cookie(COOKIE, token, max_age=config.demo_jwt_minutes * 60, httponly=True,
                        secure=config.demo_cookie_secure, samesite='strict', path='/')
    response.headers['Cache-Control'] = 'no-store'
    return profile(user)


@router.get('/me')
async def me(response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    return profile(user)


@router.post('/logout', status_code=204, dependencies=[Depends(same_origin)])
async def logout(response: Response):
    response.delete_cookie(COOKIE, path='/', httponly=True, samesite='strict')
    response.headers['Cache-Control'] = 'no-store'
