# BTC submission implementation plan

> Execute inline using superpowers:executing-plans. The user delegated spec decisions and requires the current checkout.

**Goal:** Export a BTC source release with a runnable one-command eval, a cross-judging CLI, and full M1 demo Compose.

**Architecture:** Dedicated Compose deployment, existing business/runtime implementation, and a read-only source/replay boundary. A one-off setup initializes isolated storage. A source release is generated independently of services.

**Spec:** `docs/superpowers/specs/2026-11-22-btc-submission-design.md`.

- [x] Define and test the first-setup lifecycle in `ai-services/app/bootstrap/submission.py`, using current loader, schema, evaluator fingerprint, store, role and policy initialization. Verify fresh/repeated setup and rejection of a changed corpus.
- [x] Add `compose.submission.yml`, the submission build, locked AI/backend/ASR dependencies and per-container configuration. Verify isolated Compose projects, explicit setup, M1 demo, paired eval, single run and file ASR wiring.
- [x] Add a source archive writer and evidence inventory. Verify secret/cache exclusion, untracked source inclusion, checksums and extraction. Attach only evidence with known provenance.
- [x] Update the root README and submission runbook for the new package. Verify both eval CLIs, scorer version handling, ASR path and staging/cold-start steps against the code.
- [x] Produce the source archive and separate development audio archive, inspect the packaged bytes, and rehearse the available offline entrypoints. Audit acceptance criteria and document missing external artifacts.
- [x] Check Docker builds from the archive and rehearse clean demo and eval projects with a local provider fixture.
- [ ] Validate actual conversation metrics and ASR evidence with the authorized providers and final datasets.

No worktree, subagent, commit, distribution, paid inference, reset of an existing database, or unrelated logic work. Build and test in isolated infrastructure where available. Keep existing checkout changes intact.

## Verification ledger

- Unit-first regressions exposed absent setup, Compose and archive entrypoints. Reimporting a preexisting mismatched BTC source also failed before adding read-only comparison. The setup works against a separate PostgreSQL 16 cluster with the actual BTC files, preserves a committed turn on retry, and allows the backend role to read it. The policy provider was replaced for that check.
- 22 focused submission/startup/tokenizer tests passed with the temporary DB. 62 existing loader, eval, policy source and Compose tests passed. The actual MCP permission script granted memory access to turn, operation and boot state on that isolated cluster.
- Compose resolves both projects and distinct volumes with the installed Docker CLI. The daemon socket rejects this account, noninteractive sudo requires a password, and user namespaces are unavailable. Image tags resolved via registry manifests. Three locks installed into fresh Python 3.12 venvs. Backend rendered its three HTML routes and the ASR CPU imports succeeded. Offline eval preflight accepted 29 scenarios, 67 calls and 170 turns.
- 33 official pipeline, release and bootstrap policy tests passed. The extracted archive resolves Compose for all profiles and exposes the BTC cross-judging CLI. Demo seeding created two accounts on the temporary PostgreSQL cluster. Rootless Docker requires the host `newuidmap` helper, which is missing.
- In a native rehearsal from the extracted release, real PostgreSQL 16 and Qdrant 1.19.1 persisted the base index with a deterministic local embedding stub. The four authenticated MCP services reached the same DB, and the real demo gateway served the UI and seed-account login with a DB connection. The paired runner finished both arms on one public two-call scenario with a loopback-only model fixture, produced seven trace rows per arm, invoked the BTC scorer, and reached `proposals_ready`. This run verifies the execution path.
- The K1 console instructions now target the Compose project and configured review port. Two contract checks reproduced the missing Compose context and host-only command. The 40 focused Compose and knowledge workflow tests passed after the fix.
- The five real transcript sources contain 120 unique dialogues, 39 multi-session groups and 9 groups with both call and chat. Linked audio checks verified 22 WAVs totaling 1,173.131 seconds. The BTC speech validator found zero errors and 58 warnings. The dataset archive retains the original sources, audio, checksums and coverage readout.
- Historical K0/K1 pass comparability in the saved-artifact verifier and do not prove improvement. RQR regressed by 7.7 percentage points. The historical evaluation report and 12-slide deck label their measured revision and outstanding review. A timed M1 demo script is included in the runbook.
- The authorized Docker socket became available. AI, backend and ASR images built from the extracted ZIP. Two separate Compose projects initialized, the demo became healthy and one-scenario paired eval produced the official BTC table with loopback-only fixtures. ASR verified CPU int8. This exposed root-owned 0600 eval outputs. Compose now runs file-writing jobs under the operator UID/GID from the documented environment, and the images grant read access to their packaged source.
- The rebuilt archive passed paired eval and the single-config cross-judge in Docker. The operator could open the score, run manifest, and each seven-row trace directly. The ASR container wrote to the host results and model cache at the same UID. Demo WebSocket streaming, persistence and timeline passed. Stopping all demo services requires enabling the demo profile for `down`.
- The uploaded BTC source revision is supplied by the operator. The checkout input scorer, schema and corpus are externally mounted, and the historical overlay text was corrected. Live LLM/embedding, full Compose networking and the unavailable official delivery artifacts remain separate acceptance checks.
