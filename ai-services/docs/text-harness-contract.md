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
   use stable operation keys and an uncertain write retries only through the
   same idempotent operation.
5. Check the answer against available evidence. An invalid draft gets at most
   one answer-only model repair. A completed write's receipt is evidence for the
   model to compose its acknowledgement, without executing another action. If
   generation/verification still fails, report a protocol error; no scripted
   sentence replaces the current answer.
6. Publish checked text, then commit the customer turn and actually published
   assistant text. A disconnect does not cancel an in-flight business write.
   Repeated requests must agree on identity, utterance, date and delivery mode.
7. Enqueue LangMem enrichment after commit. Candidates still require committed
   source evidence, owner/revision checks and the erasure gate before projection.

After mechanical checks, every candidate passes a bounded structured grounding
review against the current source context. The reviewer checks the full answer,
including product binding, negation, conditions and exceptions. It neither calls
business tools nor writes customer speech. Invalid output or a five-second
deadline denies publication. The existing single repair passes the same review.
Grounding review remains mandatory with optional answer checks disabled.

Provider message completion does not publish text. The stream publishes only
the exact masked answer approved by final verification, once. This adds one
model inference for an otherwise valid answer, or two reviews when a repair is
needed; offline checks establish the boundary, not semantic accuracy or latency.

Business writes require a strict turn-local authorization decision and a signed
MCP grant. The controller binds approval to the current source, session/request,
verified identity, date, tool, arguments and interpretation context. Changes
during review invalidate the decision. Review failure has a distinct unavailable
error; a semantic denial does not become permission through history or a plan.
Policy-required handoff cannot authorize another tool or an unrelated brief reason.
Proposed private addresses use an opaque source marker so masking does not erase
the difference between accepted and rejected destinations. Raw values stay masked
in model inputs and are hashed when binding the source/context.

Only controller metadata supplies the typed grant; model-supplied routing and
authorization fields are stripped. The gateway signs the normalized wire request
with the MCP context secret (the internal token by default). The order service
verifies its signature, purpose, exact payload/context/date and operation key
before a transaction. Grants expire after 120 seconds, allowing five seconds of
clock skew. Identity is resolved again before claiming or replaying the write.
Transient signatures are excluded from durable operation hashes. Successful local
receipts can be reused for the same current source/request/identity/arguments;
old state receipts and errors cannot bypass authorization or stock/quote checks.
Review attempts remain bounded, and an exhausted tool budget does not invoke review.

Callbacks use the reviewed `mcp_shared/business-calendar.json` schedule, timezone
and dated opening exceptions. The controller normalizes `callback_at` before
review; an actual shift adds `requested_callback_at`. The reviewer sees both and
must respect customer constraints on changing the time. The grant binds those
canonical arguments; MCP stores the authorized effective time and returns it with
`moved_from`. A changed calendar that changes the canonical arguments invalidates
the grant. A whole-day closure preserves the requested clock time on the next
open day when within its opening windows; after-hours requests use the next opening.

The special privacy-erasure route only creates a handoff for verification; it
never reports that a whole-customer purge has already happened.

`order.preview_update` is an owned-order read for return/exchange consultation.
It uses the same current calculation as `order.update` but never claims an
operation, locks for a write or inserts an update. Its signed identity proof binds
the date, order, action, line, quantity and replacement. No customer write consent
is needed to read a preview. Results explicitly mark estimates and unconfirmed
policy eligibility; net amount fields include fees. They are not write receipts.
Executing an update still requires a fresh authorized write and recomputes data.

`catalog.get_details` is an exact parent/variant SKU lookup backed by public
catalog and approved technical source rows. It preserves catalog field authority,
source hashes and unresolved conflicts. Public size/prose sections are linked by
reviewed data and returned with `scope=section_context`; conditions and other
named models in a section must not be silently assigned to the selected product.
Details supply catalog selection/policy provenance and durable product evidence.
Missing technical sources/properties remain unknown. Final prices/current stock
are verified separately. Both new tools are available through model aliases and
the canonical MCP names, and mandatory answer review receives their actual scope.

## Source findings and changes

| Boundary | Defect | Repair |
|---|---|---|
| Agent loop | Automatic commercial preparation/continuation ran before or after the model | One model-led business loop; those methods removed from BusinessTools |
| Write authority | Customer intent and selection were inferred by separate language rules | Structured turn-local authorization, then mandatory mechanical evidence checks |
| Product selection | Historical speech could override an explicit tool SKU/color | Tool normalization uses catalog and explicit arguments; interpretation of history is limited to memory views |
| Commercial evidence | Quotes were not checked against the owner's phone; old quotes survived a completed purchase | Exact owner/date/SKU/quantity/address and basket unit prices; prior purchase invalidates older quotes |
| Retry | Write key depended on the number of preceding tool reads | Stable session/message/action key, also order ID for updates; reuse only successful bound receipts |
| Tool budget | Default 3 calls could not perform catalog + stock + quote + create | Default 8, including the example configuration; explicit environment settings still override it |
| Verification | Broad scripted fallback could answer about another product | One constrained model repair; receipts stay evidence, not prewritten speech |
| Streaming | Early text could publish before a late tool call or invalid suffix arrived | Wait for final message stop and validate the accumulated answer before publication |
| HTTP | Nonstreaming turns could run when no internal credential was configured | Fail closed, consistent with the other chat endpoints |
| MCP | Business, policy and release calls lacked an outer deadline | 10-second deadline covering client connection and tool call; existing safe error shapes preserved |
| Memory context | Expired/inactive facts could remain in active context | Filter by status and business date; retain stale warnings |
| Call Brief | Remembered order IDs could invent a created status and borrow an unrelated variant | Unknown status unless sourced; no guessed variant or scripted opening |
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

Upgrade/restart the agent and order MCP together for signed business writes.
The existing `MCP_INTERNAL_TOKEN` is the default signing secret on both sides;
in-process integrations may supply matching `context_secret` values. Unsigned
write clients now fail closed and must use reviewed controller context. Read tools
do not require a write grant. This repair adds no schema migration and performs
no deployment. The grant authenticates the trusted-process decision, not model
entailment; holders of the signing secret remain trusted. Offline scripted checks
cannot establish live-model consent accuracy or public/hidden performance.

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

## Model-owned conversation and source boundaries

The graph remains `accept -> retrieve_context -> run_agent -> verify`.
`run_agent` exposes business tools to the model. A separate structured model
review checks current permission before any write. Code enforces ownership,
schema validity, current stock/quote binding, tool budgets and idempotency.

The following controllers have been removed from application source, including
unused helpers and their imports:

- Nine `safe_*_reply` builders and the suggested-opening generator.
- Consultation snapshots, follow-up intent rules, shortlist ranking, presented
  offers, basket-consent parsing and automatic purchase completion.
- Customer-keyword query/category repair, guessed product selection, automatic
  pre-model stock/price refresh and rewriting an exchange action.
- Handoff summary/product/question/next-action inference from reason tables or
  conversation fragments. The model now proposes these fields through a typed schema.
- Automatic privacy-request routing; the model chooses handoff, the write reviewer
  checks it, and the erasure barrier still prevents private memory access/writes.
- Customer-fact supplementation, callback-outcome inference, blocker-resolution
  rules and regex rewriting of model-classified objections.

`retrieve_context` supplies source facts/history. Pending sessions expose their
last 12 committed turns, source IDs and total turn count, without inventing a
selection or consent state. This also preserves cross-channel evidence before
asynchronous extraction finishes. Older turns depend on admitted memory after
that window. Legacy consultation/offer fields are excluded from read projections
and model context; existing stored records are not migrated or deleted.

The extractor model owns semantic interpretation of customer facts and episode
updates. Admission validates owner/session/source IDs, types/domains, literal
quotes, supported values, PII, conflicts, committed dates and revision barriers.
It does not infer customer facts when the model proposes none, or determine
intent from a hand written list of phrases. A literal quote is provenance,
not proof of semantic entailment.

Before profile projection, the worker sends mechanically admitted customer facts
to an independent structured review using the configured LangMem model. The
review judges the full current customer utterance, preserving roles, scope,
negation, conditions, third parties and corrections. Bounded session history,
existing facts and tool receipts are interpretation context, not new customer
sources. Exactly one strict indexed decision is required per proposal; only
unchanged approved facts can pass. Episode-to-profile blockers use this gate too.
Tool facts retain their deterministic source checks.

Unavailable, malformed or timed-out review leaves the job pending under the
existing five-attempt policy, then failed; it cannot publish customer proposals.
The review deadline is ten seconds. Reviewed proposals are frozen before writes
and bound to their facts and source/context. Unchanged retries reuse that set.
Legacy or changed caches are revalidated; a persisted reset flag removes only
that customer's fact rows at the job revision before replay, including retries
after cleanup interruption. Erasure and lease fences still apply. Existing
completed facts are not migrated or retroactively certified. Episode semantics
remain a separate boundary. Offline checks establish gate/storage behavior,
not semantic model accuracy. Review adds a background inference and token cost.

Ordinary responses and recovery explanations come from the model. Missing or
rejected speech uses at most one answer-only recovery. If that fails, the runtime
returns a protocol error with no invented assistant text. `persist_agent` records
delivered speech and actual tool evidence. Failed turns retain completed tool
receipts with an empty assistant turn, or an already delivered model prefix.
Erasure barriers and retry/idempotency checks remain.

Retained conditionals check tool/schema and business contracts: authorization,
owned identity/order IDs, exact catalog variants, current price/stock/quantity,
promotion dates and policy sources, factual claim grounding, PII, actual action
receipts, persistence and source/revision consistency. They do not choose a
customer's intent or generate spoken reply templates. The policy ingestion
sanitizer still returns authoritative public-policy text as RAG data; these are
source documents supplied to the model, not an alternative response generator.

Historical private-controller tests have been retired or rewritten around these
boundaries. Their former expected conversations are not specifications for the
replacement. Independent offline fixtures check model-authored speech, explicit
tool arguments, approval/rejection, exact evidence, operational history,
streaming, errors, retries and memory boundaries. Passing them does not establish
TSR/HR, generalization, acceptance or live latency.

No scenario/QA labels or saved evaluation traces were used to guide this work.
No live evaluation, database migration, knowledge publication or deployment was
performed. Remote managed prompts, published knowledge and model training data
were not audited; source cleanup cannot prove absence of overfitting there.

## Agent/context source preservation

Address masking and address recovery share the same spans. Customer clauses
after an address retain quantities, payment, negation and purchase conditions.
Multiple distinct addresses remain ambiguous at the recovery boundary.

Memory reads retain committed `customer_statements` with their turn IDs beyond
the recent dialogue window, including anonymous sessions and pending worker jobs.
These are source utterances, not inferred selections or renewed write consent.
Generation and write/answer review receive the same sources. Changes invalidate
write review. Prompt projection removes duplicated recent dialogue and brief
profile copies; auxiliary summaries with complete source dialogue share a
4,000-character budget and expose `summary_truncated`. Customer sources remain
available up to the operational and prompt budgets described below; omissions are explicit.

`latest_session` is selected chronologically before relevant episodes are
limited. Scoped room/product facts do not enter global `must_not_ask` guidance.

Public catalog attributes survive observation serialization. Quotes retain a
context hash binding customer, address and basket without persisting those raw
private arguments. The hash is a consistency check, not an authorization grant;
owner/date/quantity/price checks and MCP recomputation still apply. Legacy quotes
without the binding can require a fresh read. Up to 20 supported observations
are retained after filtering internal reads; large public evidence and later
receipts are no longer silently discarded.

The model-facing catalog argument is `max_list_price_vnd`; the canonical MCP
argument remains `max_price_vnd`. Final affordability requires quotes rather
than an empty list-price-filtered search. Repeated blocked reads expose recovery
hints using model tool names. Proposal/model-round budgets bound unproductive
loops independently of successful MCP call counts.

The existing mandatory answer review also rejects unanswered requests,
unnecessary clarification and violated customer constraints. This adds no model
inference. Offline regression and in-process MCP tests cover the source and
execution boundaries; they do not establish live-model semantic accuracy or
latency. Upgrade the harness and memory service together.

### Audit repair contracts (2026-11-21)

Apply migrations 0006 and 0007 to an existing database before upgrading AI and
memory. Bootstrap and role provisioning include the same changes. Offline audit
work does not apply migrations or restart running services.

The shared masker recognizes separated phone/identity/account numbers and long
payment identifiers while retaining dated prices and product IDs. Typed phone
numbers in an unlinked chat do not verify identity; numeric Facebook/Zalo IDs
also cannot fall back to a phone lookup. Signed backend verification can resolve
an unlinked channel, but cannot override another customer's linked channel.

Private delivery context lives in an erasable turn column with source turn/date
and a masked source statement. The model receives only a safe reference; the
write reviewer receives that masked source plus current consent. Multiple new
addresses invalidate an old reference. References older than 180 days require
new customer evidence. Completed AI memory erasure clears owner caches and
pending playback, cancels other in-flight replies, and starts later contact
anonymously. The tombstone still blocks delayed jobs and old customer writes.
This does not assert deletion of separate commercial/accounting records.

Return eligibility uses verified order and receipt dates plus stored condition
evidence. Missing conditions produce `review_pending` intake; this is neither a
pickup schedule nor an approved refund. Definite ineligibility does not write.
Old policy fees and refund periods remain distinct. Previews retain estimates,
missing conditions and source policy version.

Episode resolutions require independent review against the original item and
the complete current turn. Unreviewed/conditional/negated resolutions do not
close items. Retry-bound review digests prevent stale approval reuse. Summaries
rebuild from current canonical topics, latest accepted facts and verified actions.

Knowledge releases are pinned when policy search is first requested in a turn,
then reused within that turn. Ordinary conversation does not call release lookup.
Release-reference lookup validates the manifest without scanning index vectors.
Snapshot serving batches source/revocation reads, caches up to eight validated
snapshots, and still checks current release/source revocation and content hashes.

Model context is capped at 70,000 serialized characters, preserving current input
and prioritizing current facts, topics and observations within field budgets.
`context_completeness` exposes omissions and up to sixteen source references.
Writes are denied when relevant source context is incomplete. Operational replay
reads pending turns plus twelve recent completed turns, with at most 240 rows
per relevant session. Longer sessions are conservatively marked incomplete;
this can require a new session and explicit customer clarification before a write.
The runtime retains at most 128 idle/active session entries, expires idle entries
after fifteen minutes, keeps a bounded recent response cache and 64 tool calls
per session, and preserves pending playback entries until acknowledgement/expiry.

Internal `memory.replay` binds committed replies to a request hash. Conflicting
retries fail; a completed retry does not regenerate or execute business tools.
Historical turns without a request hash require a new message. If a business
write committed but its reply did not, its durable operation ledger blocks blind
re-execution and returns `turn_recovery_required`; a new message can inspect the
owned order. Replayed voice content is the acknowledged/heard prefix, and the
Call Brief is not persisted as part of replay. Fresh turns rebuild context.

The total turn deadline defaults to 90 seconds and includes identity, memory,
tools, verification, repair and publication. Up to three seconds inside that
deadline are reserved for receipt persistence on timeout. No unchecked model
tokens are published. First-answer latency therefore includes complete answer
generation and verification; no live latency target is claimed from offline tests.

Masked tool memory retains order-update/status/preview receipts and dated policy
provenance. A callback receipt has a consistent scheduled status. Public memory
changes preserve actual customer/tool provenance. Historical policy evidence
does not grant current rights. PB-01/06/09 are explicit in the main prompt, and
repair reuses the selected compiled prompt. Split-order create payloads expose
`basket_skus`; distinct authorized creates have distinct stable keys. An offline
four-product flow takes seven business calls within the default budget of eight.
The default output budget is 1,024 tokens for structured multi-line requests.
