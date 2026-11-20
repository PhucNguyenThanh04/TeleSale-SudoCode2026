# MCP write authorization

Repair stage 3 binds a business write to the current customer's request from
agent review through MCP execution. The user delegated specification, planning
and implementation under the earlier rules: general behavior, independent
offline tests, no trace/scenario-driven repairs, no live evaluations or writes.

## Evidence and design choices

The current agent already invokes a semantic reviewer before writes. Its output
is a boolean at the controller boundary. MCP currently accepts naked write calls
after identity/schema checks, without proof of this review. The controller also
reuses any matching write result from state, including failed or unbound results.
The callback service can silently move the approved time before inserting it.

Keep the existing reviewer and business validations. Add a short-lived signed
authorization envelope using the existing MCP signing/token secret, following
the repository's policy-context approach. The controller supplies a typed context
only after approval; the gateway binds/signs the actual normalized wire payload.
The order service verifies it before opening a transaction or claiming an
operation. A direct gateway or MCP call without that context fails closed.
An independent signing secret remains supported through the gateway/server's
existing context-secret pattern; no new environment setting is needed.

This is a deliberate choice over prompt-only changes, which cannot close the
MCP bypass, or a second model in MCP, which would duplicate inference and still
need trustworthy customer source provenance. The signature proves passage through
the trusted agent boundary, not the semantic correctness of the model decision.
Processes holding the signing secret are trusted; compromised credentials and
malicious application code are outside this boundary.

## Requirements

1. Cover `order.create`, `order.update`, `schedule.callback` and `handoff.transfer`.
   Read tools remain usable without a write grant. Identity, order ownership,
   catalog variant, current stock/quote, schema, date and budget checks remain.
2. Review the whole current utterance with separate historical customer/agent
   roles. History, memory, plans and tool observations may resolve references,
   but never create current consent. Preserve conditions, corrections, third
   parties, uncertainty, exact target/terms and legitimate short confirmations.
   No dialogue phrase lists, scenario labels or product-specific authorization.
   Preserve equality of a proposed private address to its current source using
   an opaque marker; do not remove the argument or collapse different addresses
   into indistinguishable review inputs. Continue masking raw private values.
3. Require strict structured output with no extra fields and consistent
   allowed/basis/reason. An approved customer request cites a literal current
   customer quote. Policy-required handoff is restricted to the handoff tool and
   the existing medical/out-of-document reason categories. Malformed output,
   unavailable providers and the existing five-second deadline cannot authorize
   a write; report review unavailability separately from a semantic denial.
4. Bind an approved context to session ID, request ID, current text hash,
   verified customer ID, source channel/identity, business date, tool and exact
   normalized business arguments. Only trusted controller metadata supplies it;
   model arguments cannot inject identity, operation keys or signed grants.
   Recheck the binding after awaiting review; changed source/identity/context or
   mutated reviewer arguments cannot authorize a different operation.
5. The gateway requires that typed context for writes and signs the exact
   normalized payload including identity and operation key. MCP service verifies
   signature, purpose/version, payload binding, context, date and operation-key
   binding before transactions. Reject missing, malformed, altered, expired,
   future-dated or cross-tool/cross-owner/cross-request envelopes. Grant lifetime
   is 120 seconds with at most five seconds of clock skew. Missing secret denies
   writes; read-only in-process servers can still serve reads.
6. Preserve deterministic operation keys per session/request/tool (and order ID
   for updates) and existing transactional idempotency. Exclude the transient
   envelope from the operation digest so fresh signed retries reuse the receipt.
   Re-resolve identity in MCP and require the reviewed customer to match. Unknown
   hotline handoff retains its existing phone-bound business validation.
7. Reuse write results only from successful execution authorized for the same
   current source, request, identity, tool and arguments. Changing interpretation
   context invalidates an unused approval, while an already executed receipt
   remains a record of that same operation. Do not let old state receipts or failed calls bypass a
   review or prevent a safe retry. Keep review attempts bounded by the existing
   tool budget. A restarted request can re-review and replay the same operation
   without creating a second business write.
8. A callback that violates operating hours/holiday rules must return a proposed
   alternative without inserting it. Never change an approved time silently.
   Evaluate aware timestamps in the configured business timezone; valid times
   retain the same instant. A customer can then approve a new valid time.
9. Independent offline tests must exercise denial and successful writes across
   all four tools through real BusinessTools, gateway, in-process MCP and domain
   service boundaries, using synthetic repositories and scripted model output.
   Verify tampering, timeout, stale results, state changes, retries, identity and
   reschedule behavior. No live model/DB, evaluation, migration or deployment.

## Limits and non-goals

No change to unrelated promotion association, Call Brief refresh, existing
completed memory, order fulfilment/refund/address persistence, policy documents,
remote prompts, user-facing speech generation or model training. No dashboards,
dependencies, worktrees, subagents or commits. Preserve existing user changes.
Scripted tests establish authorization transport/enforcement and business write
counts; they cannot prove real-model semantic accuracy, injection resistance or
public/hidden performance. MCP and agent must be upgraded together; unsigned
write clients must obtain a reviewed context rather than retaining a bypass.
