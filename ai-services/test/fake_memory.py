"""Process-local fake used by agent tests."""

from collections import defaultdict
from typing import Any

from app.agent.guardrails import mask_pii


class InMemoryStore:
    include_prior = True

    def __init__(self) -> None:
        self.sessions: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.session_owners: dict[str, str | None] = {}
        self.profiles: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.fact_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.order_ids: dict[str, set[str]] = defaultdict(set)

    def known_order_ids(self, customer_id: str | None) -> set[str]:
        return set(self.order_ids[customer_id]) if customer_id else set()

    def _record_order(self, customer_id: str, order_id: str) -> None:
        self.order_ids[customer_id].add(order_id)

    def session_history(self, session_id: str, customer_id: str | None) -> list[dict[str, str]]:
        if session_id in self.session_owners and self.session_owners[session_id] != customer_id:
            return []
        return list(self.sessions[session_id])

    def profile(self, customer_id: str | None) -> dict[str, dict[str, Any]]:
        return dict(self.profiles[customer_id]) if customer_id else {}

    def _record_turn(
        self, session_id: str, customer_id: str | None, customer_text: str, agent_text: str
    ) -> int:
        if session_id in self.session_owners and self.session_owners[session_id] != customer_id:
            return 0
        self.session_owners[session_id] = customer_id
        self.sessions[session_id].append({"customer": mask_pii(customer_text), "agent": mask_pii(agent_text)})
        return len(self.sessions[session_id])

    def _write_fact(
        self, customer_id: str, key: str, value: Any, op: str, source: str
    ) -> dict[str, Any] | None:
        if not key or not isinstance(value, (str, int, float, bool)):
            return None
        safe_value = mask_pii(value) if isinstance(value, str) else value
        if op not in {"set", "supersede", "delete"}:
            return None
        previous = self.profiles[customer_id].get(key)
        if previous is not None:
            previous["status"] = "superseded" if op != "delete" else "deleted"
        if op == "delete":
            self.profiles[customer_id].pop(key, None)
        elif op in {"set", "supersede"}:
            record = {"key": key, "value": safe_value, "source": source, "status": "active"}
            self.profiles[customer_id][key] = record
            self.fact_history[customer_id].append(record)
        return {"customer_id": customer_id, "key": key, "value": safe_value, "op": op, "source": source}

    def seed_fact(self, customer_id: str, key: str, value: Any, op: str, source: str) -> None:
        self._write_fact(customer_id, key, value, op, source)

    async def read_context(self, session_id: str, customer_id: str | None) -> dict:
        return {"history": self.session_history(session_id, customer_id),
                "profile": self.profile(customer_id), "episodes": [],
                "owned_order_ids": list(self.known_order_ids(customer_id))}

    async def record_turn(self, session_id: str, customer_id: str | None,
                          customer_text: str, agent_text: str, on: str, channel: str,
                          outcome: str = "khac", client_msg_id: str | None = None) -> dict:
        return {"turn_no": self._record_turn(session_id, customer_id, customer_text, agent_text)}

    async def write_fact(self, customer_id: str, session_id: str, key: str, value: Any,
                         op: str, source: str, client_msg_id: str | None = None) -> dict | None:
        return self._write_fact(customer_id, key, value, op, source)

    async def record_order(self, customer_id: str, session_id: str, order_id: str,
                           client_msg_id: str | None = None) -> dict:
        self._record_order(customer_id, order_id)
        return {"order_id": order_id}
