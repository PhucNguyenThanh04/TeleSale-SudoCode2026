# Per-turn memory display

**Goal:** Show committed conversation status immediately and actual accepted LangMem fact changes after each turn in the existing call demo, without waiting for extraction before answering.

**Architecture:** Add a typed `memory_update` to the chat response and an internal authenticated status endpoint keyed by session and message UUID. A new read-only memory MCP tool reads the committed turn and its existing distillation job under the ownership/erasure boundary. Only completed `accepted_writes` become public changes; proposals, raw evidence, identifiers and arbitrary fields do not. No DB migration or inference is required. Gateway tasks poll per message independently of TTS, then send a `memory_update` WebSocket event bound to the original voice turn. The UI renders the state underneath that reply with DOM text nodes.

**Scope and constraints:** Current checkout only; no subagents. Preserve existing changes. No live model or DB operations. No dashboard, unrelated UI redesign, previous-value inference or changes to distillation. Unknown customers have saved conversation but no eligible long-term fact job. Distinguish pending/completed/failed/not_applicable/unavailable; a completed empty change list means no new profile facts, not necessarily no episode update. Polling ends after 60 seconds or call disconnect; a timeout remains pending and never becomes a fake completed result. Public browser clients can only receive updates for turns owned by their current WebSocket. Internal status requires the backend token and same channel binding. No API key or raw memory evidence goes to the browser.

## Tasks

- [x] Test and implement a read-only per-turn job query/service/MCP tool, with completed-only changes, scalar slot whitelist, PII masking, ownership/erasure checks and anonymous behavior.
- [x] Test and implement typed chat metadata/status API and memory adapter. Initial chat response does not query or await the worker. Lookup re-resolves/binds identity using the existing runtime identity boundary. Missing/error status is unavailable, not success.
- [x] Test and implement gateway background polling, cancellation and turn binding; render per-reply Vietnamese memory updates with safe DOM APIs. Existing clients without metadata remain compatible.
- [x] Run focused offline service/API/voice/browser tests, inspect diff and document response/polling semantics and privacy limits.

**Verification:** Fake memory repository and offline HTTP transports; real headless Chrome with synthetic speech. No successful checks repeated absent changes or specific review concerns. No full suite unless required by repository instructions.
