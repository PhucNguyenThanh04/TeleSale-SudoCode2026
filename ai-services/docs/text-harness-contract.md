# Text harness: responsibilities and repaired boundaries

This review uses application source, BTC requirements/mentor clarifications,
public business schemas, catalog/policy contracts and reference tool behavior.
It does not use public or held-out conversation scenarios, saved evaluation
traces or QA labels as repair inputs. No live model evaluation or database
mutation was performed during implementation.

## Lifecycle

1. Authenticate the backend caller, bind the channel/session identity and load
   only the owner's memory. A failed memory read cannot authorize a write.
2. Give the model the current customer utterance, actual conversation roles,
   current facts, historical episodes and bound tool observations.
3. Let the model propose business tools. The harness validates their arguments,
   identity, commercial evidence, current authorization and tool budget. It does
   not prepare or complete a purchase through a second language-rule controller.
4. Return actual MCP results to the model. Tools are serialized within a turn;
   built-in filesystem/subagent tools are excluded. Reads can be cached, writes
   use stable operation keys and an uncertain write is not blindly retried.
5. Check the answer against available evidence. An invalid draft gets at most
   one answer-only repair. A completed write can be acknowledged from its actual
   receipt without executing another action. No unrelated cached recommendation
   or price replaces the current answer.
6. Publish checked text, then commit the customer turn and actually published
   assistant text. A disconnect does not cancel an in-flight business write.
   Repeated requests must agree on identity, utterance, date and delivery mode.
7. Enqueue LangMem enrichment after commit. Candidates still require committed
   source evidence, owner/revision checks and the erasure gate before projection.

The special privacy-erasure route only creates a handoff for verification; it
never reports that a whole-customer purge has already happened.

## Source findings and changes

| Boundary | Defect | Repair |
|---|---|---|
| Agent loop | Automatic commercial preparation/continuation ran before or after the model | One model-led business loop; those methods removed from BusinessTools |
| Write authority | Customer intent and selection were inferred by separate language rules | Structured turn-local authorization, then mandatory mechanical evidence checks |
| Product selection | Historical speech could override an explicit tool SKU/color | Tool normalization uses catalog and explicit arguments; interpretation of history is limited to memory views |
| Commercial evidence | Quotes were not checked against the owner's phone; old quotes survived a completed purchase | Exact owner/date/SKU/quantity/address and basket unit prices; prior purchase invalidates older quotes |
| Retry | Write key depended on the number of preceding tool reads | Stable session/message/action key, also order ID for updates; cached write result reused |
| Tool budget | Default 3 calls could not perform catalog + stock + quote + create | Default 8, including the example configuration; explicit environment settings still override it |
| Verification | Broad scripted fallback could answer about another product | One constrained model repair or a verified transaction receipt |
| Streaming | Early text could publish before a late tool call or invalid suffix arrived | Wait for final message stop and validate the accumulated answer before publication |
| HTTP | Nonstreaming turns could run when no internal credential was configured | Fail closed, consistent with the other chat endpoints |
| MCP | Business, policy and release calls lacked an outer deadline | 10-second deadline covering client connection and tool call; existing safe error shapes preserved |
| Memory context | Expired/inactive facts could remain in active context | Filter by status and business date; retain stale warnings |
| Call Brief | Remembered order IDs could invent a created status and borrow an unrelated variant | Unknown status unless sourced; no guessed variant |
| LangMem | Assistant speech could substantiate a customer's goal | Customer goals require customer speech; advice requires assistant speech |
| Anonymous turns | Tool evidence/outcome lived in a bounded process-local dictionary | Commit evidence/outcome atomically with the turn and use persisted evidence on later verification |
| PII | Repeated address masking changed an existing marker | Stable masking across the model, verification and persistence boundaries |
| Delivery address | A redacted marker could reach tools as a real address | Resolve an exact marker only against customer-source address evidence; otherwise reject |

Stock, quote/promotion calculation, owned order access, transactional MCP
idempotency, per-customer worker ordering, evidence admission, erasure suppression,
pinned RAG releases and source applicability remain their existing service
responsibilities. This review does not certify those mechanisms through a live
production run.

## Deployment and compatibility

Apply `migrations/0005_durable_turn_evidence.sql` before starting the changed
memory service against an existing database. It adds two columns without deleting
rows. The managed fresh schema contains them too. No migration was applied by
this repair. Old anonymous evidence already lost from RAM cannot be recovered by
the migration. Known-customer enrichment jobs retain their existing evidence.

Every proposed create/update/callback/handoff passes a structured authorization
request to the configured model with a 5-second deadline. The provider must
support structured function calling. Failure, malformed output, missing literal
customer evidence or ambiguity denies the write. Mechanical commercial and
ownership checks still apply after an approval. The extra inference has a real
latency and token cost; offline tests do not measure semantic accuracy or cost.

Streaming can deliver an answer after a final provider message stop and evidence
checks. It no longer promises to publish a sentence while the same message is
still generating. If the provider omits stop metadata, final graph verification
publishes the response. TTFT figures measured under the previous publication
rule are not directly comparable.

Raw delivery addresses remain outside the model/memory context. An exact address
marker can be bound at the trusted tool boundary when customer-source evidence
resolves it, including an explicit `Địa chỉ: ...` in the current request. A
missing/ambiguous source requires clarification; a marker is never stored as a
physical destination.

Chat locks, response caches and rich session observations remain process-local.
Persistent MCP operation keys prevent duplicate business writes across process
retries; they do not make response caching or session locking distributed. A
production multi-worker rollout needs a separate coordination design.

Historical tests that directly invoke removed `prepare_*` or
`complete_purchase_if_ready` controllers describe the retired implementation.
They are not evidence of the new model-led lifecycle. Focused component checks
cover the replacement boundaries; this change does not claim that the entire
legacy test suite or saved evaluation replays pass.

## Verification limits

Tests use scripted models, independent fixtures, in-memory repositories and
mocked transports; the offline runner strips provider credentials, disables
`.env` loading and blocks network connections. Coverage includes actual graph
execution with both approved and rejected purchase proposals, retry behavior,
stream completion/disconnect, MCP deadlines, commercial evidence, memory commit,
LangMem source admission, erasure and API authentication. PostgreSQL integration
fixtures include the new migration but require a separate authorized DB run.

Passing these checks is evidence about harness behavior, not a new TSR/HR result,
a proof that the model generalizes, an M1 acceptance claim or a guarantee of the
3-second latency target. Existing published knowledge was not inspected,
republished or cleared by this work.
