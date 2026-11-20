import hashlib
import hmac
import json
from app.knowledge.schemas import digest
from app.mcp_servers.mcp_knowledge.schemas import TrustedPolicyContext


def sign_policy_context(request,context,secret):
    if not secret:
        raise ValueError('Context signing secret required')
    payload={'request_hash':digest(request.model_dump(mode='json')),
             'context':context.model_dump(mode='json')}
    data=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    return json.dumps({'payload':payload,'signature':hmac.new(secret.encode(),data.encode(),hashlib.sha256).hexdigest()})


def verify_policy_context(request,envelope,secret):
    try:
        value=json.loads(envelope)
        payload=value['payload']
        data=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        expected=hmac.new(secret.encode(),data.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(value['signature'],expected) or payload['request_hash']!=digest(request.model_dump(mode='json')):
            raise ValueError('Untrusted request')
        context=TrustedPolicyContext.model_validate(payload['context'])
        if context.principal!='harness' or request.on!=context.on or (request.order_date is not None and request.order_date!=context.verified_order_date):
            raise ValueError('Untrusted business context')
        return context
    except (TypeError,ValueError,KeyError,AttributeError):
        raise PermissionError('Untrusted policy context') from None
