# Voice streaming and interruption implementation

Goal: upgrade the existing FastAPI/WebSocket voice path, referencing LiveKit
Agents without introducing its runtime. Preserve the speech service, harness,
verified-only speech, identity binding and business-operation idempotency.

References inspected:
- https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/speech_handle.py
- https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/audio_recognition.py
- https://docs.livekit.io/agents/logic/turns/

Implement the lifecycle concepts in project-native code; do not vendor source.

1. Keep one STT connection receiving audio while processing and speaking.
   Bind speech IDs to backend turn IDs; consume each final once. Serialize
   harness requests, queue new recognized turns and suppress obsolete output.
   Interrupt audio immediately on speech_started, cancel synthesis only, clear
   browser playback and reject stale audio/acknowledgements.
   Verify with offline race, duplicate-final and cancellation tests.
2. Introduce voice delivery receipts. Text chat keeps immediate persistence;
   voice history is committed after playback using completed sentence prefixes.
   Preserve original customer speech and successful tool observations, even for
   a response the customer did not hear. Do not replay tools during receipt
   handling. Serialize receipt before the next harness turn. Bound receipt waits
   and finalize conservatively on disconnect/missing receipt.
   Verify identity checks, receipt idempotency, missing receipts and partial
   playback with fake memory and tools.
3. Update browser capture/playback for full duplex, audio-clock sentence
   acknowledgements and interruption; reset scheduler and reject obsolete chunks.
   Verify with deterministic audio-clock doubles in Chrome and the existing
   offline browser harness (no Node runtime required).
4. Update voice protocol docs; run focused backend, harness and browser checks.

Constraints: current checkout; no subagents, worktrees, live model calls or
benchmarks. Preserve unrelated dirty files. Review and test changes locally.

Progress:
- Inspected current transport, browser scheduler, speech events and persistence.
- Decision: cancel audio generation/playout, never cancel/retry a business request
  merely because the caller speaks. Completed sentences are the conservative
  delivery unit; absent word timing, do not invent a partially heard sentence.
- Steps 1–4 implemented and reviewed locally. The persistent STT connection,
  turn-scoped interruption, duplicate/failed-final rejection, serialization,
  playback markers, deferred voice persistence and browser cancellation are in
  the current checkout. No runtime dependency on LiveKit was introduced.
- Backend focused verification: 59 passed (voice protocol, speech adapter,
  call lifecycle, real loopback WebSocket, memory polling, Chrome/AudioWorklet,
  interrupted playout, stale audio rejection and deterministic audio clock).
- AI-service focused verification: 45 passed (voice receipts, authenticated API,
  ordinary text chat, memory status, real graph with fake model/memory and session
  preparation). All inference is fake/offline; no live evaluations were run.
- Limits documented in the voice protocol: sentence-level conservative receipts,
  existing process-local session ownership, and real-device acoustic testing not
  established by offline tests. Backend waits at most 5 seconds for interruption
  receipts; the harness conservatively expires abandoned receipts after 300 seconds.
