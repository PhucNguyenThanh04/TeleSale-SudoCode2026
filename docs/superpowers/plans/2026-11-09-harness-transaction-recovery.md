# Harness transaction recovery

Goal: repair the existing consultation path identified in the November 9 traces,
without compensating for individual Qwen answers or running live evaluations.

Constraints: current checkout, preserve existing edits, no subagents/worktrees,
no live inference, focused offline verification only.

1. Reproduce returning-customer purchase with sourced product advice but no
   catalog metadata. Fetch metadata within the existing preparation budget,
   rederive selection, and prepare quote/stock. Advice alone never grants consent.
2. Replay variant selection and explicit offer acceptance through real business
   orchestration. Preserve stale-offer, ambiguity, refusal, and ownership gates.
3. Check price/promotion verification and task-aware recovery against trace
   failures; fix proven gaps without changing the guardrail configuration.
4. Check policy-question context and eval question-slot extraction against the
   observed failures; fix narrowly and verify related offline tests.
5. Review the diff and run focused regression checks. Report remaining model-
   dependent behavior separately; do not claim a new live-eval success rate.

## Verification and outcome

- Reproduced missing returning-customer metadata with two failing offline tests.
  Sourced, active, unambiguous advice now permits a bounded catalog read; invalid
  or ambiguous facts do not. Selection is rederived after the read, before stock.
- Verified variant purchase and the two-turn present-price/accept-price flow
  through BusinessTools. No offer acceptance means no order; successful create
  remains exactly once. Existing memory provenance and stale-offer tests pass.
- A new price regression exposed that a discount amount was accepted as a sale
  price. Separated price and discount evidence; verified recovery rejects wrong
  prices, fabricated discounts and false promotion denial when checks are enabled.
- Reproduced and fixed lost exchange context in policy queries and product
  questions misclassified as blockers. Did not change official ground truth or
  rewrite historical result artifacts.
- Focused regression run: 236 passed, one dependency deprecation warning.
  Command uses PYTHONPATH=.:ai-services and ai-services/.venv/bin/pytest across
  consultation, commerce, memory, price/promotion and extraction test files.
  An initial collection attempt without the root PYTHONPATH failed on eval import;
  the corrected run passed. No full suite, live inference, eval or restart.
- Remaining limits: unknown-error investigation and model-chosen search/tool
  behavior are outside these fixes. The existing local .env disables answer
  guardrails; it was not changed. No new runtime success rate is claimed.
