# Evidence-led Text Harness Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reproducible full-versus-baseline BTC evaluation and an evidence-linked failure matrix that identifies the next text-harness repair.

**Architecture:** Keep `eval/run_eval.py` as the only harness replay and BTC `reference_eval.py` as the scorer. Add local trace/provenance auditing and a sanitized diagnostic sidecar, then run the two configurations against independently restored copies of one eval seed. Diagnose failures before planning a runtime fix.

**Tech Stack:** Python 3.12, `unittest`, `jsonschema`, PostgreSQL, three MCP HTTP servers, configured LLM, BTC JSON schemas and reference evaluator.

**Spec:** [evidence-led text harness evaluation design](../specs/2026-10-22-evidence-led-text-harness-evaluation-design.md).

## Global Constraints

- Preserve the existing dirty working tree. Read each touched file and its diff before edits; do not commit unrelated changes.
- BTC amendments/mentor answers, tool schemas, mock results and reference evaluator outrank sample labels. Do not modify BTC files or runtime based on `scenario_id`, sample wording, SKU or answer labels.
- `request.on` is the business clock. Full and baseline have the same model, parameters, code, tools, data and initial DB seed; baseline only disables prior-session memory.
- Use eval-named isolated databases. Never reset demo/production state. Do not log DSNs, credentials, raw PII, unsanitized prompts or tool results.
- A 39-turn public run cannot establish BTC p95 compliance; the BTC latency protocol requires at least 100 turns and excludes three warm-up turns.
- Store artifacts under a new timestamped run directory; never overwrite `eval/runs/full.jsonl`, `eval/runs/baseline_no_memory.jsonl`, `report.json`, or the user's `baocaomemory.md`.

## Review Focus

- A missing, duplicate or reordered turn must fail trace coverage audit: Task 1 tests it.
- Dirty source files or different model/seed/tool configuration must make a pair incomparable: Task 1 tests it.
- A memory read failure must appear as unknown/failed, never as an empty but successful memory: Task 2 tests it.
- A diagnostic sidecar containing raw phone/address/name/tool payload must be rejected or masked: Task 2 tests it.
- A mismatch between transcript and extracted `questions`, `claims` or `facts_used` must be flagged for review before metric claims: Task 3 checks representative rows.

---

### Task 1: Trace coverage and run provenance

**Files:**
- Create: `eval/trace_audit.py`
- Create: `eval/test_trace_audit.py`
- Modify: `README.md` (evaluation commands and artifact meaning only)

**Interfaces:**
- `audit_trace(scenarios_dir: Path, trace_path: Path, expected_config: str) -> dict` validates every JSONL row against `schemas/trace_log.schema.json` and checks one unique row per input scenario/call/turn in scenario/call/turn order, one run ID and the expected config. Return row count, missing/extra/duplicate/out-of-order coordinates and errors; CLI exits nonzero on errors.
- `source_snapshot_digest(root: Path) -> str` hashes relevant source contents, including dirty/untracked `ai-services/app`, `eval`, `run_eval.py`, migrations and config declarations, excluding `.env`, virtual environments, caches and generated runs.
- `build_manifest(*, trace_path: Path, scenarios_dir: Path, config: str, source_digest: str, seed_id: str, seed_digest: str, model_id: str, model_params: dict, tool_mode: str, guardrails: dict, database_identity: dict, hardware: dict, started_at_utc: str, scorer_report_path: Path) -> dict` records only the spec's nonsecret fields and SHA-256 of trace, BTC scenario/schema/mock/policy/catalog snapshot, and scorer report. Read the run ID from validated trace; reject missing values and secret-bearing keys.
- `audit_pair(full_manifest: dict, baseline_manifest: dict) -> list[str]` checks source/BTC data/seed hash, model and nonsecret parameters, tool mode, guardrail settings and trace coverage; config and DB name/run ID may differ. Return incompatibilities.

- [ ] **Step 1: Write failing tests** for one valid two-call trace and missing, duplicate or reordered turns, wrong config/run ID, invalid BTC schema row, changed dirty source file, secret-bearing manifest field and mismatched seed/model. Use temporary files and synthetic scenario IDs; assert precise audit errors.
- [ ] **Step 2: Run** `ai-services/.venv/bin/python -m unittest eval.test_trace_audit -v`; confirm the new tests fail for missing auditor behavior.
- [ ] **Step 3: Implement** the four interfaces in `eval/trace_audit.py` and a CLI with `trace`/`manifest`/`pair` subcommands. Record SHA-256 hashes in safe manifests. Fail closed when a required comparison field is absent; never infer a common starting seed from database names alone.
- [ ] **Step 4: Run** focused tests and `ai-services/.venv/bin/python -m unittest discover -s eval -v`; expect PASS. Audit an existing historical trace as a smoke check and label its result historical.

### Task 2: Stage evidence without changing BTC trace rows

**Files:**
- Modify: `eval/run_eval.py`
- Modify: `eval/test_run_eval.py`
- Create: `eval/stage_evidence.py`
- Test: `eval/test_stage_evidence.py`

**Interfaces:**
- `stage_evidence(state: dict, response: object, *, scenario_id: str, call: str, turn: int) -> dict` returns only: coordinates, `identity_status`, memory read status, available prior fact keys and scope IDs, prior episode count, Call Brief presence and safe field/key counts, memory write count/error, and business tool names/success statuses. It does not copy values, names, phone, address, prompt or raw tool results.
- `run(args, runtime=None)` retains BTC JSONL shape and writes `<trace>.stages.json` next to the existing `.events.json` and `.report.json` sidecars. The sidecar is diagnostic only; BTC evaluator still consumes the JSONL trace.

- [ ] **Step 1: Write failing tests** for known identity with prior facts/brief, unknown or ambiguous identity, memory read failure, successful/failed `order.create`, and raw PII present in state. Assert that the diagnostic sidecar contains no raw PII and distinguishes unavailable memory from an empty profile.
- [ ] **Step 2: Run** `ai-services/.venv/bin/python -m unittest eval.test_stage_evidence eval.test_run_eval -v`; confirm the new cases fail.
- [ ] **Step 3: Implement** `stage_evidence` from existing `TurnState` and emit one sidecar item per trace row. Do not add a second LLM call or alter runtime routing. Keep raw `call_brief`, fact values and tool result bodies out of sidecar.
- [ ] **Step 4: Run** focused tests, root `eval` suite and BTC trace-schema validation; expect PASS and no changes to the reference scorer's input contract.

### Task 3: Reproducible public pair and failure matrix

**Files:**
- Create: `docs/eval-runbook.md`
- Create: `eval/failure_matrix.py`
- Create: `eval/test_failure_matrix.py`
- Create: `docs/eval-findings/2026-10-22-public-text-harness.md` (only after a new pair is actually run; otherwise write a clearly marked environment blocker in the runbook)

**Interfaces:**
- `build_failure_matrix(scenarios_dir: Path, trace_path: Path, stages_path: Path, btc_report_path: Path) -> list[dict]` reports each scenario/call outcome and observed stages. Each finding includes trace coordinates, tool evidence and `status=observed|unknown`; it must not infer missing memory from `facts_used=[]` alone.

- [ ] **Step 1: Write failing tests** for a successful order, a known customer whose brief is present but whose agent never calls `order.create`, an unavailable memory read, a failed business tool, and a `handoff.transfer` expected-outcome control. Assert the first *observed* failing stage and an `unknown` stage where evidence is absent.
- [ ] **Step 2: Run** `ai-services/.venv/bin/python -m unittest eval.test_failure_matrix -v`; confirm failure before implementation.
- [ ] **Step 3: Implement** the matrix generator. Use BTC `success_if` and scorer output for expected outcome, tool trace for actual action, and Task 2 sidecar for identity/read/brief. Preserve uncertainties; do not copy sample answers into agent code.
- [ ] **Step 4: Document and perform the pair run** only after the three MCPs point to eval-named DBs restored independently from the same migration/data/seed snapshot. Record the seed identifier/hash, code snapshot hash, nonsecret model/parameter and tool settings, hardware, UTC start time and run IDs. Validate all 39 expected public turns with Task 1. Run `full`, restore the same seed, run `baseline_no_memory`, then run BTC `reference_eval.py` on those exact traces. Keep the trace and manifest paths together in one new `eval/runs/<timestamp>/` directory. If endpoints/model/DB reset are unavailable, stop at runnable tests and record the specific blocker; do not substitute older traces.
- [ ] **Step 5: Review** the extracted `questions`, `claims` and `facts_used` against agent text/tool arguments for all failed calls and at least one passing control. Record extractor errors separately from agent errors. Generate the failure matrix and findings note with RQR/CCR/TSR/HR, guardrail violations, per-case failures and descriptive latency; avoid a p95 compliance claim from 39 turns.
- [ ] **Step 6: Run** root `eval` tests, AI service tests, BTC trace schema audit, pair audit and `git diff --check`; record exact commands/results and what used mock versus PostgreSQL/MCP HTTP/LLM.

### Task 4: Choose the first repair and independent development cases

**Files:**
- Modify: `docs/eval-findings/2026-10-22-public-text-harness.md` after Task 3 produced evidence
- Modify: `eval/held_out/README.md` only to distinguish development cases from the existing reserved held-out set
- Create: a separate follow-up implementation plan under `docs/superpowers/plans/` for the diagnosed defect; no speculative runtime edits in this task

**Interfaces:**
- The follow-up plan names the violated BTC contract, exact first failing layer, reproduction test, independent wording/product variant and unaffected control. Rank candidates by lost Task Success across scenarios, hidden-test class coverage, guardrail risk and effort; do not rank by sample memory-label differences alone.

- [ ] **Step 1: Rank** observed failures from Task 3. Mark uncertain cases for additional trace inspection; choose one root-cause class only when its evidence is sufficient.
- [ ] **Step 2: Design** at least one development variant in the chosen class with a different expression and product plus one unaffected control. Keep these separate from BTC public samples and the reserved held-out memory set; do not tune against hidden-test guesses.
- [ ] **Step 3: Write** a focused repair plan with TDD and mock BTC verification. Include a full/baseline rerun after the repair and stop conditions for TSR, RQR, CCR, HR and guardrail regressions. If the current pair already clears task outcomes, prioritize the next measured gap instead.
- [ ] **Step 4: Report** the chosen repair and evidence to the user for review before implementing that separate plan. Schedule BTC-compliant latency measurement on at least 100 turns after functional behavior stabilizes.

## Completion gate

Tasks 1–3 are complete only when the new trace pair and scorer report exist and are comparable, or when the environment blocker is recorded precisely with runnable audits/tests ready. Task 4 requires a real failure matrix; a historical report alone cannot select the repair. No score from the hidden BTC set is inferred.

## Execution status (2026-10-22)

Tasks 1–3 produced the trace auditor, masked stage sidecar, BTC score wrapper with input hashes, failure matrix, tests and [runbook](../../eval-runbook.md). The live pair is blocked: configured DB is `telesale`, no MCP listeners exist on 8011–8013, and the current user cannot access the Docker socket. Task 4 remains pending because no new comparable pair exists. The ignored ledger under `.superpowers/sdd/2026-10-22-evidence-led-text-harness-evaluation/` records the review findings and test evidence.
