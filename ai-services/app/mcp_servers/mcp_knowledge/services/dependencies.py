"""Bounded knowledge dependency calls with a shared absolute deadline."""
import asyncio
import time


class PolicyUnavailable(RuntimeError):
    pass


class PolicyDependencies:
    def __init__(self, config, *, clock=time.monotonic):
        self.config = config
        self.clock = clock
        self._states = {}

    async def call_dependency(self, component, operation, *, deadline):
        state = self._states.setdefault(component, {'failures':0, 'opened':None, 'probe':False})
        probe = state['opened'] is not None
        if probe:
            if state['probe'] or self.clock()-state['opened'] < self.config.breaker_cooldown_seconds:
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
                except (ConnectionError, OSError, TimeoutError):
                    state['failures'] += 1
                    if state['failures'] >= self.config.breaker_failures:
                        state['opened'] = self.clock()
                    if probe or attempt or deadline-self.clock() < self.config.dependency_timeout_seconds:
                        raise
                else:
                    state.update(failures=0, opened=None)
                    return result
        finally:
            if probe:
                state['probe'] = False
