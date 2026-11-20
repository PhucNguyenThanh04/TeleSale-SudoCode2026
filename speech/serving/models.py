
from __future__ import annotations

import io
import logging
import os
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf
from huggingface_hub import hf_hub_download
from scipy.signal import resample_poly

from speech.asr import clean_hypothesis
from speech.normalize import normalize_text
from speech.text.tts import prepare_tts_text


SAMPLE_RATE = 16_000
MODEL_REPO = "g-group-ai-lab/gipformer1.5-68M-rnnt"
MODEL_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
logger = logging.getLogger("uvicorn.error")


def read_wav(data: bytes) -> np.ndarray:
    with io.BytesIO(data) as file:
        samples, rate = sf.read(file, dtype="float32", always_2d=True)
    if rate < 8_000 or rate > 96_000:
        raise ValueError("Unsupported sample rate")
    if len(samples) / rate > 30:
        raise ValueError("Audio must be at most 30 seconds")
    mono = samples.mean(axis=1)
    if rate != SAMPLE_RATE:
        from math import gcd
        factor = gcd(rate, SAMPLE_RATE)
        mono = resample_poly(mono, SAMPLE_RATE // factor, rate // factor)
    return np.asarray(mono, dtype=np.float32)


class Models:
    def __init__(self, directory: Path):
        self.asr_provider = os.getenv("SPEECH_ASR_PROVIDER", "cuda").strip().lower()
        self.vad_provider = os.getenv("SPEECH_VAD_PROVIDER", self.asr_provider).strip().lower()
        self.tts_provider = os.getenv("SPEECH_TTS_PROVIDER", "cuda").strip().lower()
        for name, provider in (("ASR", self.asr_provider), ("VAD", self.vad_provider), ("TTS", self.tts_provider)):
            if provider not in {"cuda", "cpu"}:
                raise ValueError(f"SPEECH_{name}_PROVIDER must be cuda or cpu")
        if "cuda" in (self.asr_provider, self.vad_provider) and "+cuda" not in version("sherpa-onnx"):
            raise RuntimeError("GPU ASR requires a CUDA-enabled sherpa-onnx wheel; "
                               "install requirements-cuda13.txt or set SPEECH_ASR_PROVIDER=cpu")
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        model_dir = directory / "gipformer"
        paths = {}
        files = (tuple(name.replace(".int8", "") for name in MODEL_FILES)
                 if self.asr_provider == "cuda" else MODEL_FILES)
        for name in files:
            local = model_dir / name
            paths[name] = str(local) if local.is_file() else hf_hub_download(repo_id=MODEL_REPO, filename=name, local_dir=model_dir)
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=paths[files[0]],
            decoder=paths[files[1]],
            joiner=paths[files[2]],
            tokens=paths["tokens.txt"],
            num_threads=int(os.getenv("SPEECH_CPU_THREADS", "4")),
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
            provider=self.asr_provider,
        )
        vad_path = directory / "silero_vad.onnx"
        if not vad_path.exists():
            import urllib.request
            source = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
            temporary = vad_path.with_suffix(".download")
            urllib.request.urlretrieve(source, temporary)
            temporary.replace(vad_path)
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(vad_path)
        config.silero_vad.min_silence_duration = 0.35
        config.sample_rate = SAMPLE_RATE
        config.provider = self.vad_provider
        self.vad_config = config
        from korvatts import TTS
        self.tts = TTS(device="gpu" if self.tts_provider == "cuda" else "cpu",
                       num_threads=int(os.getenv("SPEECH_CPU_THREADS", "4")))
        if self.tts_provider == "cuda":
            for name in ("duration_predictor", "text_encoder", "vector_estimator", "vocoder"):
                if getattr(self.tts.sessions, name).get_providers()[0] != "CUDAExecutionProvider":
                    raise RuntimeError(f"Korva {name} did not initialize on CUDA")
        self.asr_warmup_runs = 0
        self.vad_warmup_runs = 0
        self.tts_warmup_runs = 0
        for index in range(3):
            self.transcribe_segment(np.zeros(SAMPLE_RATE, dtype=np.float32))
            self.asr_warmup_runs += 1
            logger.info("ASR warmup %d/3 complete (provider=%s)", index + 1, self.asr_provider)
        for index in range(3):
            self.segments(np.zeros(SAMPLE_RATE, dtype=np.float32))
            self.vad_warmup_runs += 1
            logger.info("VAD warmup %d/3 complete (provider=%s)", index + 1, self.vad_provider)
        for index in range(3):
            self.synthesize("Xin chào.", "khanh_vy")
            self.tts_warmup_runs += 1
            logger.info("Korva TTS warmup %d/3 complete (provider=%s)", index + 1, self.tts_provider)

    def create_vad(self):
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = self.vad_config.silero_vad.model
        config.silero_vad.min_silence_duration = 0.7
        config.silero_vad.min_speech_duration = 0.2
        config.silero_vad.max_speech_duration = 60
        config.sample_rate = SAMPLE_RATE
        config.provider = self.vad_config.provider
        vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=35)
        return vad, config.silero_vad.window_size

    def transcribe_segment(self, samples: np.ndarray) -> str:
        stream = self.recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        self.recognizer.decode_stream(stream)
        return normalize_text(clean_hypothesis(stream.result.text)).written

    def segments(self, samples: np.ndarray):
        vad = sherpa_onnx.VoiceActivityDetector(self.vad_config, buffer_size_in_seconds=35)
        window = self.vad_config.silero_vad.window_size
        for start in range(0, len(samples), window):
            vad.accept_waveform(samples[start:start + window])
        vad.flush()
        result = []
        while not vad.empty():
            segment = vad.front
            if len(segment.samples) >= SAMPLE_RATE // 5:
                result.append((segment.start / SAMPLE_RATE, np.asarray(segment.samples, dtype=np.float32).copy()))
            vad.pop()
        return result

    def transcribe(self, samples: np.ndarray):
        start = time.perf_counter()
        segments = self.segments(samples)
        vad_ms = round((time.perf_counter() - start) * 1000)
        result = []
        for position, audio in segments:
            text = self.transcribe_segment(audio)
            result.append({"start_s": round(position, 3), "end_s": round(position + len(audio) / SAMPLE_RATE, 3), "text": text})
        stt_ms = round((time.perf_counter() - start) * 1000) - vad_ms
        return {"text": " ".join(item["text"] for item in result if item["text"]), "segments": result, "debug": {"vad_ms": vad_ms, "stt_ms": stt_ms, "audio_s": round(len(samples) / SAMPLE_RATE, 3), "streaming_stt": False}}

    def synthesize(self, text: str, voice: str):
        start = time.perf_counter()
        audio, duration = self.tts.synthesize(prepare_tts_text(text), voice=voice, lang="vi", total_steps=16)
        output = io.BytesIO()
        sf.write(output, np.asarray(audio).reshape(-1), 44_100, format="WAV", subtype="PCM_16")
        return output.getvalue(), {"tts_ms": round((time.perf_counter() - start) * 1000), "audio_s": round(float(duration), 3)}
