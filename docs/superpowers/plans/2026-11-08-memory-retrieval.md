# Memory retrieval corrections

Goal: retrieve relevant older customer episodes before limiting results; validate
memory read contracts; preserve fact evidence in model context. Work inline in
this checkout with no agents, worktrees, live inference or benchmark runs.

1. Reproduce older matching episodes lost beyond the default five, missing query
   propagation, malformed read payloads and dropped fact evidence with offline
   regression tests. Keep legacy callers and identity/scope/revision protections.
2. Add an optional bounded query to memory.read. Apply shared deterministic
   ranking to eligible episodes before truncation; refresh only the selected
   prior episodes from committed evidence. Keep current episode separate and
   existing prior-session accounting. Rank explicit product scope first, then
   relevant text, open blockers and date; an empty query preserves existing order.
3. Add typed read response models for history, facts, scopes and episode envelopes.
   Validate both MCP output and harness consumption; preserve extension fields
   used by canonical episode/consultation views and structured error responses.
   Legacy MemoryStore implementations without query support continue to work.
4. Carry masked evidence_quote, source_turn_id and source session into model facts.
   Add a small local prompt instruction about source evidence, missing retrieval
   and conflicting facts; do not change extraction semantics or publish prompts.
5. Run focused offline tests for retrieval, scopes, managed prompts, completed
   revisions, erasure/freshness and harness compatibility. Inspect the final diff.

Existing unrelated changes, including customer honorific and voice work, remain.

## Verification and decisions

- Implemented all five steps. Query ranking happens on authorized completed
  active episode versions before truncation; the harness uses the same ranking.
- Preserve accepted cross-session resolutions in the read view, including when
  the resolving session is outside the shortlist. The canonical projection is
  not mutated. This prevents retrieving an old episode from reopening a settled
  blocker/question.
- ReadResponse requires history/profile and validates the remaining envelopes;
  optional legacy fields and canonical extensions survive serialization. Legacy
  customer-only history entries remain valid without inventing assistant speech.
- Source UUIDs remain intact while evidence text is masked before model exposure.
  The existing honorific changes were preserved. No dependency/migration or
  extraction behavior changes were needed.
- Final focused verification: 159 passed, one existing LangGraph deprecation
  warning. Tests deny socket connections and use fake model/store/projector data;
  no live inference, database, managed-prompt publication or benchmark was run.
- The local configuration currently disables managed prompts. The README explains
  that deployments enabling them must publish the reviewed prompt separately.
- Final diff whitespace check passed; no unrelated dirty files were reverted.
