"""Session continuation view; durable memory reads remain authoritative."""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date


_CONTEXT_FIELDS = ('history', 'profile', 'scoped_facts', 'episodes', 'current_episode',
                   'call_brief', 'remembered_order_ids')


@dataclass
class SessionState:
    customer_id: str | None
    on: date
    include_prior: bool
    context: dict = field(default_factory=dict)
    decision: dict = field(default_factory=dict)

    def resume(self, customer_id, request, include_prior):
        if (self.customer_id, self.on, self.include_prior) != (customer_id, request.on, include_prior):
            self.customer_id, self.on, self.include_prior = customer_id, request.on, include_prior
            self.context.clear()
            self.decision.clear()
        return deepcopy(self.context)

    def update(self, state):
        if state.get('tool_failed') or state.get('memory_blocked'):
            self.context.clear()
            self.decision.clear()
            return
        # Replace, never merge back facts removed by a fresh owner/TTL/erasure read.
        self.context = {key: deepcopy(state[key]) for key in _CONTEXT_FIELDS if key in state}
        self.decision = deepcopy(state.get('consultation') or {})
