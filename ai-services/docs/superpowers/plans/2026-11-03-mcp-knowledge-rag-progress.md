# Progress — 2026-11-03-mcp-knowledge-rag.md

Scope: approved functional implementation only; no eval, benchmark, calibration, live model, dependency installation, database migration, service restart, commit or subagents.

Pre-flight: schema -> source/rules -> encoder/index/repository -> publisher/search -> MCP -> consumers share SourceChunk/Evidence, absolute deadlines and immutable release manifests.
Ruling: work in current checkout and self-review; user/repository instructions override skill worktree, commits and reviewer dispatch.
Ruling: keep lexical lifecycle records readable for existing review history, but never serve or activate them as hybrid; build hybrid separately through the existing approval/CAS controls.
Ruling: missing measured runtime config is a readiness failure, not an excuse to invent production thresholds; functional tests supply explicit fake config.

Tasks 1–10: functional implementation complete; environment-dependent verification remains explicitly unperformed.

Task 1: complete — contracts + settings: 16 focused tests passed; RED before implementation.
Task 2: complete — parser/rules: 4 focused tests passed; 99 source sections accounted for, 93 safe serving sections, six excluded administrative/internal-only sections. No QA used.
Task 3: complete — 4 focused fake-encoder tests passed, including expired queued work and running-worker ownership after timeout.
Task 4: complete — 3 focused tests passed with local in-memory Qdrant and fake dependency failures. Migration written, not applied; SQL role checks pending real test DB.
Task 5: complete — 8 focused build/release tests passed. Repeated build stable; failed index never ready; source tombstone blocks pinned reads. No DB migration executed.
Task 6: complete — 8 focused search/erasure tests passed. All-or-nothing operational errors, grouped evidence and explicit missing dependencies work under fake config.
Task 7: complete — dedicated authenticated MCP, signed request-bound context, four-service factory/launcher and separate CUDA build/Compose artifacts. 24 focused launcher/gateway/consumer tests passed; authenticated HTTP rejects unauthorized requests in ASGI without running a real server.
Task 8: complete — canonical evidence consumers and conditional grounding updated. 5 initial gateway/grounding tests passed; additional regressions fixed always-on applicability grounding and conflict preservation under hard limit (RED -> GREEN).
Task 9: complete — 4 functional MCP -> BusinessTools -> guardrail -> Knowledge Gap Loop tests passed using scripted outputs/fake dependencies. No live model or evaluation runner.
Ruling: do not install/build/apply the CUDA or database artifacts; actual device/model/index/SQL grant readiness is explicitly unverified. Functional tests use explicit fake relevance config, never production thresholds.
Ruling: preserve the current lexical review workflow when no hybrid config is provided; once hybrid config is configured its existing prepare operation delegates to the hybrid builder. Serving and hybrid activation reject lexical manifests regardless.
Task 10: runbook written; final self-review and one full functional regression run pending.

Final review: self-review per user no-subagents constraint. Added RED -> GREEN regressions for snapshot metadata tampering, conditional rights with optional checks disabled, conflict preservation at hard limit, and revocation bypass through cached policy reads.
Ruling: policy reads are not cached by BusinessTools; a repeated call must revalidate current revocation state. Other read caches remain unchanged.
Ruling: source section body hash stays compatible with original BTC source references; document hash and canonical sorted whole-snapshot digest protect introductions, transformation and all applicability metadata.

Task 10: complete — runbook, CLI help, shell syntax, metadata JSON, Compose YAML, local links and whitespace checked. Full unit/mock regression executed ONCE: `.venv/bin/python -m pytest test eval_harness -q` -> 520 passed, 18 skipped, 1 dependency deprecation warning, 8.78s. No failures.

Final limits: no eval, benchmark, calibration, live model, dependency install, GPU inference, database migration/grant execution, Docker build or service restart. Real-device/DB integration readiness is not claimed. No git add/commit and no subagents. Existing unrelated architecture-review artifacts were left untouched.


Architecture follow-up (user requested): moved serving schemas/repositories/encoder/search/auth into `mcp_servers/mcp_knowledge/{schemas,repos,services,tools}`. Shared knowledge is grouped under `policy`, `events`, `services`, `repos`; stable CLI and worker command entrypoints retained. Imports and mock targets updated directly, without old-path compatibility modules. Runtime config loading moved out of executable server.py. Release reference validation and resource lifecycle belong to the knowledge service; handler delegates. Functional behavior and serialized contracts retained.
Architecture checks: three import/ownership/entrypoint-dependency tests failed before restructuring, then passed. Initial focused checks: 14 passed; dedicated MCP checks: 4 passed. Full functional regression for this change: 524 passed, 18 skipped, 1 unchanged dependency deprecation warning (8.47s). Run once; no eval/live model/benchmark. CLI/worker command paths, serialized contracts and business behavior preserved.
