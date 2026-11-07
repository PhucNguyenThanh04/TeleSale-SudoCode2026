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
`app.voice_main` only exposes the voice WebSocket and FastAPI documentation; it
does not serve or modify the frontend. WebSocket routes do not appear in OpenAPI.

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
| `audio` | `turn_id`, `index`, `segment_index`, `format`, `audio_base64` | VieNeu PCM audio chunk |
| `audio_segment_end` | `turn_id`, `segment_index`, `pause_ms` | Insert a 200 ms pause after this sentence |
| `audio_complete` | `turn_id` | All audio was sent, not necessarily played |
| `error` | `stage`, `code`, `message`, `fatal`, `turn_id` | Failure, with a nullable turn ID |

`turn_id` is a backend UUID unique per speech turn in this call; it is not the
speech service's repeating `turn-1`. `index` orders all audio chunks within the
reply, starting at zero. `segment_index` groups chunks by TTS sentence.

Example audio:

```json
{"event":"audio","turn_id":"<uuid>","index":0,"segment_index":0,"format":{"encoding":"pcm_s16le","sample_rate":48000,"channels":1},"audio_base64":"..."}
```

Decode base64 as **raw PCM**, not a WAV file. Queue chunks in order and schedule
the indicated sentence pauses. The browser is responsible for audio playback.

After playback of all chunks finishes, and after receiving `audio_complete`, send:

```json
{"event":"playback_finished","turn_id":"<uuid of current reply>"}
```

Backend opens a fresh speech connection, waits for speech readiness, then sends
`state: listening`. Audio captured during `processing` / `speaking` is discarded;
the browser should pause forwarding audio until `listening` to avoid echo.
Early, duplicate or wrong-turn playback acknowledgements produce a nonfatal
`unexpected_playback` error and do not open listening.

The first nonempty transcript calls `/v1/chat/turns` with a new `client_msg_id`,
`channel`, `channel_identity`, `on`, the unchanged STT `text`, and
`input_mode: asr_transcript`, without a session ID. Backend retains the returned
harness `session_id` in memory and sends it on subsequent turns. Call Brief is
forwarded when returned; there is no pre-call harness request or synthetic greeting.
The gateway does not call an eval runner, seed conversation facts or create memory.

At the first accepted transcript, backend closes the speech connection, discarding
unfinished/queued audio. This prevents delayed transcripts from becoming new turns
when playback completes. Reopening speech changes only the speech connection ID;
the harness session stays unchanged. Empty transcripts do not call the harness.
Very short speech may emit started/ended without a final transcript, as documented
by the speech service.

## End and failures

Send `{"event":"end"}` or close the socket to finish. Backend closes upstream
resources and cancels local in-flight work. When possible it sends `state: closed`
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
| TTS HTTP/SSE failure, including stream ending without `done` | Nonfatal `tts_failed`; keep agent text |

On `tts_failed`, stop and discard queued playback for that reply, then send
`playback_finished` for that turn to resume. There is no `audio_complete` for a
failed synthesis. An incomplete TTS stream must not be treated as successful.

Errors contain stable codes rather than upstream payloads or customer data. Codes
include `start_required`, `start_timeout`, `invalid_command`, `already_started`,
`unexpected_playback`, `audio_too_large`, `speech_unavailable`,
`speech_disconnected`, `speech_failed`, speech-service error codes,
`harness_failed`, and `tts_failed`.
When a speech-service error identifies a previously announced speech turn, its
`turn_id` is mapped to the same backend UUID as `speech_started`, allowing the
frontend to mark that turn as failed. Connection-level errors may have no turn ID.

Disconnecting cannot guarantee cancellation of a business action already executing
inside the harness. No reconnect/resume, retries, cross-connection idempotency,
barge-in, filler speech or partial STT results in this version. If the browser never
acknowledges playback, the call remains waiting until it sends `end` or disconnects.

## Offline verification

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/test/test_voice_contract.py backend/test/test_voice_speech.py backend/test/test_voice_flow.py backend/test/test_voice_websocket.py backend/test/test_voice_transport.py -q -o asyncio_default_fixture_loop_scope=function
```

Tests use fake speech and harness transports, including a real loopback WebSocket
server with synthetic transcripts, fragmented SSE, multiple turns, playback gating,
connection cleanup and failure paths. They do not call
models, speech inference, databases or the public deployment. Full browser/live
integration requires the frontend to implement this contract and services to be
deployed; it is not established by these tests.
