# TeleSale Speech serving

CPU speech service for the KHOI machine. It serves Silero VAD, Gipformer 1.5 int8 ONNX via sherpa-onnx, KorvaTTS, and VieNeu v3 Turbo ONNX fp32. It is separate from the existing text chat agent and does not yet call it.

Public Swagger: <https://sudoapi.ktoxz.id.vn/docs> (no authentication). Full endpoint report: [docs/speech-api-report.md](../../docs/speech-api-report.md).

## Endpoints

- `GET /health`: model readiness and streaming capability.
- `POST /v1/speech/transcribe`: raw WAV body, 8–96 kHz mono/stereo, at most 30 seconds and 10 MiB. Returns transcript, VAD segments, and VAD/STT timings.
- `POST /v1/speech/synthesize`: JSON `{"text":"...","voice":"khanh_vy"}`. Returns WAV, with TTS timing in response headers.
- `POST /v1/speech/synthesize/sequence`: the same JSON; splits at each period or after 20 words, synthesizes each chunk separately, and returns all WAV chunks plus per-chunk timings in one response.
- `POST /v1/speech/synthesize/stream`: SSE stream. Sends `start`, each `segment` as soon as its WAV is ready, then `done` (or `error`). The browser plays the first segment immediately and queues later segments, with a minimum 200 ms pause between playback segments. The batch `/sequence` endpoint remains available for existing clients.
- `GET /v1/speech/vieneu/voices`: all available VieNeu preset voice labels and IDs.
- `POST /v1/speech/vieneu/synthesize`: JSON `{"text":"...","voice":"Trúc Ly"}`; returns one complete 48 kHz PCM WAV.
- `POST /v1/speech/vieneu/stream`: SSE with `start`, `segment_start`, `audio_chunk` (base64 PCM16 mono at 48 kHz), `segment_end`, and `done` or `error`. Accepts up to 8000 characters for a complete agent reply; splits at each period or after 20 words. The browser schedules frames as they arrive and inserts 200 ms between sentences.
- `GET /`: browser demo for microphone input and TTS playback.

The Gipformer ONNX model is loaded through `sherpa_onnx.OfflineRecognizer.from_transducer`, as in the model author's reference script. VAD can split incoming audio into short segments, but this does not make Gipformer streaming. A true incremental STT endpoint needs an online-compatible export and separate latency testing.

The service holds audio only in memory, binds to `127.0.0.1:18110`, limits input size and length, and allows at most 20 inference requests per minute per Cloudflare client IP. Cloudflare publishes `sudoapi.ktoxz.id.vn` and `telesale.ktoxz.id.vn` to the same origin. The latter hosts a speech-only demo, not the complete sales chat application.

## KHOI deployment

The separate Windows scheduled task `TeleSaleSpeech18110` runs as `pc\khoi` with limited privileges at user logon. It resumes after KHOI signs in following a reboot. `run-khoi.ps1` refuses to start if port 18110 is already occupied. The Python venv and model files are under `H:\TeleSaleSpeech`; source is under `C:\Users\KHOI\TeleSaleSpeech\serving`.

VieNeu runs in a second limited task, `TeleSaleVieNeu18111`, bound to loopback port 18111 with its own venv and model cache under `H:\TeleSaleVieNeu`. The main API proxies VieNeu requests to that sidecar, so no extra Cloudflare route is needed. `run-vieneu-khoi.ps1` refuses to start when port 18111 is occupied. The CPU uses fp32 because the i7-7820X lacks VNNI needed by VieNeu's int8 build. `materialize_vieneu_cache.py` converts the freshly downloaded Hugging Face snapshot symlinks into files in the isolated cache, avoiding ONNX Runtime's external-data path rejection without relaxing its path checks.

After changes, copy the changed source, then run `restart-khoi.ps1`; it checks the PID on port 18110 belongs to this service before stopping it. Inspect `Get-ScheduledTask -TaskName TeleSaleSpeech18110` and `http://127.0.0.1:18110/health`. `python -m speech.serving.check_public` runs TTS → VAD → STT through the public API; `python -m speech.serving.check_stream` measures the public time to first Korva WAV. `python -m speech.serving.check_vieneu https://sudoapi.ktoxz.id.vn/v1/speech/vieneu/stream` checks the first VieNeu PCM frame and completion. The demo references a versioned `/tts.js` URL because Cloudflare may cache static assets.

References: [Silero VAD](https://github.com/snakers4/silero-vad), [Gipformer reference ONNX inference](https://github.com/ggroup-ai-lab/gipformer/blob/main/infer_onnx.py), [sherpa-onnx VAD example](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/vad-with-non-streaming-asr.py), [KorvaTTS](https://github.com/dogenthq/KorvaTTS), [VieNeu SDK](https://docs.vieneu.io/docs/sdk/streaming/).

## Continuous microphone input (WebSocket)

`WS /v1/speech/listen` receives multiple speech turns on one connection. Use
`wss://sudoapi.ktoxz.id.vn/v1/speech/listen` after deploying this version;
this change does not deploy the endpoint. The speech service does not invoke
an agent or control playback. The backend forwards audio, consumes final
transcripts, invokes the agent and uses the existing TTS endpoints.

Input is **raw PCM signed 16-bit little-endian, mono, 16000 Hz**, sent as
binary messages without WAV headers. WebM/Opus is not decoded by this endpoint.
Resample/decode before sending. Recommended chunks: 20–100 ms (640–3200 bytes).
Message boundaries need not align with VAD frames or even sample boundaries;
the service buffers incomplete frames/bytes. Maximum message size is 32000
bytes. Send at capture speed rather than uploading a whole call at once.

Wait for `ready` before sending. Output is JSON text messages:

| Event | Fields in addition to `event`, `session_id` |
|---|---|
| `ready` | `audio: {encoding: "pcm_s16le", sample_rate: 16000, channels: 1}` |
| `speech_started` | `turn_id` |
| `speech_ended` | `turn_id`, `reason: "silence"` or `"max_duration"` |
| `transcript_final` | `turn_id`, `text` |
| `error` | `code`, `message`, `fatal`, and `turn_id` when applicable |

IDs are scoped to a connection: a fresh UUID `session_id`, then `turn-1`,
`turn-2`, etc. A turn's events occur in started → ended → final/error order.
Events from different turns may interleave. Dispatch the agent only on a
nonempty `transcript_final`, not on `speech_ended`. A final transcript may
have empty `text`; speech shorter than 200 ms is discarded without STT.
There are no partial transcripts.

The per-connection Silero VAD uses 700 ms minimum silence and 200 ms minimum
speech. These are initial settings, not measured quality guarantees. Turns
are capped at 30 seconds; a VAD frame crossing the cap is split and its tail
is retained for continuation. Gipformer remains offline per completed turn.
Reception continues during STT. Each connection has at most two waiting STT
turns, plus one being processed/waiting for the shared inference lock.
REST VAD settings and existing REST/SSE response formats are unchanged.

Errors:

| Code | Behavior |
|---|---|
| `invalid_message` | Text/control application message unsupported; fatal, close 1003 |
| `audio_too_large` | Binary message exceeds 32000 bytes; fatal, close 1009 |
| `overloaded` | STT waiting queue is full; fatal, close 1013 |
| `service_unavailable` | Models not ready; fatal, close 1013, no `ready` |
| `transcription_failed` | Error for one turn; nonfatal, session continues |

The endpoint accepts only binary application messages, without a start/stop
JSON command. Ordinary WebSocket ping/pong frames are handled by the transport.
PCM has no header to validate its actual sample rate/codec; sending another
encoding may produce incorrect transcripts rather than a detectable error.

Close the WebSocket to end the session. Unfinished audio, partial bytes/frames
and queued work are discarded. Native inference already running is allowed
to finish under the shared lock; its result is discarded. Audio is never
persisted. There is no flush-on-close, reconnect/resume or transcript replay.
The demo assumes alternating customer/agent speech; interruption handling,
echo cancellation and playback controls are outside this endpoint's scope.

WebSockets do not appear as REST paths in `/openapi.json`; use this contract.
The existing HTTP rate limiter is not a WebSocket session limiter. The endpoint
uses the service's existing public demo/no-auth deployment model.

### Client integration example

Install `websockets` and supply a raw PCM file in the format above. Receive
events concurrently with sending audio; leave the socket open after upload
until the final result arrives. The trailing silence lets VAD close the turn.
This is a manual integration example, not an automated live model test:

```python
import asyncio
import json
from pathlib import Path
import websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:18110/v1/speech/listen") as ws:
        print(json.loads(await ws.recv()))  # ready

        async def send_audio():
            audio = Path("customer.pcm").read_bytes() + bytes(32000)
            for offset in range(0, len(audio), 3200):
                await ws.send(audio[offset:offset + 3200])
                await asyncio.sleep(0.1)

        async def receive_events():
            async for message in ws:
                event = json.loads(message)
                print(event)
                if event["event"] == "transcript_final":
                    await ws.close()
                    return
                if event["event"] == "error" and event["fatal"]:
                    return

        await asyncio.gather(send_audio(), receive_events())

asyncio.run(main())
```

For a real microphone, keep both loops running across turns; closing after
one transcript above only makes the file example finite. A silent file may
produce no final event; stop the example manually in that case.

Existing streaming TTS choices: `POST /v1/speech/vieneu/stream` (default voice
`Trúc Ly`) and `POST /v1/speech/synthesize/stream` (default `khanh_vy`). A TTS
stream completing is not confirmation that playback has finished.

Offline verification (fake VAD/recognizer; no model download or public calls):

```bash
python -m unittest speech.serving.test_models speech.serving.test_listen speech.serving.test_text_segments -v
```
