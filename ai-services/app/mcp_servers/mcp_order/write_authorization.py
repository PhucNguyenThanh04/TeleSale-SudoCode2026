import hashlib
import hmac
import json
import time
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.mcp_servers.mcp_order.schemas import CallbackInput, CreateInput, HandoffInput, UpdateInput


WRITE_MODELS = {'order.create': CreateInput, 'order.update': UpdateInput,
                'schedule.callback': CallbackInput, 'handoff.transfer': HandoffInput}
WRITE_TOOLS = frozenset(WRITE_MODELS)
AUTHORIZATION_TTL_SECONDS = 120
_ROUTING = {'source_channel', 'source_identity', 'operation_key', 'trusted_authorization'}


class AuthorizedWriteContext(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    session_id: UUID
    request_id: UUID
    customer_id: str | None
    source_channel: str = Field(min_length=1)
    source_identity: str = Field(min_length=1)
    on: date
    tool: Literal['order.create', 'order.update', 'schedule.callback', 'handoff.transfer']
    args_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    customer_text_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    review_context_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)


def write_digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def normalized_write(name, args):
    return WRITE_MODELS[name].model_validate(args).model_dump(
        mode='json', exclude_none=True, exclude={'trusted_authorization'})


def write_args_digest(name, args):
    return write_digest({key: value for key, value in normalized_write(name, args).items()
                         if key not in _ROUTING})


def write_operation_key(context, args):
    key = f'{context.session_id}:{context.request_id}:{context.tool}'
    return key + ':' + args['order_id'] if context.tool == 'order.update' else key


def _validate_binding(name, args, context):
    if (context.tool != name or context.args_hash != write_args_digest(name, args)
            or args.get('source_channel') != context.source_channel
            or args.get('source_identity') != context.source_identity
            or args.get('operation_key') != write_operation_key(context, args)
            or 'on' in args and str(args['on']) != context.on.isoformat()):
        raise PermissionError('Untrusted write context')


def sign_write_authorization(name, args, context, secret):
    try:
        if not secret or not isinstance(context, AuthorizedWriteContext):
            raise ValueError('Write authorization required')
        request = normalized_write(name, args)
        _validate_binding(name, request, context)
        payload = {'purpose': 'telesale-write-v1', 'request_hash': write_digest(request),
                   'context': context.model_dump(mode='json'), 'issued_at': int(time.time())}
        signature = hmac.new(secret.encode(), _json(payload).encode(), hashlib.sha256).hexdigest()
        return _json({'payload': payload, 'signature': signature})
    except (ValueError, TypeError, KeyError, AttributeError):
        raise PermissionError('Untrusted write context') from None


def verify_write_authorization(name, args, secret):
    try:
        if not secret:
            raise ValueError('Write authorization required')
        envelope = json.loads(args['trusted_authorization'])
        payload = envelope['payload']
        expected = hmac.new(secret.encode(), _json(payload).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(envelope['signature'], expected):
            raise ValueError('Untrusted signature')
        issued_at = payload['issued_at']
        age = time.time() - issued_at
        if (payload['purpose'] != 'telesale-write-v1' or type(issued_at) is not int
                or not -5 <= age <= AUTHORIZATION_TTL_SECONDS):
            raise ValueError('Expired write authorization')
        request = normalized_write(name, args)
        if payload['request_hash'] != write_digest(request):
            raise ValueError('Untrusted payload')
        context = AuthorizedWriteContext.model_validate(payload['context'])
        _validate_binding(name, request, context)
        return context
    except (ValueError, TypeError, KeyError, AttributeError):
        raise PermissionError('Untrusted write context') from None
