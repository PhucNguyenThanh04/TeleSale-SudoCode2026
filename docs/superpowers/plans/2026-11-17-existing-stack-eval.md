# Eval on existing services with equal memory reset

Goal: ordinary No-memory/Full evaluation uses the running services and the same
runtime reset before each configuration. Keep knowledge for the separate Full K1 run.

1. Route `run_system.py eval` directly to the paired runner, without Docker,
   bootstrap, server processes, a new boot ID or the managed-demo lock.
   Verify the public command also works while a demo owns that lock, forwards
   expected DB/arguments and preserves configuration/boot/release pins.
2. Keep the existing shared reset lifecycle; test reset before each configuration,
   across No memory, Full K0 and Full K1, with memory retained between calls.
   Since workers remain running, keep their internal job sequence monotonic
   across resets so an old worker claim cannot match a newly created job ID.
   Read/restore that sequence under runtime table locks; business IDs still reset.
3. Keep detection after the normal pair and a separate one-Full follow-up file.
   Update instructions to use the running frontend/services without fresh startup.
4. Run focused offline launcher/reset/pair/follow-up/BTC CLI checks. No live
   evaluation, Docker operation, schema reset, DB mutation, subagent or worktree.

The existing reset clears runtime conversation/memory and mutable business state
for comparable scoring; it retains BTC, knowledge, demo accounts and migration metadata.
Do not change demo bootstrap or add infrastructure features.

Completed 2026-11-17: 105 focused checks passed, 2 PostgreSQL checks skipped.
The follow-up command also preserves the original release pin (unset/empty/explicit)
instead of forcing an empty value after changing the ordinary eval dispatch.
Requirement audit and commands: [evidence](../../existing-stack-eval-20261117.md).
