"""Bounded evidence snapshots; PII filtering follows payload field paths."""
import re
from app.agent.guardrails.checks import mask_pii
from app.knowledge.schemas import KnowledgeError


def safe_text(value):
    if not isinstance(value, str):
        raise KnowledgeError('Text required')
    if len(value) > 16000:
        raise KnowledgeError('Evidence text too long')
    return re.sub(r'(?<!\d)\d[\d .-]{8,}\d(?!\d)', '[REDACTED]', mask_pii(value))


def safe_tools(calls):
    if not isinstance(calls, list) or len(calls) > 30:
        raise KnowledgeError('Invalid tool evidence')
    result = []
    # Only these argument paths leave the originating service. Personal fields
    # at tool_calls[*].args are replaced; unrelated same-named keys are not used.
    public_args = {'sku', 'variant_sku', 'qty', 'price_vnd', 'on', 'order_date',
                   'promo_code', 'size', 'color'}
    private_args = {'customer_phone', 'customer_name', 'address', 'shipping_address', 'phone'}
    for call in calls:
        name = call.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[a-z_]+\.[a-z_]+', name):
            raise KnowledgeError('Invalid tool name')
        args = {}
        for key, val in call.get('args', {}).items():
            if key in private_args:
                args[key] = '[REDACTED]'
            elif key in public_args and isinstance(val, (str, int, float, bool, type(None))):
                args[key] = safe_text(val) if isinstance(val, str) else val
        result.append({'name': name, 'args': args})
    return result


def snapshot(event):
    allowed = {'source', 'actor_id', 'customer_id', 'session_id', 'message_id',
               'run_id', 'scenario_id', 'call', 'turn', 'signal', 'on', 'release_id', 'agent_version'}
    out = {k: str(v)[:200] for k, v in event.items() if k in allowed and v is not None}
    if 'score_sha256' in event:
        if not isinstance(event['score_sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', event['score_sha256']):
            raise KnowledgeError('Invalid score provenance hash')
        out['score_sha256'] = event['score_sha256']
    if 'rating' in event:
        if type(event['rating']) is not bool:
            raise KnowledgeError('Rating must be boolean')
        out['rating'] = event['rating']
    for key in ('question', 'answer', 'reason', 'correction', 'context'):
        out[key] = safe_text(event.get(key, ''))
    out['tool_calls'] = safe_tools(event.get('tool_calls', []))
    out['retrieved_ids'] = [safe_text(str(v))[:150] for v in event.get('retrieved_ids', [])[:30]]
    if out.get('source') not in {'operator_feedback', 'evaluation_result', 'runtime_signal', 'business_outcome'}:
        raise KnowledgeError('Unknown feedback source')
    if not out['question'] and not out['answer']:
        raise KnowledgeError('Evidence requires a question or answer')
    return out
