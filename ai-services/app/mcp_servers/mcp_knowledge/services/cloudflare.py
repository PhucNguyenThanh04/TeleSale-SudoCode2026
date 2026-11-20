import asyncio
import math
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx


class PolicyProviderError(RuntimeError):
    def __init__(self, reason, *, status=None, provider_code=None, retryable=False, retry_after=0):
        super().__init__(reason)
        self.reason, self.status, self.provider_code = reason, status, provider_code
        self.retryable, self.retry_after = retryable, retry_after


def _error(response, body):
    errors = body.get('errors', []) if isinstance(body, dict) else []
    first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
    message = str(first.get('message', '')).casefold()
    code = str(first.get('code', ''))
    code = code if re.fullmatch(r'\d{1,10}', code) else None
    status = response.status_code
    reason, retryable = 'provider_error', status >= 500
    if status in (400, 403, 429) and (code == '3036' or any(marker in message for marker in (
            'daily free allocation', 'daily quota', 'neurons limit', 'quota exceeded', 'quota exhausted'))):
        reason, retryable = 'quota_exhausted', False
    elif status in (401, 403):
        reason, retryable = 'auth', False
    elif status == 429 and any(marker in message for marker in ('rate limit', 'too many requests')):
        reason, retryable = 'rate_limited', True
    elif status == 429 and code == '3040':
        reason, retryable = 'provider_error', True
    elif status == 408:
        reason, retryable = 'network', True
    elif status in (400, 404, 413, 422):
        reason, retryable = 'config', False
    delay = 0
    if reason == 'rate_limited':
        value = response.headers.get('Retry-After', '0')
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                delay = 0
        if not math.isfinite(delay):
            delay = 0
    return PolicyProviderError(reason, status=status, provider_code=code,
                               retryable=retryable, retry_after=max(0, delay))


class CloudflareEmbeddingClient:
    def __init__(self, config, *, account_id, token, client=None, clock=time.monotonic):
        if not re.fullmatch(r'[0-9a-fA-F]{32}', account_id or '') or not token or not token.strip():
            raise ValueError('Cloudflare account ID and Workers AI token required')
        self.config, self.clock = config, clock
        self._url = f'https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{config.model_name}'
        self._token = token
        self._client = client or httpx.AsyncClient(follow_redirects=False)

    async def embed(self, texts, *, deadline):
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError('Embedding deadline')
        if not texts or len(texts) > self.config.batch_size or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError('Invalid embedding batch')
        try:
            async with asyncio.timeout(min(remaining, self.config.dependency_timeout_seconds)):
                response = await self._client.post(self._url,
                    headers={'Authorization': 'Bearer '+self._token}, json={'text': texts, 'truncate_inputs': False},
                    timeout=min(remaining, self.config.dependency_timeout_seconds))
        except httpx.TimeoutException:
            raise TimeoutError('Cloudflare timeout') from None
        except httpx.HTTPError:
            raise PolicyProviderError('network', retryable=True) from None
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            body = None
        if not response.is_success or isinstance(body, dict) and body.get('success') is False:
            raise _error(response, body)
        data = body.get('result', {}).get('data') if isinstance(body, dict) and isinstance(body.get('result'), dict) else None
        if not isinstance(data, list) or len(data) != len(texts):
            raise PolicyProviderError('invalid_response', status=response.status_code)
        for vector in data:
            if (not isinstance(vector, list) or len(vector) != self.config.dimension
                    or any(type(v) not in (float, int) or not math.isfinite(v) for v in vector)
                    or not math.isfinite(sum(v*v for v in vector)) or sum(v*v for v in vector) <= 0):
                raise PolicyProviderError('invalid_response', status=response.status_code)
        return data

    async def close(self):
        await self._client.aclose()
