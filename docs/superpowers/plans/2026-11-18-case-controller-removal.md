# Remove conversation hardcoding

## Objective and evidence boundary

Remove application branches that implement particular conversations, choose
customer intent/consent, rank a predetermined recommendation or compose spoken
answers in code. Inspect source and authoritative business contracts, without
reading public/held-out scenarios, saved traces or QA labels as repair inputs.
Keep authentication, ownership, commercial evidence, tool schema validation,
PII handling, persistence/idempotency and source-backed business calculations.

Work in the current checkout. No subagents, worktrees, live model calls,
benchmarks, database mutations or changes to datasets. Preserve all existing
work. Do not add comments or explanatory docstrings to code.

## Completion requirements

- Remove the legacy deterministic reply builders and opening generator from
  application source, including their obsolete caller/import paths.
- Audit active model orchestration, tool boundaries, context/brief rendering,
  memory admission/projection and streaming for hidden conversation controllers.
- Remove or replace inferred focus, purchase/consent, shortlist and task-completion
  decisions where they steer the model, alter proposed tool arguments or filter
  evidence according to hand-written conversation cases.
- Keep domain/security checks backed by tool/schema/policy contracts; record
  why each retained family is an invariant rather than a scenario workaround.
- Migrate/retire tests of removed private controllers without treating their
  expected replies as desired runtime behavior. Retain and verify independent
  component contracts for model-authored text, tool evidence and durable memory.
- Verify the entire source dependency boundary and focused offline behavior.
  Report actual limitations; offline checks do not certify hidden-set quality.

## Work ledger

- [x] Remove legacy reply builders and obsolete imports/tests.
- [x] Remove conversation planning hidden in context, memory and evidence selection.
- [x] Audit remaining conditionals, literals, prompt examples and tool normalization.
- [x] Verify source contracts and replacement behavior, then completion audit.

## Initial source evidence

`session_nodes.py` still defines nine `safe_*_reply` builders with about 40
natural-language response branches. `brief_opening.py` formats greetings through
outcome/product/blocker branches. They have no runtime caller except the separate
mechanical `transaction_selection_mismatch` check, but remain in application
source and are imported by historical tests.

The active dependency graph still includes `consultation`, `consultation_followup`
and `consultation_shortlist`: commerce evidence infers quantity/address from
speech; context derives focus/recommendation/selection; streaming tests task and
purchase intent. These need source-driven review beyond deleting old replies.


## Completed changes

Deleted the reply/opening builders and the consultation, follow-up, shortlist,
presented-offer, customer-fact fallback, catalog-query and callback-request
controllers. Basket code now verifies quoted arithmetic only. The factual
transaction/SKU check lives in policy, outside reply construction.

The model owns query/category, product choice, tool sequence, purchase permission,
exchange action, questions and next steps. Context no longer performs commercial
refreshes before model choice. Streaming waits for a completed model message and
factual checks; no conversation-keyword progress/task classifier remains.

The worker consumes typed model proposals and actual tool receipts. It no longer
adds customer facts or recognizes callback/blocker outcomes through a rulebook.
Admission retains types, domains, literal source quotes, values and source identity;
semantic interpretation belongs to extraction. Reads expose bounded committed
transcripts for pending memory, including prior owned sessions, rather than
inventing state. Existing consultation/offer fields are filtered from projections
and model context without modifying stored data.

Handoff now takes typed model-authored summary, questions and next_action. Code
binds verified identity/time/history sources and validates any selected product
or price; no reason-to-narrative table or guessed focus remains.

## Retained invariant families

| Family | Reason retained |
| --- | --- |
| Channel/session identity and CRM binding | Determines which private records/tools are permitted; does not choose conversational intent |
| Typed tools, catalog variants, source prices/stock/quantity | Enforces actual business contracts on explicit model arguments |
| Current semantic write review | A model checks current permission; old consent or recommendation is not authorization |
| Grounding, PII and action receipts | Rejects unsupported model claims; generates no replacement speech |
| Memory owner/source/quote/domain/revision/TTL checks | Validates proposed evidence and prevents cross-customer or stale writes |
| Stable operation keys, budgets, retries and erasure barriers | Prevents duplicate actions, disclosure and lost receipts |
| Policy sanitization and numerical business rules | Supplies authoritative tool/RAG data; does not bypass model reply generation |
| Brief/source formatting and relevance retrieval | Presents source facts; no inferred selection or consent is inserted |

The evaluator's role vocabulary helpers were retained because its reference
adapter imports them. They are not an application consent/blocker planner.
Evaluator CLI descriptions were retained as literal help text when earlier
comment/docstring cleanup removed __doc__; scoring logic is not a repair target.

## Verification and test migration

- A focused sweep across model/tool, evidence, memory, streaming and API components
  passed 332 checks. This was not the repository full suite or a live evaluation.
- Following the additional handoff audit, 89 targeted checks passed: 87 together,
  then the two delivery checks after correcting their mock gateway interface.
  These include model-before-handoff, missing-model errors, typed handoff data,
  owner/erasure barriers, unsupported completion claims and no code-written repair.
- Final static inspection: 557 tracked/new Python sources parse; no Python comments
  or explanatory docstrings remain. No missing application imports remain, and
  git diff --check is clean.
- Historical tests tied to removed private controllers were retired, and tests of
  automatic refresh, inferred selection/facts and code-authored recovery were
  rewritten. Seven import-only test modules left by that retirement were deleted.
  Independent regression tests live in test_model_owned_conversation.py and
  test_llm_reply_boundary.py. Removed test counts are not quality improvements.
- Controller-test snapshots/manifests from this work are under
  /tmp/telesale-retired-controller-tests-jk0bjuhx,
  /tmp/telesale-retired-automation-tests-q0y40mas and
  /tmp/telesale-retired-lexical-admission-tests-f0cxpyug. The current diff is the
  authoritative final set; some tests in early snapshots were subsequently
  replaced or restored as independent contracts.

## Limits

No public/held-out scenario files, QA labels or saved traces were used as repair
inputs. No live model/eval, database mutation, migration, knowledge publication,
deployment or full repository suite was run. Extraction semantics now rely on
the model; literal provenance alone does not prove an interpretation correct.
Pending transcripts retain the last 12 turns per session until admitted memory
provides longer-term context. Managed remote prompts, published knowledge and
model training data were not inspected. This source cleanup does not establish
hidden-set scores, live latency or absence of overfitting in data/models.
