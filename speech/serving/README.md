# TeleSale Speech serving

Speech service with GPU ASR by default. It serves Silero VAD, Gipformer 1.5 FP32 ONNX on CUDA via sherpa-onnx, KorvaTTS, and VieNeu v3 Turbo PyTorch/CUDA. VAD and Korva use CUDA execution providers; VieNeu uses PyTorch/CUDA (including its audio codec). Explicit CPU ASR uses the existing int8 files. It is separate from the existing text chat agent and does not yet call it.

Public Swagger: <https://sudoapi.ktoxz.id.vn/docs> (no authentication). Full endpoint report: [docs/speech-api-report.md](../../docs/speech-api-report.md).

## Layout and local startup

```text
speech/
├── text/tts.py              shared TTS text preparation and respell overrides
├── lexicon.py, lexicon.json pronunciation dictionary (also used by offline ASR)
├── vi_numbers.py            shared number/unit/date/phone reading rules
└── serving/
    ├── app.py              public HTTP/WS API and VieNeu proxy
    ├── models.py           Gipformer/Silero and Korva model boundaries
    ├── vieneu_sidecar.py   isolated VieNeu WAV/PCM inference
    ├── listen.py           continuous VAD/STT session
    ├── text_segments.py    prepared text → segments of at most 20 words
    ├── static/             browser demo HTML and JS
    ├── tests/              offline contracts and browser playback queue test
    ├── tools/              explicit preload, smoke and remote API checks
    └── deploy/windows/     KHOI scheduled-task scripts
```

From the repository root, with the existing serving environment installed:

```bash
bash scripts/serve-speech.sh
```

ASGI entrypoints remain `speech.serving.app:app` (18110) and
`speech.serving.vieneu_sidecar:app` (18111). Public routes and audio formats are
unchanged; `/` and `/tts.js` now read files from `static/`.

## CUDA ASR/VAD/TTS and startup warmup

The default is `SPEECH_ASR_PROVIDER=cuda`. On this Linux x86_64 / Python 3.12
machine, use the CUDA 13 / cuDNN 9 wheel (the system already has these libraries):

```bash
uv pip install --python .venv-speech-serving/bin/python -r speech/serving/requirements-cuda13.txt
# SDK dependencies pull in the CPU `onnxruntime` distribution. Replace it:
uv pip uninstall --python .venv-speech-serving/bin/python onnxruntime
uv pip install --python .venv-speech-serving/bin/python --no-deps --reinstall onnxruntime-gpu==1.28.0
bash scripts/serve-speech.sh
```

Do not install CPU `onnxruntime` and `onnxruntime-gpu` side by side: both write
the same Python module. Korva/VieNeu metadata still names `onnxruntime`, so a
package metadata checker may report that dependency missing after replacement;
the imported `onnxruntime` module is provided by `onnxruntime-gpu`. Reapply this
replacement if SDK dependency installation reinstalls the CPU package.
The CUDA 13 Python EP is pinned to the ORT 1.28 API generation used by sherpa;
changing it independently can cause native provider-library conflicts.

The existing `requirements-local.lock.txt` describes the older CPU environment;
apply the CUDA requirements after installing that lock. Do not replace the GPU
wheel with the regular CPU-only PyPI wheel. The Python `onnxruntime` package used
by TTS is separate from the ONNX Runtime bundled in sherpa-onnx: changing only
`onnxruntime-gpu` does not switch sherpa ASR to CUDA. See the
[official GPU installation instructions](https://k2-fsa.github.io/sherpa/onnx/python/install.html)
for other platforms/CUDA versions.

CUDA ASR uses `encoder.onnx`, `decoder.onnx`, `joiner.onnx` and `tokens.txt` from
the same Gipformer repository. Missing files download once into the model cache;
CPU/int8 files remain available. Select a GPU with `CUDA_VISIBLE_DEVICES` before
starting the process. A CPU-only sherpa wheel is rejected when CUDA is selected.
To explicitly use a machine without a GPU (including the legacy KHOI deployment):

```bash
SPEECH_ASR_PROVIDER=cpu SPEECH_VAD_PROVIDER=cpu SPEECH_TTS_PROVIDER=cpu bash scripts/serve-speech.sh
```

Model initialization performs exactly **3 ASR warmup decodes** on synthetic
one-second, mono 16 kHz silence, bypassing VAD so inference really runs. Each
completed run is logged as `ASR warmup 1/3`, `2/3`, `3/3`. Model publication and
`Application startup complete` happen only after all three succeed. An inference
failure aborts startup. No audio/transcript is persisted and no agent is called.
`/health` reports `stt_provider` and `stt_warmup_runs`; a successful startup has
`stt_warmup_runs: 3`. These warmups check startup, not accuracy or latency gains.

### VAD and TTS warmups

`SPEECH_VAD_PROVIDER` defaults to the ASR provider (`cuda` by default).
`SPEECH_TTS_PROVIDER` defaults to `cuda` for both Korva and VieNeu. Main-service
initialization performs 3 VAD passes on synthetic audio and 3 Korva syntheses
of `Xin chào.` in addition to the existing 3 ASR decodes. WebSocket VAD copies
the CUDA setting into each per-connection detector; recurrent state stays local
to that connection. Korva checks all four ONNX sessions for CUDA rather than
silently accepting CPU fallback.

The VieNeu sidecar uses `backend=pytorch`, `device=cuda`, `dtype=auto` for both
the backbone and MOSS codec. On the RTX 3050 this selects bfloat16 for the
backbone. The batch/stream capacity is 1 because calls are already serialized
by the existing model lock and the GPU has 4 GB. Startup consumes **3 complete
PCM streams** for `Xin chào.` so the actual streaming path and codec run.
No model is published until all three return nonempty audio. Preset loading
and warmup do not create or persist voice clones/audio files.

Main `/health` reports `vad_provider`, `vad_warmup_runs`, `tts_provider` and
`tts_warmup_runs` alongside ASR fields. The sidecar `/health` reports its own
`tts_provider` and `tts_warmup_runs`. Successful initialization reports three
completed warmups for each component. These are readiness checks, not latency
or quality measurements. The CPU opt-out above remains explicit.

## TTS text pipeline

All serving TTS paths use shared `speech.text.tts.prepare_tts_text`:

```text
agent text → NFC/whitespace cleanup → numbers/units/dates/phone reading
           → known dictionary pronunciation → remaining acronyms
           → split prepared text (sequence/stream) → Korva or VieNeu
```

For example, `AirPure giá 5.200.000đ. COD nhé!` becomes
`e pia giá năm triệu hai trăm nghìn đồng. cê ô đê nhé!`.
A price written as `5200000 đồng` is read as money rather than an identifier;
phone numbers still use digit-by-digit reading. Splitting happens **after**
expansion, so numeric text cannot silently exceed the 20-word segment limit.
Korva prepares text at its model boundary; VieNeu prepares both WAV input and
stream segments. The public API only proxies VieNeu text, avoiding a second
independent normalization policy. Audio is still kept in memory.

This reuses the offline pronunciation/number helpers, but does **not** use
`normalize_text(...).spoken` verbatim: that output lowercases and removes
punctuation for WER scoring. TTS keeps punctuation and does not run fuzzy ASR
correction or ITN against an agent answer. `tts.respell` remains importable for
existing offline/manual synthesis; its implementation now lives in `text/tts.py`.
Offline dataset generation, cache keys and frozen ASR scoring rules are unchanged.
VieNeu's built-in English handling remains available; edge/MMS pronunciation
maps are not forced onto it. Existing dictionary entries include unverified
pronunciations; offline tests check text/transport behavior, not acoustic quality.

## STT hậu xử lý dùng chung với B2

Cả `POST /v1/speech/transcribe` và `WS /v1/speech/listen` đi qua cùng
`Models.transcribe_segment`:

```text
Silero VAD → Gipformer raw text → asr.clean_hypothesis
           → normalize.normalize_text → written text → backend/agent
```

Ví dụ `anh chốt kê ô đê đơn bốn triệu rưỡi nha` trả về
`anh chốt COD đơn 4,5 triệu nha`. Phần dùng chung lọc mẫu câu ảo giác đã biết,
rút gọn lặp n-gram, chuẩn hóa tên/từ Việt–Anh bằng lexicon và ITN số.
`text` trong REST (cả tổng và từng segment) và `transcript_final.text` của WS
đều là dạng **written**, không phải dạng spoken dùng chấm WER. Không thêm field
mới hoặc ghi transcript/audio xuống đĩa. Một câu bị lọc trả text rỗng; WS vẫn
phát `transcript_final` cho lượt đó và tiếp tục nhận lượt mới, backend bỏ qua
text rỗng nên không gọi agent.

Đây là **phần hậu xử lý text của B2**, không phải toàn bộ baseline B2: B2 offline
còn dùng Whisper hotwords và kiểm `no_speech_prob`/`avg_logprob`. Gipformer greedy
hiện không có prompt hotword hoặc hai xác suất đó, nên không giả lập giá trị,
không áp bộ lọc hotword echo có thể xóa nhầm câu so sánh tên hãng. Không dùng
số đo WER/CER của B2 để khẳng định chất lượng Gipformer serving. Test offline
trong `tests/test_stt_pipeline.py` đối chiếu kết quả với `asr.finalize` B2 trên
transcript giả lập, đồng thời kiểm đường REST và WS. Các luật offline giữ nguyên.

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

The separate Windows scheduled task `TeleSaleSpeech18110` runs as `pc\khoi` with limited privileges at user logon. It resumes after KHOI signs in following a reboot. `deploy/windows/run-khoi.ps1` refuses to start if port 18110 is already occupied. The Python venv and model files are under `H:\TeleSaleSpeech`; deploy the full source package under `C:\Users\KHOI\TeleSaleSpeech\speech` (including `text/`, `lexicon.json` and the shared Python modules). Do not copy only `serving/`, and do not copy datasets or voice references.

VieNeu runs in a second limited task, `TeleSaleVieNeu18111`, bound to loopback port 18111 with its own venv and model cache under `H:\TeleSaleVieNeu`. The main API proxies VieNeu requests to that sidecar, so no extra Cloudflare route is needed. `deploy/windows/run-vieneu-khoi.ps1` refuses to start when port 18111 is occupied. The CPU uses fp32 because the i7-7820X lacks VNNI needed by VieNeu's int8 build. `tools/materialize_vieneu_cache.py` converts the freshly downloaded Hugging Face snapshot symlinks into files in the isolated cache, avoiding ONNX Runtime's external-data path rejection without relaxing its path checks.

When migrating an existing Windows task, update its action to the relocated script under `speech\serving\deploy\windows\` before restarting; the scripts now use `speech.serving` imports. New tasks use the install scripts in that directory. Windows task execution has not been tested on Linux. After changes, copy the changed source, then run `deploy/windows/restart-khoi.ps1`; it checks the PID on port 18110 belongs to this service before stopping it. Inspect `Get-ScheduledTask -TaskName TeleSaleSpeech18110` and `http://127.0.0.1:18110/health`. `python -m speech.serving.tools.check_public` runs TTS → VAD → STT through the public API; `python -m speech.serving.tools.check_stream` measures the public time to first Korva WAV. `python -m speech.serving.tools.check_vieneu https://sudoapi.ktoxz.id.vn/v1/speech/vieneu/stream` checks the first VieNeu PCM frame and completion. The demo references a versioned `/tts.js` URL because Cloudflare may cache static assets.

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
python -m unittest discover -s speech/serving/tests -t . -v
python -m unittest speech.test.test_text speech.test.test_audio_tts.VoiceTests.test_respell_replaces_whole_words_longest_first -v
# Optional JS queue check, if Node is installed:
node speech/serving/tests/test_tts_stream.js
```

Operational tools moved under `speech.serving.tools`. For example,
`python -m speech.serving.tools.preload` downloads/loads model weights and
`python -m speech.serving.tools.smoke` performs real inference. The `check_*`
commands contact deployed APIs; they are not part of offline verification.

The broader offline dataset/audio tests require `speech/requirements.txt`,
including `faster-whisper` for WAV decoding. A serving-only environment does not
install that offline ASR dependency. Use the offline environment for those tests.
