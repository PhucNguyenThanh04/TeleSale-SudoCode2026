# RQR/CCR repair from latest smoke v2 20261112T071219Z-90613d42

User priority: preserve and correctly use prior customer context, before further
task-completion tuning. Approved to audit and repair in this checkout. No model
eval/API calls, DB mutation, BTC input changes, frozen trace/score changes,
subagents, worktrees or unrelated UI/transaction work.

Acceptance:
- [x] Account for all 31 carry-over labels with saved evidence, distinguishing
      stored/read/used/recognized and marking missing evidence explicitly.
- [x] Reproduce and repair demonstrated memory loss/inconsistency in offline
      production read/context paths, including completion of enrichment.
- [x] Correct observable-use extraction where real filter/variant/handoff usage
      is missed; do not count current customer repetition, failed tools, stale or
      cross-owner/source/scope mismatches as prior recall.
- [x] Verify changed budget/size/color and multiple products/rooms across
      sessions; preserve baseline isolation, deletions and user corrections.
- [x] Run connected focused regressions; verify source/frozen-run integrity.

Do not optimize CCR by repeating unused facts, suppressing necessary questions,
inventing missing orders, changing BTC scoring rules or claiming new model scores.
Existing smoke-runtime repairs are already present in this dirty checkout and
must be preserved. Saved stage files expose key presence, not full fact values;
do not infer durable storage correctness from them alone.

Latest user direction supersedes the earlier audit source. Authoritative audit: docs/memory-carryover-audit-v2-20261112.md (31 labels, 13 counted). V1 audit is historical only. Changes already started remain subject to verification against latest behavior; do not present v1 missing-key observations as v2 failures.

## Verified runtime memory repairs

- Completed enrichment no longer makes committed deterministic facts disappear
  merely because projection omitted them. The operational read reconstructs
  verified evidence while respecting per-key revisions, corrections and deletion
  barriers. A scoped projection is not duplicated as an unscoped fallback.
- Positive and explicitly negative child facts both survive; later customer
  corrections override earlier statements. Three-session read -> context -> brief
  -> prompt tests retain old room area and use the updated budget/child value.
- Canonical `langmem:<UUID>:<UUID>` provenance survives masking/splitting, even
  when UUIDs contain long digit sequences. Arbitrary phone-containing source
  strings still cannot bypass masking. Fact values/evidence remain masked.
- Explicitly named room areas are stored per room; multiple named rooms do not
  acquire a guessed common area. Requirements use the currently named room and
  do not let another room in session history overwrite it. Existing legacy room
  scope aliases retain revision/deletion barriers rather than reviving deleted
  evidence under a new canonical label.
- Latest T06 speech is replayed with completed prior turns: corrected gray 41
  HikePro remains distinct from black RunLite. Asking about 42 retains gray and
  does not mix product facts. Latest T13 speech is replayed with only the old
  child fact varied: the actual production shortlist changes its recommendation
  from that prior fact without a decorative spoken reminder or an order.

## Latest RQR behavior

Both reported repeats are T19 order-ID requests after its earlier create never
succeeded. No missing order is invented or purchase gate changed. The existing
known-owner empty order.status result now supplies the bounded answer directly
for a pure status request, instead of asking for unavailable ID/phone again.
The following "confirmed/handed to carrier" question is recognized as status
follow-up. Error/negative-success results and unknown identity do not use this
path, and policy tasks retain their own response path. Both exact latest-smoke
utterances pass AgentNodes offline replay with no repeated ID request.

## Measurement-only corrections

facts_used can recognize max_price_vnd/min_room_area_m2 filter usage and exact
catalog-backed variant attributes, including spoken variant names tied to a
parent-scoped fact. Typed handoff brief fields can show use; arbitrary nested
text cannot. Prior source/session checks, failed-tool exclusion, current-customer
repetition exclusion and room/product boundaries remain. No SKU suffix is parsed
without catalog metadata and an updated size is not credited as the old size.
These changes improve attribution only, not the agent's memory capacity. No
saved score is rewritten or new CCR claimed.

## Evidence and completion audit

- **318 focused tests passed in 24.66s**, covering memory read/context/projection,
  worker/admission, source masking, scope, brief continuity, deep/react smoke
  runtime replay, consultations, follow-up, facts_used and extraction/lifecycle.
  Existing dependency deprecation warning only. No full suite was run.
- Regressions were reproduced before fixes. A pre-existing test that expected
  brief disappearance after turn one was corrected to the current HEAD/user
  contract: open items remain in brief, commercial refresh is not repeated.
- Frozen v2 verified using load_pair: 62 rows/config, saved RQR **2/14** and
  CCR **13/31** unchanged. All **69** base/November-patch/effective file hashes
  match its stored release manifest. git diff --check passes.
- No model/API evaluation, DB mutation, BTC dataset change, deployment, worktree
  or subagent work occurred. Existing unrelated dirty changes were preserved.

All accepted code/audit requirements above have offline evidence. Missing causal
details in frozen traces remain unknown; a key-presence diagnostic is never
promoted into proof of correct durable memory. Further model-score validation
requires a new separately authorized user-run smoke. The operational fallback
now processes completed committed evidence too; latency under a live DB has not
been benchmarked, and no latency improvement is claimed.
