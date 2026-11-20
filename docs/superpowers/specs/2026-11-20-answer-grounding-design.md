# General answer grounding

The current deterministic answer checks can accept a statement that reverses a
policy condition or invents an attribute outside their recognized vocabulary.
This change implements the first repair stage agreed in conversation: grounding
of customer-facing answers. Memory extraction, Call Brief, write authorization,
model selection and Knowledge availability are outside this stage.

The user authorized autonomous specification, planning and implementation in the
current checkout. No worktree, subagent, commit, live model evaluation, database
change or remote prompt publication is part of this work.

## Requirements

1. Preserve the existing deterministic checks for identity, commerce, PII,
   internal output, policy applicability and actual action receipts.
2. After those checks pass, review the entire candidate with the configured
   model through a strict structured output. Review every factual assertion,
   including conditions, exceptions, negation, uncertainty, product and variant
   binding, without selecting business actions or generating customer speech.
3. Current successful business observations are authoritative for commercial
   facts. Policy evidence must retain applicability, dependencies and source
   metadata. Failed, conflicting or malformed policy evidence cannot authorize
   a claim. Conditional evidence can support a conditional explanation, never
   an unconditional entitlement.
4. Customer statements and admitted memory describe the customer's situation.
   Earlier assistant speech, historical prices and plans do not independently
   prove current product specifications, policy rights or completed actions.
   Instructions embedded in any data are not reviewer instructions.
5. A valid approval must explicitly agree across strict fields. Timeout,
   unsupported structured output, malformed or inconsistent output denies
   publication. The review has a five-second deadline and performs no tools.
6. An unsupported draft receives at most the existing one answer-only repair.
   The repair must pass the same deterministic and semantic checks. Exhaustion
   returns the existing protocol error; no canned answer or extra write is added.
7. Streaming and collected text share the same publication boundary. Provider
   chunks, including a completed message, cannot publish before final review.
   Approval is bound to the exact masked final answer. Rejected speech must not
   enter delivered history; existing disconnect, receipt and retry behavior stays.
8. Grounding remains mandatory when optional answer checks are disabled.
9. No product names, SKU patterns, scenario IDs, public/hidden conversations,
   saved traces, QA labels or evaluation results may determine new behavior.
   Tests use independent synthetic sources across unrelated domains, paraphrases,
   contradictions and insufficient evidence. They verify integration and
   fail-closed behavior, not semantic model accuracy.

## Chosen approach and tradeoffs

A structured semantic reviewer is the chosen approach. Extending phrase lists
would leave the same failure for new attributes and paraphrases. Restricting
all answers to literal source quotations would reject legitimate explanations.
The existing model and structured function-calling interface are reused; no
dependency or evaluator framework is introduced.

The reviewer adds one inference for an otherwise valid answer and another only
if a repaired answer needs checking. This may increase latency and cost. Offline
tests cannot establish reviewer accuracy, hidden/public scores or the latency
target. No live calls are authorized in this stage.

The final review checks both source boundaries and the exact publication path.
Focused offline tests cover the changed behavior; the unrelated legacy suite
and previous evaluation artifacts are not acceptance criteria for this change.
