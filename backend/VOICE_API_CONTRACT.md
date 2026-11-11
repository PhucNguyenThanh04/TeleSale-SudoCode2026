# Voice demo gateway

Backend-only transport orchestration. The frontend captures/plays audio; the
speech service runs VAD/STT and TTS; the harness owns customer identification,
conversation state, memory, tools and Call Brief. No login, database writes,
audio persistence, transcript rewriting or business decisions in this gateway.

## Run

From the repository root, with the backend dependencies installed:

```bash
backend/.venv/bin/python -m uvicorn app.voice_main:app --app-dir backend --host 127.0.0.1 --port 8000
```

This dedicated entrypoint does not start PostgreSQL/Redis or import the legacy
operator routes. The existing `app.main` imports API modules absent from the
checkout at implementation time; it is not the entrypoint for this demo.
`app.voice_main` serves the call website at `/`, frontend assets at `/assets/`,
the voice WebSocket and FastAPI documentation. Open http://127.0.0.1:8000 to call.
The backend Dockerfile also starts this entrypoint. WebSocket routes do not appear
in OpenAPI. See [frontend instructions](../frontend/README.md) for microphone and
browser requirements.

Settings come from `backend/.env` and environment variables:

| Setting | Default | Purpose |
|---|---|---|
| `AI_SERVICE_URL` | `http://127.0.0.1:8001` | Harness HTTP origin |
| `AI_INTERNAL_TOKEN` | unset | Match the harness token; never sent to the browser |
| `AI_SERVICE_TIMEOUT_SECONDS` | `120` | Harness HTTP timeout |
| `SPEECH_HTTP_URL` | `http://127.0.0.1:18110` | Speech HTTP origin |
| `SPEECH_LISTEN_URL` | `ws://127.0.0.1:18110/v1/speech/listen` | Continuous VAD/STT WebSocket |
| `SPEECH_VOICE` | `Trúc Ly` | VieNeu voice |
| `SPEECH_CONNECT_TIMEOUT_SECONDS` | `10` | Speech connection/ready timeout |
| `SPEECH_TIMEOUT_SECONDS` | `120` | TTS HTTP timeout, including read inactivity |
| `VOICE_START_TIMEOUT_SECONDS` | `10` | Time allowed for the browser's first command |

Use `https://` / `wss://` speech origins when connecting to the public deployment.
If `.env` sets `AI_SERVICE_TIMEOUT_SECONDS=30`, that overrides the voice default.
No model calls are performed at application startup. Services must already be
running and reachable when a call is made. Harness startup currently requires its
internal token, so configure the matching backend token in that deployment.

## Browser connection and input

Connect to `WS /api/calls/stream` (`wss://` when the gateway is behind TLS).
One browser connection represents one call. First send JSON:

```json
{"event":"start","channel":"zalo_oa","channel_identity":"zalo_dung99","on":"2026-10-15"}
```

`channel`: `hotline`, `chat_fanpage`, `zalo_oa`, `web_chat` or `other`.
`channel_identity`: nonempty string, resolved by the harness, not the gateway.
`on`: scenario date, fixed throughout this call. Unknown fields are rejected.

Backend waits for speech readiness before sending:

```json
{"event":"ready","audio":{"encoding":"pcm_s16le","sample_rate":16000,"channels":1}}
{"event":"state","state":"listening"}
```

Only then send **binary raw PCM16 little-endian, mono, 16 kHz** chunks, ideally
20–100 ms (640–3200 bytes), maximum 32000 bytes per message. No WAV headers or
WebM/Opus. The browser must provide this encoding; the backend does no resampling,
decoding or VAD. Wire bytes cannot validate the actual codec/sample rate.

## Events and turn flow

JSON events are sent as WebSocket text messages:

| Event | Fields | Meaning |
|---|---|---|
| `state` | `state` | `listening`, `processing`, `speaking` or `closed` |
| `speech_started` | `turn_id` | Speech detected |
| `speech_ended` | `turn_id`, `reason` | Speech segment ended; **do not call agent yet** |
| `transcript_final` | `turn_id`, `text` | Nonempty final STT result; agent processing begins |
| `agent_reply` | `turn_id`, `session_id`, `agent_text`, `call_brief`, `needs_handoff`, `handoff_ticket_id` | Harness response |
| `memory_update` | `turn_id`, `client_msg_id`, `memory_update`, `tracking_finished` | Asynchronous memory result for the original reply |
| `audio` | `turn_id`, `index`, `segment_index`, `format`, `audio_base64` | VieNeu PCM audio chunk |
| `audio_segment_end` | `turn_id`, `segment_index`, `pause_ms` | Insert a 200 ms pause after this sentence |
| `audio_mark` | `turn_id`, `played_chars` | Confirmable end offset of an original verified sentence |
| `playback_interrupt` | `turn_id` | Stop and discard this reply's queued audio immediately |
| `audio_complete` | `turn_id` | All audio was sent, not necessarily played |
| `error` | `stage`, `code`, `message`, `fatal`, `turn_id` | Failure, with a nullable turn ID |

`turn_id` is a backend UUID unique per speech turn in this call; it is not the
speech service's connection-local `turn-1`. `index` orders all audio chunks within the
reply, starting at zero. `segment_index` groups chunks by TTS sentence.

Example audio:

```json
{"event":"audio","turn_id":"<uuid>","index":0,"segment_index":0,"format":{"encoding":"pcm_s16le","sample_rate":48000,"channels":1},"audio_base64":"..."}
```

Decode base64 as **raw PCM**, not a WAV file. Queue chunks in order and schedule
the indicated sentence pauses. The browser is responsible for audio playback.

After playback of all chunks finishes, and after receiving `audio_complete`, send:

```json
{"event":"playback_finished","turn_id":"<uuid of current reply>","played_chars":42}
```

The microphone remains active during `listening`, `processing` and `speaking`.
One speech connection stays open throughout the call. Enable browser echo
cancellation and noise suppression, as the bundled frontend does.

For each `audio_mark`, wait until the audio clock reaches that point in the
playback queue, then send `{"event":"playback_progress","turn_id":"...","played_chars":42}`.
Use the offset issued by the server, not a client-computed text length. The offset
counts original verified text, even when TTS expands numbers into spoken words.
Only completed original sentences are confirmed; a partially played sentence is
conservatively omitted because word-level timestamps are unavailable.

On `playback_interrupt`, stop all playing/scheduled sources, clear queued audio
and pending completion callbacks, then send
`{"event":"playback_stopped","turn_id":"...","played_chars":42}` with the last
completed mark (zero if none). Ignore subsequent audio, marks or completion for
that interrupted turn. On the next reply, reset the playback schedule and indexes.

Early, duplicate, wrong-turn, decreasing or unissued playback offsets produce
nonfatal `unexpected_playback`. A finished acknowledgement is accepted only after
`audio_complete` (or a reported synthesis failure). Old clients omitting
`played_chars` conservatively confirm zero characters.

Input `speech_started` interrupts output immediately. A nonempty final transcript
queues a new harness turn. Already-issued harness requests run once to completion;
only synthesis/playout are canceled. Requests are serialized, and the previous
turn's playback receipt is persisted before the next request begins. Replies from
superseded generations never start synthesis. Duplicate finals and finals for
failed STT turns are ignored. Up to four recognized turns may wait behind the
active request; overflow closes with `overloaded` rather than silently losing input.

At `start`, the backend creates a session UUID and calls authenticated
`POST /v1/chat/sessions/prepare` with that ID, `channel`, `channel_identity` and
`on`, concurrently with speech setup/listening. Preparation does not delay the
`ready` event. The first transcript waits for preparation if necessary, then calls
`/v1/chat/turns` with the same session ID, a new `client_msg_id`, unchanged STT
`text`, `input_mode: asr_transcript` and `delivery_mode: voice`. Subsequent turns retain that session.
The prepare endpoint resolves identity and builds context/Call Brief without
inference, synthetic greetings, committed turns or distillation jobs. It requires
`X-AI-Internal-Token`; configure the same token for gateway and AI service.

`agent_reply` also forwards optional `memory_update` metadata. `turn_saved`
confirms the conversation commit; voice replies initially have `turn_saved: false`.
After playback, authenticated `POST /v1/chat/turns/playback` commits the original
customer text, the confirmed assistant prefix and successful tool observations.
It does not generate a new reply or repeat business tools. `pending` does not
claim that long-term facts have been extracted. After this commit the gateway polls the internal `/v1/chat/turns/memory`
endpoint every second while pending, for up to 60 seconds, independently of
audio and listening. Only completed, accepted fact writes are displayed. The
result stays bound to its original `turn_id` even when a later reply has begun.
Failures produce an unavailable memory result without failing the voice call.
On tracking timeout, status stays pending with `tracking_finished: true`.
Disconnect cancels polling; the browser does not receive the internal token or
a public arbitrary-session memory lookup route. Clients without metadata remain
compatible. The metadata never becomes TTS input or a new conversation turn.

Prepared commercial reads are consumed once within 30 seconds for the same
customer/date. Each real turn still reads memory to enforce ownership and erasure
barriers and see current history. The first real-turn Call Brief is rebuilt for
the actual utterance and forwarded in `agent_reply`; the preliminary brief from
preparation is not sent to the browser or spoken. A changed product, quantity or
delivery condition still requires compatible evidence. The gateway does not call
an eval runner, seed conversation facts or create memory.

Empty transcripts do not call the harness. Very short speech may emit
started/ended without a final transcript. An interruption can therefore stop
output without creating a new business turn.

## End and failures

Send `{"event":"end"}` or close the socket to finish. Backend closes upstream
resources and cancels local capture/synthesis/polling. An already-issued harness
request is allowed to finish once, with confirmed playback persisted conservatively;
preparation is cancellable before a business request has been issued. When possible it sends `state: closed`
before closing the browser socket. It does not call a nonexistent harness end API
or claim to have finalized/summarized the harness session. Starting another browser
connection starts another call; harness resolves the returning customer again.

| Failure | Behavior |
|---|---|
| No valid initial `start`, or start timeout | Fatal protocol error; close |
| Invalid command after start | Nonfatal protocol error |
| Audio message over 32000 bytes | Fatal protocol error; close |
| Nonfatal speech `transcription_failed` | Report error; continue listening |
| Speech unavailable/disconnected, malformed event or fatal speech error | Fatal STT error; close |
| Harness HTTP error, timeout or invalid response | Fatal harness error; close; no automatic retry |
| Preparation HTTP error, timeout or changed session ID | Fatal `preparation_failed` harness error; close |
| TTS HTTP/SSE failure, including stream ending without `done` | Nonfatal `tts_failed`; keep agent text |

On `tts_failed`, `playback_interrupt` requests clearing queued playback. Reply with
`playback_stopped` using the last completed mark. There is no `audio_complete` for a
failed synthesis. An incomplete TTS stream must not be treated as successful.

Errors contain stable codes rather than upstream payloads or customer data. Codes
include `start_required`, `start_timeout`, `invalid_command`, `already_started`,
`unexpected_playback`, `audio_too_large`, `speech_unavailable`,
`speech_disconnected`, `speech_failed`, speech-service error codes,
`preparation_failed`, `harness_failed`, `playback_failed`, and `tts_failed`.
A failed playback commit closes the call without retrying business execution.
When a speech-service error identifies a previously announced speech turn, its
`turn_id` is mapped to the same backend UUID as `speech_started`, allowing the
frontend to mark that turn as failed. Connection-level errors may have no turn ID.

Synthesis and post-synthesis playback waits are each bounded to 120 seconds.
After interruption, the stop-receipt wait is bounded to five seconds. Missing
receipts use the last confirmed mark, never all generated text. The harness has
a 300-second fallback for abandoned voice receipts and finalizes pending voice
turns conservatively before a following turn or during orderly shutdown.

Pending voice state and receipts use the existing process-local harness session
binding/cache; route a session to the same AI-service process. They do not add
cross-process recovery or crash durability. No automatic reconnect/resume,
business retries, filler speech, semantic interruption classifier or partial STT
results are introduced. Validate echo behavior on target microphones/speakers;
offline tests cannot establish real acoustic quality.

The design references [LiveKit speech lifecycle](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/speech_handle.py)
and [turn handling](https://docs.livekit.io/agents/logic/turns/); LiveKit is not a
runtime dependency and no LiveKit source is vendored.

## Offline verification

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/test/test_voice_contract.py backend/test/test_voice_speech.py backend/test/test_voice_flow.py backend/test/test_voice_websocket.py backend/test/test_voice_transport.py backend/test/test_voice_interruptions.py backend/test/test_voice_memory.py -q -o asyncio_default_fixture_loop_scope=function
```

Tests use fake speech and harness transports, including a real loopback WebSocket
server with synthetic transcripts, fragmented SSE, multiple turns, playback gating,
connection cleanup and failure paths. They do not call
models, speech inference, databases or the public deployment. Browser integration is covered separately by `test_voice_browser.py` with real
Chrome and AudioWorklet against fake speech/agent transports; see the frontend
README. Live model/service integration is not established by these offline tests.

## Product state in the returning Call Brief

`products_advised` retains historical discussed products. Optional nullable
`recommended_sku` identifies the provenance-backed latest agent recommendation;
`selected_sku` identifies the customer's explicit selection and is not purchase
consent. The browser labels these separately as “Đã trao đổi”, “Đề xuất gần nhất”
and “Khách đã chọn” (or “Chưa xác nhận”). Legacy briefs without these fields still
render normally.

The brief reuses the consultation snapshot already computed during context
loading. A later recommendation remains visible even when the independent
`product_advised` fact projection has not caught up. Historical X prices/promos
are never copied onto Y, and generated-but-unplayed voice text cannot create a
new recommendation in committed history. This reconciliation adds no memory
read, model invocation or refresh call; it does not rewrite stored facts.
