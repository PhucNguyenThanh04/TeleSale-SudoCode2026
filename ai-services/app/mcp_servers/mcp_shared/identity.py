import hashlib
import hmac
import json
import time

from app.mcp_servers.mcp_catalog.schemas import OrderQuoteInput, QuoteInput
from app.mcp_servers.mcp_order.schemas import PreviewUpdateInput, StatusInput


IDENTITY_READS = {'pricing.get_quote': QuoteInput, 'pricing.quote_order': OrderQuoteInput,
                  'order.status': StatusInput, 'order.preview_update': PreviewUpdateInput}


def select_identity(matches, customer_id=None):
    selected = [item for item in matches if customer_id is None or item['customer_id'] == customer_id]
    return selected[0] if len(selected) == 1 else None


async def resolve_identity(repo, session, channel, channel_identity, verified_customer_id=None):
    matches = await repo.identity_matches(session, channel, channel_identity)
    if matches or verified_customer_id is None:
        return select_identity(matches, verified_customer_id)
    customers = await repo.rows(session, 'customers')
    return select_identity([{'customer_id': customer['customer_id'], 'phone': customer['phone']}
        for customer in customers if customer.get('customer_id') == verified_customer_id
        and isinstance(customer.get('phone'), str)], verified_customer_id)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _request_hash(name, args):
    payload = IDENTITY_READS[name].model_validate(args).model_dump(
        mode='json', exclude_none=True, exclude={'trusted_identity'})
    if not payload.get('source_channel') or not payload.get('source_identity'):
        raise ValueError('Source identity required')
    return hashlib.sha256(_json({'tool': name, 'args': payload}).encode()).hexdigest()


def sign_identity(name, args, customer_id, secret):
    try:
        if not secret or not isinstance(customer_id, str) or not customer_id.strip():
            raise ValueError('Verified identity required')
        payload = {'purpose': 'telesale-identity-v1', 'customer_id': customer_id,
                   'request_hash': _request_hash(name, args), 'issued_at': int(time.time())}
        signature = hmac.new(secret.encode(), _json(payload).encode(), hashlib.sha256).hexdigest()
        return _json({'payload': payload, 'signature': signature})
    except (ValueError, TypeError, KeyError, AttributeError):
        raise PermissionError('Untrusted identity') from None


def verify_identity(name, args, secret):
    try:
        if not secret:
            raise ValueError('Identity authentication required')
        envelope = json.loads(args['trusted_identity'])
        payload = envelope['payload']
        signature = hmac.new(secret.encode(), _json(payload).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, envelope['signature']):
            raise ValueError('Untrusted identity signature')
        if (payload['purpose'] != 'telesale-identity-v1'
                or type(payload['issued_at']) is not int
                or not -5 <= time.time() - payload['issued_at'] <= 120
                or payload['request_hash'] != _request_hash(name, args)
                or not isinstance(payload['customer_id'], str) or not payload['customer_id'].strip()):
            raise ValueError('Untrusted identity binding')
        return payload['customer_id']
    except (ValueError, TypeError, KeyError, AttributeError):
        raise PermissionError('Untrusted identity') from None
