# AI service audit repairs

## Intent and authority

The user requested autonomous spec → plan → execution for all fourteen findings from the AI/MCP/BTC audit. Implement in the current checkout, preserve existing uncommitted work, use no subagents or worktrees, and perform offline verification without paid model/embedding evaluations. Existing Python/LangGraph/LangMem/FastMCP/PostgreSQL architecture remains in place. No dashboards, new frameworks, unrelated refactors, code comments, or explanatory docstrings.

## Required behavior

1. PII: mask continuous and separated phone, identity, and bank account numbers, including 16–19 digit payment identifiers. Preserve legitimate prices, dates, product IDs, and ordinary numbers. Cover prompt inputs, persisted transcripts, and outputs through the shared masker.
2. Identity: a phone typed into an unlinked chat is not verified identity. Only a linked channel or backend-verified identity may load customer memory. Signed backend verification must work consistently at catalog and order MCP boundaries, including an unlinked channel; unsigned requests must retain source-identity checks.
3. Returns: current customer consent does not establish return eligibility. Use the order's creation date to select the old/new policy, and its verified receipt date to determine the return window. Respect hygiene, damage, clearance and manufacturer-defect restrictions when known. Missing eligibility evidence creates an explicitly pending review request, without scheduling pickup or promising an approved refund. Verified ineligible requests do not write. Previews label all estimates and missing conditions. Old-policy fees/refund periods remain distinct.
4. Episodes: a source quote is insufficient proof of resolving a blocker. Review resolutions against the original item and current full turn, rejecting negation, conditions, wrong scopes and unrelated quotes. No reviewer availability means no resolution is admitted. The worker must preserve source IDs and retry safety.
5. Delivery context: preserve a customer's supplied delivery address privately across turns/restarts with its source and masked surrounding statement. Never expose the raw address in prompts or public memory updates. Resolve only an unambiguous reference, and let the write-authorization reviewer judge current consent and corrections against that source. Erasure removes this context.
6. Erasure: pending requests retain their write barrier. Completed erasure must serve later contact as a fresh anonymous customer and must not reload CRM history into conversational memory. Purge runtime caches and pending playback for erased owners. Preserve the tombstone so old jobs cannot resurrect data. Do not imply that independently owned accounting/backend stores have been erased.
7. Knowledge availability: ordinary conversation and catalog/order tools must not fail solely because knowledge release lookup is unavailable. Pin a release when policy is actually requested; never serve unverified policy on failure. Release-reference lookup must not reverify every index vector per chat turn. Cache immutable validated snapshots with explicit revocation checks.
8. Summaries: rebuild the current episode summary from current topics and verified actions instead of preserving an old 800-character prefix. Latest corrections and open/resolved state must be visible in the next brief.
9. Context/resource bounds: cap the complete model context while retaining current input, active customer constraints and source references. Do not silently drop purchase constraints and then permit a write. Bound runtime caches without breaking durable retry protection. Limit operational reconstruction to pending/relevant evidence rather than rereading all completed sessions on every turn.
10. Tool memory: persist safe receipts for order changes, status, previews and policy provenance. Include callback success consistently in fact and episode paths. Keep original evidence provenance in public memory updates. Historical policy observations never grant present-day rights.
11. Latency/streaming: preserve verification before publication and honest first-answer timing. Use a total request deadline and bounded verification/repair work. A timeout after a write must retain the operation receipt. Do not claim a measured latency improvement or p95 compliance without authorized live measurement.
12. Prompts: explicitly enforce PB-06 medical handoff, PB-09 pre-order presentation, and bounded returning-customer openings. Reuse the selected compiled prompt in repair. Keep privacy, scope, consent, customer constraints and current commercial evidence checks intact. Add offline behavior/contract regressions.
13. Tool capability: expose split-order context to the model. Give distinct authorized order creations within one turn stable independent operation keys while retries remain idempotent. Support a four-product purchase within a justified tool budget and retain money/quantity/consent checks.
14. Verification: align preparation, outage, erasure and guarded-publication tests with the implemented contract. Add replay for cross-channel contact while extraction is pending. Review historical unresolved extraction candidates transparently; do not relabel historical scores as current or invent human labels. Produce an offline verification record with any real external-evidence limitation.

## Implementation decisions

These are agent decisions under the user's autonomous execution request, not preferences previously supplied by the user:

- Keep signed identity authorization as the trust boundary; never weaken unsigned channel checks.
- Missing return-condition evidence results in a review-pending intake receipt. It is not an approved return, pickup schedule, or refund.
- Keep the existing full-answer verification boundary initially. Optimize its dependencies and deadlines before attempting irreversible partial publication.
- Keep private delivery data separate from masked conversation/model context and delete it with AI memory.
- Keep external BTC data immutable. Record contradictions between the reference mock and policy rather than silently editing the external corpus.
- Local fake-model and deterministic tests establish contracts, not real-model quality or human review agreement.
- Do not commit overlapping pre-existing edits or change deployment state as part of this repair.

## Acceptance

Every numbered requirement maps to a plan task and focused offline evidence. Security, money, memory semantics and retry changes have a regression observed failing before the implementation. Run focused tests as tasks complete. Run a full offline suite at most once at the final integration gate if needed; never repeat a successful suite without a new change/failure. Record the exact tests, outcomes, deviations and remaining evidence in the execution ledger. Completion requires all implementable requirements and honest handling of requirements that need human labels or authorized live data.
