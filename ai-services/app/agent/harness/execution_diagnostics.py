"""Content-free execution evidence; never serialize exception messages or bodies."""
from contextvars import ContextVar
from functools import wraps
import re

PHASES = frozenset({'build', 'preparation', 'model_invocation', 'postprocess', 'verification'})
ERROR_TYPES = frozenset({'BadRequestError', 'AuthenticationError', 'PermissionDeniedError',
    'NotFoundError', 'UnprocessableEntityError', 'InternalServerError', 'APIStatusError',
    'APIError', 'APIConnectionError', 'APITimeoutError', 'RateLimitError', 'TimeoutError',
    'RuntimeError', 'ValueError', 'TypeError', 'KeyError', 'AttributeError', 'OSError',
    'ConnectionError', 'HTTPStatusError', 'ConnectError', 'ReadTimeout', 'GraphRecursionError',
    'unknown_error'})
ERROR_CODES = frozenset({'invalid_value', 'invalid_request_error', 'invalid_api_key',
    'model_not_found', 'unsupported_parameter', 'unsupported_value', 'rate_limit_exceeded',
    'insufficient_quota', 'context_length_exceeded', 'unknown'})
_phase = ContextVar('execution_phase', default=('preparation', None))
_attempted = ContextVar('execution_model_attempted', default=False)


def normalize_execution_event(metadata: dict) -> dict:
    phase = metadata.get('phase')
    status = metadata.get('status')
    result = {'version': 1, 'phase': phase if isinstance(phase, str) and phase in PHASES else 'preparation',
              'status': status if isinstance(status, str) and status in {'succeeded', 'failed', 'unknown', 'not_attempted'} else 'unknown'}
    if isinstance(metadata.get('invocation'), str) and metadata['invocation'] in {'initial', 'refresh'}:
        result['invocation'] = metadata['invocation']
    if status == 'failed':
        kind = metadata.get('error_type')
        result['error_type'] = kind if isinstance(kind, str) and kind in ERROR_TYPES else 'unknown_error'
        code = metadata.get('error_code')
        result['error_code'] = code if isinstance(code, str) and code in ERROR_CODES else 'unknown'
        param = metadata.get('error_param')
        result['error_param'] = param if isinstance(param, str) and re.fullmatch(
            r'(?:model|temperature|seed|max_completion_tokens|reasoning_effort|tool_choice|'
            r'tools\[\d{1,3}\]\.function\.(?:name|parameters)|messages)', param) else 'unknown'
        status_code = metadata.get('http_status')
        if type(status_code) is int and 100 <= status_code <= 599:
            result['http_status'] = status_code
    return result


def safe_execution_error(exc: Exception, *, phase: str, invocation: str | None = None) -> dict:
    body = getattr(exc, 'body', None)
    body = body if isinstance(body, dict) else {}
    if isinstance(body.get('error'), dict):
        body = body['error']
    return normalize_execution_event({'phase': phase, 'invocation': invocation, 'status': 'failed',
        'error_type': type(exc).__name__, 'http_status': getattr(exc, 'status_code', None),
        'error_code': body.get('code'), 'error_param': body.get('param')})


def set_execution_phase(phase: str, invocation: str | None = None) -> None:
    _phase.set((phase, invocation))
    if phase == 'model_invocation':
        _attempted.set(True)


def execution_result(state, status='succeeded', exc=None):
    from app.agent.harness.observability import log_event
    phase, invocation = _phase.get()
    payload = (safe_execution_error(exc, phase=phase, invocation=invocation) if exc is not None
               else normalize_execution_event({'phase': phase, 'invocation': invocation, 'status': status}))
    log_event(state, 'execution', 'phase_result', **payload)


def execution_node(phase):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(self, state):
            token = _phase.set((phase, None))
            attempt_token = _attempted.set(False)
            try:
                result = await fn(self, state)
                if phase == 'preparation' and not _attempted.get():
                    set_execution_phase('model_invocation')
                    execution_result(state, 'not_attempted')
                set_execution_phase('verification' if phase == 'verification' else 'postprocess')
                execution_result(state)
                return result
            except Exception as exc:
                execution_result(state, exc=exc)
                raise
            finally:
                _phase.reset(token)
                _attempted.reset(attempt_token)
        return wrapped
    return decorate


def execution_health(turn_records: list[dict]) -> str:
    if not turn_records:
        return 'unknown'
    unknown = False
    for record in turn_records:
        events = record.get('runtime_events', [])
        evidence = [e for e in events if e.get('step') == 'execution' and e.get('event') == 'phase_result']
        if (record.get('runtime_error') or any(e.get('status') == 'failed' for e in evidence)
                or any(e.get('event') == 'model_failed' for e in events)):
            return 'degraded'
        model = [e for e in evidence if e.get('phase') == 'model_invocation']
        completed = any(e.get('phase') == 'postprocess' and e.get('status') == 'succeeded' for e in evidence)
        if not model or not completed or any(e.get('status') not in {'succeeded', 'not_attempted'} for e in model):
            unknown = True
    return 'unknown' if unknown else 'healthy'


def pair_execution_health(values):
    values = list(values)
    return 'degraded' if 'degraded' in values else 'healthy' if values and all(v == 'healthy' for v in values) else 'unknown'


def safe_failure_details(source):
    """Share only normalized execution evidence across runner processes."""
    error = source.get('execution_error') if isinstance(source, dict) else getattr(source, 'execution_error', None)
    return {'execution_error': normalize_execution_event(error)} if isinstance(error, dict) else {}
