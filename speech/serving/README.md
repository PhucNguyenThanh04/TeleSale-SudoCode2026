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
