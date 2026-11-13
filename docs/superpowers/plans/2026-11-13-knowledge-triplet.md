# Three-arm knowledge experiment

Implement in the current checkout. Preserve unrelated gateway authentication edits.
No live models, embeddings, database mutations or release activation during implementation.

## Contract

- One CLI runs baseline K0, full K0, simulated review/publication, full K1.
- Reuse audited official pair and production knowledge lifecycle; never fake worker,
  permissions, source validity, test approval or release checks in the live CLI.
- Auto-review is limited to an explicit pre-reviewed plan with source hashes,
  exact turn locators, correction payload and deterministic answer assertions.
- Feedback comes exclusively from selected failed full-K0 turns, with trace provenance.
- Worker processes only those events. Existing technical/correct-refusal gaps are excluded.
- Preserve active revisions in K1. The manifest labels simulated approval and
  experimental cross-release scoring; it is not an official same-release pair.
- Independent memory resets, frozen scenarios/model/source/seed, pinned releases.
- Save progress after K0 and publication; resume checks immutable inputs before spending.
- Export three-arm BTC numbers and per-gap answer/source evidence; no guaranteed gains.

## Verification

1. Tests first for plan validation, scoped jobs and lifecycle permissions/source gates.
2. Offline orchestration tests prove exactly three executions, release/trace mapping,
   resume, rejection of drift/no gaps and evidence-linked reporting.
3. Real lifecycle integration with in-memory repository/index/encoder adapters, no
   network or model API. Focused existing coordinator/knowledge tests once changes settle.
4. Document full CLI, auto-review limits, source-plan preparation, costs and reset scope.

## Verified implementation

- Entry point: `python -m eval_harness.knowledge_triplet`; operator guide:
  `ai-services/eval_harness/KNOWLEDGE_TRIPLET.md`.
- 93 focused tests passed; 3 opt-in integration tests skipped. The existing
  `RuntimeResetTests.test_both_configurations_reset_before_each_run` was excluded
  after reproducing its same conversation-phase failure with the original HEAD
  worker implementation loaded in a separate Python process. Its benchmark/reset
  implementations and fixture were not changed by this task.
- Real BTC scoring, manifests and extraction reports exercised with synthetic
  traces. Real feedback/analysis/review/publication/search services exercised with
  an in-memory repository, index and embedding adapter. The release-extension
  gate also passed against those actual built hybrid manifests.
- CLI help and `git diff --check` passed. No live models, external embeddings,
  database writes or real releases were invoked during implementation.
- No change to BTC datasets, saved evaluation runs, or the unrelated gateway
  authentication work. No measured live improvement is claimed.
