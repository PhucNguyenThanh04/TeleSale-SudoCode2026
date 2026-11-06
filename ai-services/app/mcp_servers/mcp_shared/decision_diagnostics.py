"""Opt-in, bounded decision evidence. Never serialize arbitrary application objects."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone, date
from functools import wraps
import hashlib
import hmac
import inspect
import marshal
import math
import os
import re
import sys
from uuid import UUID, uuid4

_CURRENT = ContextVar('decision_diagnostics', default=None)
_ORIGIN = ContextVar('decision_origin', default='unknown')
_ATTEMPT = ContextVar('diagnostic_attempt', default=None)
_INITIALIZED = datetime.now(timezone.utc).isoformat()
_ALIAS_KEY = os.urandom(32)
EVENTS = frozenset({'context_loaded', 'context_masked', 'memory_read', 'memory_commit', 'memory_projection', 'memory_enqueue',
    'worker_admission', 'worker_projection', 'job_readback', 'quote_binding', 'stock_binding', 'requirements_checked', 'consultation_before', 'consultation_after',
    'gate_input', 'gate_result', 'tool_attempt', 'tool_prepared', 'tool_result',
    'continuation', 'final_verified', 'final_commit', 'provenance', 'prompt'})
TOOLS = frozenset({'catalog.search', 'pricing.get_quote', 'inventory.check', 'order.create',
    'order.update', 'order.status', 'policy.search', 'crm.get_customer', 'handoff.transfer',
    'schedule.callback'})
REASONS = frozenset({'identity_required', 'purchase_permission_required', 'selection_required',
    'purchase_already_completed', 'catalog_required', 'variant_required', 'ambiguous',
    'selection_mismatch', 'selection_unavailable', 'quantity_required', 'quantity_mismatch', 'product_requirements_not_met',
    'current_quote_required', 'price_mismatch', 'current_stock_required',
    'delivery_confirmation_required', 'offer_confirmation_required', 'budget_consent_required',
    'budget_basis_required', 'precondition_or_arguments', 'purchase_evidence_required',
    'unverified_sku', 'sku_required', 'tool_limit', 'tool_error', 'invalid_tool_result',
    'unknown_sku', 'session_owner_mismatch', 'customer_erasure_in_progress',
    'memory_store_unavailable', 'erasure_blocked', 'not_evaluated', 'unknown_reason'})
FIELDS = frozenset({'candidates', 'recommended_sku', 'selected_sku', 'budget',
    'presented_offer', 'accepted_offer', 'delegation'})
_SKU = re.compile(r'SKU-[A-Z0-9-]{1,80}\Z')
_IDENTIFIER = re.compile(r'(?:SKU-[A-Z0-9-]{1,80}|[A-Z][A-Z0-9_-]{0,39})\Z')
ENUMS = {'basis': {'unit', 'total', 'unknown'}, 'presented_basis': {'unit', 'total', 'unknown'},
    'coverage': {'unknown', 'partial', 'complete'}, 'mode': {'hard', 'approx', 'unknown'},
    'type': {'gift', 'delivery', 'freeship', 'freecod', 'fixed', 'percent', 'percent_second_item'},
    'selection_status': {'resolved', 'catalog_required', 'selection_required', 'selection_unavailable'},
    'status': {'active', 'revoked', 'unknown'}, 'source_kind': {'customer', 'agent', 'tool'},
    'next_action': {'search', 'clarify', 'quote', 'purchase', 'pause', 'confirm_terms'}}


def enabled():
    if os.getenv('EVAL_DECISION_DIAGNOSTICS') != '1':
        return False
    from app.configs import get_settings
    return get_settings().app_env != 'production'


def active():
    return _CURRENT.get() is not None


def uuid_value(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


class Capture:
    def __init__(self, max_events=256, max_bytes=262144):
        self.events = []
        self.max_events, self.max_bytes = max_events, max_bytes
        self.size = self.errors = 0
        self.truncated = False
        self.aliases = {}
        self.producer_id = str(uuid4())

    def alias(self, kind, value):
        if value is None:
            return None
        key = (kind, str(value))
        if key not in self.aliases:
            self.aliases[key] = alias_value(kind, value)
        return self.aliases[key]

    def append(self, item):
        import json
        size = len(json.dumps(item).encode())
        if len(self.events) >= self.max_events or self.size + size > self.max_bytes:
            self.truncated = True
            return
        self.events.append(item)
        self.size += size


@contextmanager
def capture_decisions(*, max_events=256, max_bytes=262144, aliases=None):
    capture = Capture(max_events, max_bytes)
    if aliases is not None:
        capture.aliases = aliases
    token = _CURRENT.set(capture)
    try:
        yield capture
    finally:
        _CURRENT.reset(token)


@contextmanager
def origin(value):
    token = _ORIGIN.set(value if value in {'model', 'continuation', 'preparation'} else 'unknown')
    try:
        yield
    finally:
        _ORIGIN.reset(token)


def _ref(value, state, capture):
    if not isinstance(value, dict):
        return {}
    request = state.get('request')
    source = uuid_value(value.get('source_turn_id'))
    history = {uuid_value(t.get('source_turn_id')) for t in state.get('history', []) if isinstance(t, dict)}
    result = {'source_turn_id': source, 'source_valid_uuid': source is not None,
        'source_in_history': source in history if source else False,
        'source_is_current': source == uuid_value(getattr(request, 'client_msg_id', None)) if source else False,
        'owner_matches': value.get('customer_id') == state.get('customer_id') if 'customer_id' in state else None,
        'same_session': str(value.get('session_id')) == str(getattr(request, 'session_id', '')) if request else None,
        'session_alias': capture.alias('session', value.get('session_id')),
        'session_ref': uuid_value(value.get('session_id'))}
    if value.get('source_kind') in ENUMS['source_kind']:
        result['source_kind'] = value['source_kind']
    if value.get('tool_name') in TOOLS:
        result['tool_name'] = value['tool_name']
    if type(value.get('observation_index')) is int and 0 <= value['observation_index'] < 20:
        result['observation_index'] = value['observation_index']
    return result


def _business(value, state, capture):
    """Called only at known typed snapshot/offer/args paths, never on raw profile."""
    if not isinstance(value, dict):
        raise TypeError('invalid_snapshot')
    result = {}
    for key, item in value.items():
        if key in {'sku', 'variant', 'recommended_sku', 'selected_sku', 'focus_sku', 'gift_sku', 'promo_code', 'required_promo_code'}:
            if item is None or isinstance(item, str) and (_IDENTIFIER if key in {'promo_code', 'required_promo_code'} else _SKU).fullmatch(item):
                result[key] = item
        elif key == 'delivery_condition':
            result['delivery_condition_present'] = bool(item)
        elif key in {'room_area_m2', 'required_room_area_m2'} and type(item) in (int, float) and math.isfinite(item) and 0 <= item <= 100000:
            result[key] = item
        elif key == 'missing_fields' and isinstance(item, list):
            result[key] = [v for v in item if v in {'selection', 'sku', 'variant', 'size', 'color', 'qty', 'quantity', 'price_vnd', 'price', 'quote', 'stock', 'consent', 'budget', 'payment_method', 'address', 'offer_confirmation'}]
        elif key == 'candidates' and isinstance(item, list):
            result[key] = [v for v in item[:16] if isinstance(v, str) and _SKU.fullmatch(v)]
        elif key in {'price_vnd', 'qty', 'limit_vnd', 'discount_vnd', 'discount_percent', 'schema_version', 'shipping_fee_vnd', 'available_qty'}:
            if item is None or type(item) is int and 0 <= item <= 10**12:
                result[key] = item
        elif key in ENUMS and isinstance(item, str) and item in ENUMS[key]:
            result[key] = item
        elif key in {'purchase_intent', 'free_shipping', 'freeship', 'cod_supported', 'child_lock_required', 'child_safe_lock'} and type(item) is bool:
            result[key] = item
        elif key == 'on' and item is not None:
            try:
                result[key] = date.fromisoformat(str(item)).isoformat()
            except ValueError:
                pass
        elif key in {'presented_offer', 'accepted_offer', 'budget', 'delegation', 'constraints'}:
            result[key] = None if item is None else _business(item, state, capture)
        elif key == 'promo_terms' and isinstance(item, list):
            result[key] = [_business(v, state, capture) for v in item[:11] if isinstance(v, dict)]
        elif key == 'source_refs' and isinstance(item, dict):
            result[key] = {k: _ref(v, state, capture) for k, v in item.items() if k in FIELDS}
        elif key == 'sources' and isinstance(item, dict):
            result[key] = {k: {side: _ref(v[side], state, capture) for side in ('agent', 'observation') if side in v}
                           for k, v in item.items() if (k in {'price_vnd', 'qty', 'variant', 'on', 'sku', 'basis', 'promo_terms'} or re.fullmatch(r'term:(?:[0-9]|10)', k)) and isinstance(v, dict)}
        elif key == 'presented_source':
            result[key] = None if item is None else _ref(item, state, capture)
    return result


def safe_snapshot(value, state=None):
    return _business(value, state or {}, _CURRENT.get() or Capture())


def emit(event, *, state=None, component='runtime', **payload):
    capture = _CURRENT.get()
    if capture is None:
        return
    try:
        if event not in EVENTS or component not in {'runtime', 'memory', 'worker', 'harness'}:
            return
        state = state or {}
        request = state.get('request')
        item = {'event': event, 'component': component, 'sequence': len(capture.events) + 1,
            'producer_id': capture.producer_id, 'origin': _ORIGIN.get(), 'customer_alias': capture.alias('customer', state.get('customer_id')),
            'session_alias': capture.alias('session', getattr(request, 'session_id', None)),
            'source_turn_id': uuid_value(getattr(request, 'client_msg_id', None)),
            'session_ref': uuid_value(getattr(request, 'session_id', None))}
        if _ATTEMPT.get() is not None:
            item['attempt_id'] = _ATTEMPT.get()
        for key in ('snapshot', 'decision', 'args'):
            if key in payload:
                item[key] = _business(payload[key], state, capture)
        if 'reason' in payload:
            item['reason'] = payload['reason'] if payload['reason'] in REASONS else 'unknown_reason'
        for key in ('attempt_id', 'parent_id'):
            if type(payload.get(key)) is int and payload[key] >= 0:
                item[key] = payload[key]
        if payload.get('tool') in TOOLS:
            item['tool'] = payload['tool']
        if payload.get('status') in {'allowed', 'blocked', 'not_evaluated', 'success', 'failed',
                'cached', 'unknown', 'enqueued', 'admitted', 'rejected', 'projected'}:
            item['status'] = payload['status']
        for key in ('revision', 'history_count', 'turn_count', 'rejected_count'):
            if type(payload.get(key)) is int and payload[key] >= 0:
                item[key] = payload[key]
        for key in ('receipt_present', 'context_present', 'context_matches', 'history_truncated', 'in_stock', 'fresh', 'quantity_sufficient'):
            if type(payload.get(key)) is bool:
                item[key] = payload[key]
        for key in ('prompt_sha256',):
            if isinstance(payload.get(key), str) and re.fullmatch('[a-f0-9]{64}', payload[key]):
                item[key] = payload[key]
        if payload.get('prompt_name') in {'telesale-sales-agent', 'telesale-langmem-extraction'}:
            item['prompt_name'] = payload['prompt_name']
        if payload.get('prompt_source') in {'local', 'managed', 'fallback', 'unknown'}:
            item['prompt_source'] = payload['prompt_source']
        if type(payload.get('prompt_version')) is int and payload['prompt_version'] >= 0:
            item['prompt_version'] = payload['prompt_version']
        if 'provenance' in payload:
            item['provenance'] = provenance()  # never trust external arbitrary metadata
        capture.append(item)
    except Exception:
        capture.errors += 1


def loaded_fingerprint(modules):
    digest = hashlib.sha256()
    for module in sorted(modules, key=lambda m: m.__name__):
        digest.update(module.__name__.encode())
        for name, value in sorted(vars(module).items()):
            candidates = [(name, value)]
            if inspect.isclass(value) and value.__module__ == module.__name__:
                candidates = [(name + '.' + n, v.__func__ if isinstance(v, (classmethod, staticmethod)) else v)
                              for n, v in sorted(vars(value).items())]
            for label, fn in candidates:
                if inspect.isfunction(fn) and fn.__module__ == module.__name__:
                    digest.update(label.encode())
                    digest.update(marshal.dumps(fn.__code__))
                    original = inspect.unwrap(fn)
                    if original is not fn:
                        digest.update(marshal.dumps(original.__code__))
    return digest.hexdigest()


def provenance():
    modules = [v for k, v in list(sys.modules.items()) if v is not None and
               (k.startswith('app.agent.') or k.startswith('app.mcp_servers.mcp_memory.') or
                k.startswith('app.mcp_servers.mcp_shared.'))]
    revision = os.getenv('BUILD_REVISION', '')
    return {'fingerprint_format': 'python-code-marshal-v1', 'python_version': sys.version.split()[0],
        'loaded_code_sha256': loaded_fingerprint(modules),
        'build_revision': revision if re.fullmatch('[a-f0-9]{7,64}', revision) else 'unknown',
        'diagnostics_initialized_at': _INITIALIZED, 'process_start': 'unknown'}


def consultation_views(context):
    if not isinstance(context, dict):
        return []
    episodes = [context.get('current_episode'), *context.get('episodes', [])]
    return [topic['consultation'] for ep in episodes if isinstance(ep, dict)
            for topic in ep.get('topics', []) if isinstance(topic, dict)
            and isinstance(topic.get('consultation'), dict)]


def memory_boundary(event):
    """Attach a safe opt-in envelope without changing the business response consumed by runtime."""
    def decorate(fn):
        signature = inspect.signature(fn)
        @wraps(fn)
        async def wrapped(*args, **kwargs):
            if not enabled():
                return await fn(*args, **kwargs)
            bound = signature.bind(*args, **kwargs).arguments
            from types import SimpleNamespace
            data = bound.get('data') if isinstance(bound.get('data'), dict) else {}
            state = {'customer_id': bound.get('customer_id'), 'request': SimpleNamespace(
                session_id=bound.get('session_id'), client_msg_id=data.get('client_msg_id'))}
            with capture_decisions() as capture:
                emit('provenance', state=state, component='memory', provenance=True)
                result = await fn(*args, **kwargs)
                state['history'] = result.get('history', [])
                for snapshot in consultation_views(result):
                    emit(event, state=state, component='memory', snapshot=snapshot,
                         status='success', history_count=len(state['history']),
                         turn_count=result.get('turn_count'),
                         history_truncated=result.get('turn_count', 0) > len(state['history']))
                emit(event, state=state, component='memory',
                     status='failed' if 'error' in result else 'success',
                     reason=result.get('error', 'not_evaluated'))
            return {**result, '_decision_diagnostics': {
                'events': capture.events, 'truncated': capture.truncated, 'errors': capture.errors}}
        return wrapped
    return decorate


def gate_boundary(fn):
    @wraps(fn)
    def wrapped(state, args):
        result = fn(state, args)
        emit('gate_result', state=state, args=args,
             status='allowed' if result is None else 'blocked',
             reason=result or 'not_evaluated')
        return result
    return wrapped


def _wire_safe(value, key=''):
    """Validate producer output again at the trust boundary; reject unknown paths."""
    if isinstance(value, dict):
        containers = {'snapshot', 'decision', 'args', 'budget', 'delegation', 'constraints',
            'presented_offer', 'accepted_offer', 'source_refs', 'sources', 'agent', 'observation',
            'presented_source', 'provenance'} | FIELDS | {'price_vnd', 'qty', 'variant', 'on', 'sku', 'basis', 'promo_terms'}
        if key and key not in containers and not re.fullmatch(r'term:(?:[0-9]|10)', key):
            return False
        return all(_wire_safe(v, k) for k, v in value.items())
    if isinstance(value, list):
        if key == 'missing_fields':
            return len(value) <= 16 and all(v in {'selection', 'sku', 'variant', 'size', 'color', 'qty', 'quantity', 'price_vnd', 'price', 'quote', 'stock', 'consent', 'budget', 'payment_method', 'address', 'offer_confirmation'} for v in value)
        return key in {'promo_terms', 'candidates'} and len(value) <= 16 and all(_wire_safe(v, 'sku' if key == 'candidates' else 'presented_offer') for v in value)
    if value is None:
        return key in {'source_turn_id', 'customer_alias', 'session_alias', 'owner_matches', 'same_session',
            'presented_offer', 'accepted_offer', 'presented_source', 'sku', 'variant', 'selected_sku',
            'recommended_sku', 'focus_sku', 'price_vnd', 'qty', 'limit_vnd', 'on', 'session_ref'}
    if type(value) is bool:
        return key in {'source_valid_uuid', 'source_in_history', 'source_is_current', 'owner_matches',
            'same_session', 'purchase_intent', 'free_shipping', 'freeship', 'cod_supported', 'receipt_present',
            'context_present', 'context_matches', 'history_truncated', 'in_stock', 'fresh', 'quantity_sufficient',
            'child_lock_required', 'child_safe_lock', 'delivery_condition_present'}
    if key in {'room_area_m2', 'required_room_area_m2'} and type(value) in (int, float):
        return math.isfinite(value) and 0 <= value <= 100000
    if type(value) is int:
        return key in {'sequence', 'revision', 'history_count', 'turn_count', 'rejected_count',
            'attempt_id', 'parent_id', 'observation_index', 'price_vnd', 'qty', 'limit_vnd',
            'discount_vnd', 'discount_percent', 'schema_version', 'shipping_fee_vnd', 'prompt_version', 'available_qty'} and 0 <= value <= 10**12
    if not isinstance(value, str):
        return False
    choices = {'event': EVENTS, 'component': {'runtime', 'memory', 'worker', 'harness'},
        'origin': {'model', 'continuation', 'preparation', 'unknown'}, 'reason': REASONS,
        'tool': TOOLS, 'tool_name': TOOLS,
        'status': {'active', 'revoked', 'unknown', 'allowed', 'blocked', 'not_evaluated',
            'success', 'failed', 'cached', 'enqueued', 'admitted', 'rejected', 'projected'},
        **{k: v for k, v in ENUMS.items() if k != 'status'}}
    if key in choices:
        return value in choices[key]
    if key in {'customer_alias', 'session_alias'}:
        return bool(re.fullmatch(r'(?:customer|session)_[a-f0-9]{12}', value))
    if key in {'source_turn_id', 'session_ref', 'producer_id'}:
        return uuid_value(value) == value
    if key == 'prompt_name':
        return value in {'telesale-sales-agent', 'telesale-langmem-extraction'}
    if key == 'prompt_source':
        return value in {'local', 'managed', 'fallback', 'unknown'}
    if key in {'loaded_code_sha256', 'prompt_sha256'}:
        return bool(re.fullmatch('[a-f0-9]{64}', value))
    if key == 'build_revision':
        return value == 'unknown' or bool(re.fullmatch('[a-f0-9]{7,64}', value))
    if key == 'fingerprint_format':
        return value == 'python-code-marshal-v1'
    if key == 'python_version':
        return bool(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value))
    if key in {'diagnostics_initialized_at', 'process_start', 'on'}:
        if value == 'unknown': return True
        try:
            datetime.fromisoformat(value)
            return True
        except ValueError:
            return False
    if key in {'sku', 'variant', 'recommended_sku', 'selected_sku', 'focus_sku', 'gift_sku', 'promo_code', 'required_promo_code'}:
        return bool((_IDENTIFIER if key in {'promo_code', 'required_promo_code'} else _SKU).fullmatch(value))
    return False


_NO_OWNER = object()


def _ingest(envelope, customer_id=_NO_OWNER):
    capture = _CURRENT.get()
    if capture is None or not isinstance(envelope, dict):
        return
    capture.truncated |= envelope.get('truncated') is True
    if type(envelope.get('errors')) is int:
        capture.errors += max(0, envelope['errors'])
    for event in envelope.get('events', [])[:256]:
        if valid_event(event):
            if customer_id is not _NO_OWNER:
                event = {**event, 'customer_alias': capture.alias('customer', customer_id)}
            capture.append(event)
        else:
            capture.errors += 1


def tool_boundary(fn):
    @wraps(fn)
    async def wrapped(self, name, proposed):
        capture = _CURRENT.get()
        if capture is None:
            return await fn(self, name, proposed)
        attempt = len(capture.events) + 1
        parent = _ATTEMPT.get()
        token = _ATTEMPT.set(attempt)
        before = len(self.state.get('tool_calls', []))
        emit('tool_attempt', state=self.state, tool=name, args=proposed,
             attempt_id=attempt, parent_id=parent, context_present=bool(proposed.get('address')))
        try:
            result = await fn(self, name, proposed)
            executed = len(self.state.get('tool_calls', [])) > before and any(
                c.get('name') == name for c in self.state.get('tool_calls', [])[before:])
            emit('tool_result', state=self.state, tool=name, attempt_id=attempt,
                 status='failed' if result.get('error') and executed else 'blocked' if result.get('error') else 'success' if executed else 'cached',
                 reason=result.get('error', 'not_evaluated'),
                 receipt_present=bool(result.get('order_id') or result.get('ticket_id')),
                 args={k: v for k, v in result.items() if k in {'sku', 'price_vnd', 'qty', 'on'}},
                 in_stock=result.get('in_stock'))
            return result
        finally:
            _ATTEMPT.reset(token)
    return wrapped


def phase_origin(value):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(*args, **kwargs):
            with origin(value):
                return await fn(*args, **kwargs)
        return wrapped
    return decorate


def context_checkpoint(event, state, context):
    if not active():
        return
    combined = {**state, 'history': context.get('history', [])}
    for snapshot in consultation_views(context):
        emit(event, state=combined, snapshot=snapshot, history_count=len(combined['history']))
    emit(event, state=combined, history_count=len(combined['history']))


def worker_boundary(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        if not enabled():
            return await fn(*args, **kwargs)
        with capture_decisions():
            return await fn(*args, **kwargs)
    return wrapped


def worker_envelope():
    capture = _CURRENT.get()
    if capture is None:
        return None
    return {'events': list(capture.events), 'truncated': capture.truncated, 'errors': capture.errors}


def prompt_loaded(name, text, source, version=None):
    if active():
        emit('prompt', prompt_name=name, prompt_source=source, prompt_version=version,
             prompt_sha256=hashlib.sha256(text.encode()).hexdigest())


async def save_worker_envelope(repo, conn, job_id, stored):
    """A failed diagnostics-only write must not abort the business transaction."""
    capture = _CURRENT.get()
    if capture is None:
        return
    value = {**stored, '_decision_diagnostics': worker_envelope()}
    try:
        if hasattr(conn, 'transaction'):
            async with conn.transaction():  # asyncpg savepoint inside the job transaction
                await repo.save_distillation_proposals(conn, job_id, value)
        else:
            await repo.save_distillation_proposals(conn, job_id, value)
    except Exception:
        capture.errors += 1


def ingest(envelope, customer_id=_NO_OWNER):
    try:
        _ingest(envelope, customer_id)
    except Exception:
        if active():
            _CURRENT.get().errors += 1


@contextmanager
def resume_capture(capture):
    token = _CURRENT.set(capture)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def observe_job(capture, job, state):
    if capture is None:
        return
    try:
        with resume_capture(capture):
            ingest(job.get('envelope'), customer_id=state.get('customer_id'))
            emit('job_readback', state=state, component='harness',
                 status='success' if job.get('status') == 'completed' else 'unknown',
                 revision=job.get('revision'))
    except Exception:
        capture.errors += 1


def normalize_aliases(value, aliases):
    if isinstance(value, list):
        return [normalize_aliases(v, aliases) for v in value]
    if not isinstance(value, dict):
        return value
    result = {k: normalize_aliases(v, aliases) for k, v in value.items() if k != 'session_ref'}
    session_ref = value.get('session_ref')
    if session_ref:
        key = ('session', session_ref)
        if key not in aliases:
            aliases[key] = alias_value('session', session_ref)
        result['session_alias'] = aliases[key]
    return result


def alias_value(kind, value):
    configured = os.getenv('_EVAL_DECISION_ALIAS_KEY', '')
    secret = bytes.fromhex(configured) if re.fullmatch('[a-f0-9]{64}', configured) else _ALIAS_KEY
    digest = hmac.new(secret, f'{kind}:{value}'.encode(), hashlib.sha256).hexdigest()[:12]
    return f'{kind}_{digest}'


def valid_event(event):
    required = {'event', 'component', 'sequence', 'producer_id', 'origin',
                'customer_alias', 'session_alias', 'source_turn_id'}
    return isinstance(event, dict) and required <= event.keys() and _wire_safe(event)
