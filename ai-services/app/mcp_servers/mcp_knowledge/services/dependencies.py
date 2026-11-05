"""Bounded knowledge dependency calls with a shared absolute deadline."""
import asyncio
import time
from app.mcp_servers.mcp_knowledge.services.cloudflare import PolicyProviderError


class PolicyUnavailable(RuntimeError):
    pass


class PolicyDependencies:
    def __init__(self, config, *, clock=time.monotonic):
        self.config = config
        self.clock = clock
        self._states = {}

    async def call_dependency(self, component, operation, *, deadline):
        state = self._states.setdefault(component, {'failures':0, 'opened':None, 'probe':False, 'last_error':None})
        probe = state['opened'] is not None
        if probe:
            if state['probe'] or self.clock()-state['opened'] < self.config.breaker_cooldown_seconds:
                if state['last_error'] is not None:
                    raise state['last_error']
                raise PolicyUnavailable('Dependency circuit open')
            state['probe'] = True
        try:
            for attempt in range(1 if probe else 2):
                remaining = deadline-self.clock()
                if remaining <= 0:
                    raise TimeoutError('Knowledge deadline')
                try:
                    async with asyncio.timeout(min(remaining, self.config.dependency_timeout_seconds)):
                        result = await operation()
                except (ConnectionError, OSError, TimeoutError, PolicyProviderError) as exc:
                    state['failures'] += 1
                    state['last_error'] = exc if isinstance(exc, PolicyProviderError) else None
                    if isinstance(exc, PolicyProviderError) and not exc.retryable:
                        state['opened'] = self.clock()
                        raise
                    if state['failures'] >= self.config.breaker_failures:
                        state['opened'] = self.clock()
                    if probe or attempt or deadline-self.clock() < self.config.dependency_timeout_seconds:
                        raise
                    if isinstance(exc, PolicyProviderError) and exc.retry_after:
                        if deadline-self.clock() <= exc.retry_after:
                            raise
                        await asyncio.sleep(exc.retry_after)
                else:
                    state.update(failures=0, opened=None, last_error=None)
                    return result
        finally:
            if probe:
                state['probe'] = False
