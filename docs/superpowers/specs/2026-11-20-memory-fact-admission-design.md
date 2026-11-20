# Customer fact admission

This is repair stage 2: customer profile facts must be supported by the meaning
of their committed source before entering long-term memory. The user authorized
autonomous specification, planning and execution with general rules, independent
fixtures and no use of saved traces or public/hidden conversations for repairs.

## Requirements

1. Keep the existing owner/session/source-turn, literal quote, slot type/domain,
   PII, scope and same-turn conflict checks. When the committed date is present,
   the candidate observed_on must match it. Tool-derived facts keep their
   deterministic evidence path and do not need a semantic model approval.
2. Review mechanically admitted customer facts in one structured model request
   per distillation job. Each decision refers to an input index, with a strict
   boolean and consistent reason. Require exactly one decision per input fact;
   reject duplicate, missing, out-of-range or malformed decisions as an unavailable
   review. Only original facts may pass; the reviewer cannot invent or rewrite
   a value, scope, source, operation or date.
3. Judge each fact against the full current customer utterance. Respect negation,
   hypothetical/conditional statements, questions, third parties, quoted speech,
   uncertainty and explicit corrections. A negative fact can be valid; do not
   simply discard all negative sentences. Retractions/deletes require evidence
   about that exact slot and scope. A literal quote proves provenance, not meaning.
4. Preserve speaker roles. Earlier turns, prior facts and successful tool
   observations may resolve references and product/room identities, but only the
   current committed customer speech supplies new customer facts. Do not turn
   assistant advice or a historical selection into current consent or preference.
   Supply the existing bounded five-turn window as interpretation context to both
   extraction and review, without turning earlier turns into new sources.
5. A changed fact updates only its admitted scope. Keep the existing monotonic
   revision projection, owner fencing and erasure gate. Do not infer global facts
   from unrelated products/rooms or modify stored facts the customer did not change.
6. Review timeout, lack of structured-output support or malformed output must
   leave the job retryable under its existing five-attempt policy. Do not project
   customer proposals or mark the job completed on an unavailable review. The raw
   committed turn remains available. The review has a ten-second deadline.
7. Gate every path that can project a customer profile fact, including a blocker
   proposed through an episode and cached accepted proposals. Save reviewed
   proposals before projection and bind the cache receipt to the exact facts and
   committed source/context. An unchanged reviewed retry must not call extraction
   or semantic review again.
8. A legacy or changed cached proposal must be revalidated and reviewed. It may
   already have a partial store write under the same job revision. Persist a reset
   flag before cleanup, discard that revision's fact rows under the existing
   customer locks, then project only the frozen reviewed set. Keep the reset flag
   across retries so a crash cannot promote rejected rows when the job completes.
9. New code must not contain dialogue phrase lists, product/SKU cases or scenario
   labels. Tests use independent synthetic values, speaker/context variations,
   multiple scopes, strict-output failures, cache tampering and partial-write
   retries. No live model, benchmark, database or remote prompt operation is run.

## Approach and limits

Use the configured LangMem model as an independent batch reviewer after mechanical
admission and before projection. Meaning remains model-owned. Code enforces the
typed decisions, exact-source binding, cache integrity and publication order.
No new dependency, migration, worktree, subagent or commit is needed.

The synchronous admission helper remains a mechanical validator. The worker owns
the semantic gate; operational read reconstruction supplies tool-derived facts
only. Existing admitted store rows are not migrated or retroactively certified.
Episode narratives/resolutions, summary rendering, Call Brief and write
authorization are outside this stage, apart from blocking the episode-to-profile
fact path from bypassing review.

Offline checks prove the gate and storage behavior. They do not establish semantic
model accuracy, prompt-injection resistance or public/hidden scores. The reviewer
adds background inference and token cost; chat does not wait for that inference.
