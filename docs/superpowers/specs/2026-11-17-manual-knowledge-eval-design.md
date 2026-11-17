# Manual three-arm knowledge evaluation

Corrected user flow: ordinary No-memory/Full K0 pair → system gap proposals →
human review/publication on `/knowledge` → separate `run_knowledge_eval.py` file
evaluates Full K1 only. The paired command finishes without waiting for review.

- Use the canonical paired runner for A/B and canonical full runner for C. No fourth arm.
- Detect after the ordinary paired CLI when Knowledge is enabled and configured.
  Remove the public `--manual-review` workflow. BTC single-trace CLI stays unchanged.
- Only failures/signals from audited Full K0 produce experiment proposals. Persist
  experiment-bound evidence and process only those jobs. Never auto-approve in this mode.
- Save proposals beside the frozen paired run and print a scoped frontend link. Reviewers can
  approve, edit into new revisions, or reject proposals using existing services.
- Retain K0 revisions in the frontend release selection. Resume accepts only a K1
  extending K0 with approved revisions from these proposed gaps, reviewed tests,
  decisions and unchanged public sources. Rejected/unpublished drafts never enter C.
- Keep managed API/gateway running after ordinary eval for frontend review. The
  evaluation itself is finished; no automatic third arm. Launch the second file
  explicitly using `--base-run`, against the original boot, without fresh startup.
- Freeze source/settings/model/seed/scenarios/scorer/K0 artifacts. Serialize follow-ups.
  C resets runtime memory using the existing runner while retaining published K1.
- Report A/B/C BTC metrics and review provenance. Target retrieval is not answer
  correctness; generated tests are not independent labels. Do not auto-resolve gaps.
- Verify offline with RAM repositories, controlled runner doubles and browser/gateway
  tests. Do not run live evaluation, embeddings or database resets for implementation.
