# Implementation plan

1. Detect proposals after the ordinary paired CLI and add a separate Full K1 file.
   Verify real offline worker/decisions and exactly A/B, finish, review, C; reject invalid lineage.
2. Scope review queries/frontend to the experiment and retain K0 release items.
   Verify service filtering, gateway forwarding and browser release selection.
3. Keep review UI running after managed ordinary eval and document the separate file.
   Verify launcher behavior without starting services/resetting DB.
4. Run focused regression checks, inspect final diff against the spec, document evidence.

Execution is in the current checkout, without subagents or commits. Existing dirty
changes belong to earlier work and must be preserved.

Completed 2026-11-17. Implementation, targeted tests and requirement audit are
recorded in [manual knowledge eval evidence](../../manual-knowledge-eval-20261117.md).
No live evaluation, embedding, DB reset, commit or subagent work was performed.
The reset test double needed prepare/playback no-ops to exercise the existing
runner lifecycle; production reset behavior and the two-reset assertion stayed intact.

Corrected after user clarified the desired two-file interface: no public
manual-review or resume step. The paired CLI runs detection then finishes;
run_knowledge_eval.py consumes --base-run and executes only published Full K1.
