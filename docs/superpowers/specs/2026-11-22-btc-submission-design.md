# BTC submission packaging

The submission gives BTC a GitHub repository URL and a pinned Git ref. The submitted commit contains the Compose stack, build recipes and instructions that reproduce both BTC evaluation interfaces after cloning. M1 targets Linux, Python 3.12 images, chat demo and local file ASR. The packaging uses the existing agent, database schema, loader, scorer and ASR CLI. Final scores, human assessment and organizer-only fixtures remain subject to the files and permissions actually available.

## Runtime and evaluation

- Supply the BTC package via a read-only mount. Mount scenario and audio inputs separately. An explicit first setup imports BTC source, initializes operational tables, roles, LangGraph and the base policy. Policy indexing requires operator opt-in. Reusing setup on the same release preserves runtime data, and a different source requires a fresh dedicated volume or a separate migration.
- Use one Compose file for the complete M1 chat demo and the eval runner. Different project names isolate the PostgreSQL, Redis, Qdrant, and application networks. Only the demo gateway publishes a port. Compose uses service DNS rather than host loopback for service calls.
- Expose a paired one-command eval after setup and startup. Use the existing paired runner to generate Full/baseline traces and a BTC score table. Keep the separately runnable `run_eval.py` command and pass through `--scenarios`, `--config` and `--out`. The grader supplies the BTC scorer with the matching release and hidden scenarios.
- Provide a CPU ASR invocation with file inputs and explicit model assets. Paired evaluation accepts stored ASR evidence for its table. Realtime TTS and GPU speech are outside the M1 package's supported runtime.

## Source and evidence

- A versioned local rehearsal archive uses current tracked and non-ignored source, including untracked delivery files. Its manifest and SHA-256 record which bytes were tested. The GitHub handoff requires those delivery files to be committed at the ref shared with BTC. Container build contexts use explicit copied inputs. Provider and demo credentials are configured outside images and Git.
- BTC inputs are either supplied by the reviewer or transferred as their unmodified official release. Team artifacts have explicit names, provenance and availability. Existing audio and reports are labeled with their actual coverage. Official scores, video, slide and organizer ASR audio are only represented as available when an actual artifact is present and attributable.
- Verification covers archive extraction, Compose resolution, isolated storage, startup prerequisites, clean initialization plus idempotent retry, scenario and ASR CLI, and exclusion of secrets. Run focused offline checks. Docker runtime launch or paid model calls require applicable machine access and authorization. Report any verification gaps as such.
