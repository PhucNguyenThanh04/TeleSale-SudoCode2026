# Memory Identity Boundary Implementation Plan

**Goal:** Keep ambiguous and unverified conversation content out of a verified customer's cross-session memory while preserving same-session use before verification and cross-channel continuity for a resolved customer.

**Architecture:** Keep CRM as the identity resolver and PostgreSQL `ai_memory` as the durable store. Filter session turns by their recorded owner when producing customer-scoped episodes; keep anonymous turns available only while the session remains unverified. Use `customer_id`, never the phone or channel identifier, to retrieve prior facts and episodes.

**Tech Stack:** Python 3.12, LangGraph, MCP memory, PostgreSQL, unittest.

**Spec:** Conversation agreement on the first memory step, BTC `DIEU-CHINH-DE.md` and `GIAI-DAP-MENTOR.md`, repository `docs/memory-policy.md`.

## Global Constraints

- Preserve the user's existing uncommitted memory changes.
- Do not branch on scenario names, fixture customer IDs, product IDs or exact dialogue.
- Keep customer fact validation and business-date tool rules intact.
- Verify on mock and report separately whether PostgreSQL, MCP HTTP and public sample were run.

## Review Focus

- An ambiguous number must not expose either candidate's profile or episodes.
- Anonymous turns before later verification must not enter the verified customer's episode.
- A known customer must still load prior episodes across trusted channels.
- A conflicting verified identity for a bound session must fail.
- A restart must not turn a previously anonymous session into a different customer's history.

## Tasks

### Task 1: Characterize identity and episode boundaries

**Files:** `ai-services/test/test_mcp_memory.py`, `ai-services/test/test_deep_memory.py`.

- [x] Add an anonymous-then-verified test that asserts the prior anonymous utterance is absent from the customer's episode and the verified utterance is present.
- [x] Add a different-customer and cross-channel control using different identifiers and paraphrased utterances.
- [x] Run the focused tests and confirm the unsafe case fails for the expected reason.

### Task 2: Enforce the boundary in memory storage

**Files:** `ai-services/app/mcp_servers/mcp_memory/repos/postgres.py`, `ai-services/app/mcp_servers/mcp_memory/services/memory.py`.

- [x] Add a repository read restricted to turns attributed to the verified customer.
- [x] Build episode summaries from those turns, without reassigning anonymous turns.
- [x] Run focused tests and confirm the new and existing memory tests pass.

### Task 3: Clean up legacy mixed memory

**Files:** `ai-services/migrations/0006_episode_identity_boundary.sql`,
`ai-services/test/test_memory_identity_migration.py`.

- [x] Restore anonymous ownership for turns formerly bound by successful `claim_pending`.
- [x] Retract facts sourced from those turns and rebuild affected episodes.
- [x] Test against temporary PostgreSQL tables with successful and failed claims.

### Task 4: Restore test execution and verify the slice

**Files:** `ai-services/test/test_memory_recovery.py`, memory docs if behavior changes.

- [x] Replace stale CLI tests with current one-turn entrypoint coverage; preserve read failure and restart checks.
- [x] Run AI and backend suites, BTC mock checks where applicable, and `git diff --check`.
- [x] Record public-sample and PostgreSQL/MCP coverage limits accurately.
