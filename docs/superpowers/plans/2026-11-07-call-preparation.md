# Call preparation implementation plan

**Goal:** Start identity/context/Call Brief preparation at voice connection time, before the first transcript, without synthetic conversation turns.

**Architecture:** An authenticated `/v1/chat/sessions/prepare` endpoint resolves session identity and runs the existing context/brief builder without invoking the agent or persisting a turn. The voice gateway starts it concurrently with STT, waits only if the first transcript arrives sooner, and keeps the returned session ID. The runtime reuses prepared commercial reads briefly in the same session/date/customer; it rebuilds context and the brief for the actual utterance.

**Constraints:** Work in this checkout without subagents. Preserve unrelated changes. No live inference, benchmarks, DB writes or deployment. Retain per-turn memory reads: they enforce erasure barriers and ownership and supply newly committed history and LangMem changes. Do not cache a full profile across that check. Preserve brief orders, open blockers/questions, must_not_ask, outcome-aware opening, stale warnings and PII filtering through the existing builder. Preparation must not create consent, a committed turn, or a distillation job.

## Tasks

- [x] Add offline runtime tests for preparation without inference/persistence, first-turn brief, freshness reuse, date/identity boundaries, current memory failure and history updates. Implement preparation and authenticated schemas/API. Prepared observations expire after 30 seconds and are consumed once; cancelled/failed preparation publishes no prepared result.
- [x] Add gateway tests proving preparation starts before transcription, does not delay STT readiness, is awaited by the first turn, shares the exact session, propagates safe failure, and is cancelled on disconnect. Implement concurrent preparation and update existing offline transport doubles.
- [x] Run focused AI identity/context/brief/API tests and voice transport/flow tests. Review the diff for identity, stale evidence and cancellation boundaries. Update service/voice docs with the actual behavior and limitations.

**Verification:** AI service unittest modules for preparation, API, deep memory, freshness, scoped context, brief contracts and identity contracts; backend pytest voice flow, transport, WebSocket and contract modules. Use each service's virtualenv and import root. No full suite unless required by repository instructions.

**Decision:** Re-read memory each turn rather than reusing an unchecked profile. This intentionally leaves one MCP read in the critical path, while moving CRM lookup and returning-customer freshness reads ahead of speech. A distributed context revision/invalidation protocol is outside this change.

**Verification record:** 59/60 existing focused AI tests passed. `contract_memory_identity.MemoryIdentityContract.test_fanpage_to_hotline_loads_same_customer_fact` also fails with the unmodified `HEAD` runtime (`profile.room_area_m2: missing`), confirmed by loading that source in memory without changing the checkout. Five offline browser tests passed. New preparation/API tests and 29 voice flow/transport/contract tests passed. No live latency improvement has been measured.
