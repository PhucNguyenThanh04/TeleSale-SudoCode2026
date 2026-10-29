"""CPU speech models. Audio is handled in memory and never persisted."""

from __future__ import annotations

import io
import os
import time
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf
from huggingface_hub import hf_hub_download
from scipy.signal import resample_poly


SAMPLE_RATE = 16_000
MODEL_REPO = "g-group-ai-lab/gipformer1.5-68M-rnnt"
MODEL_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")


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
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        model_dir = directory / "gipformer"
        paths = {}
        for name in MODEL_FILES:
            local = model_dir / name
            paths[name] = str(local) if local.is_file() else hf_hub_download(repo_id=MODEL_REPO, filename=name, local_dir=model_dir)
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=paths["encoder.int8.onnx"],
            decoder=paths["decoder.int8.onnx"],
            joiner=paths["joiner.int8.onnx"],
            tokens=paths["tokens.txt"],
            num_threads=int(os.getenv("SPEECH_CPU_THREADS", "4")),
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
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
        self.vad_config = config
        from korvatts import TTS
        self.tts = TTS()

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
            stream = self.recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, audio)
            self.recognizer.decode_stream(stream)
            result.append({"start_s": round(position, 3), "end_s": round(position + len(audio) / SAMPLE_RATE, 3), "text": stream.result.text.strip()})
        stt_ms = round((time.perf_counter() - start) * 1000) - vad_ms
        return {"text": " ".join(item["text"] for item in result if item["text"]), "segments": result, "debug": {"vad_ms": vad_ms, "stt_ms": stt_ms, "audio_s": round(len(samples) / SAMPLE_RATE, 3), "streaming_stt": False}}

    def synthesize(self, text: str, voice: str):
        start = time.perf_counter()
        audio, duration = self.tts.synthesize(text, voice=voice, lang="vi", total_steps=16)
        output = io.BytesIO()
        sf.write(output, np.asarray(audio).reshape(-1), 44_100, format="WAV", subtype="PCM_16")
        return output.getvalue(), {"tts_ms": round((time.perf_counter() - start) * 1000), "audio_s": round(float(duration), 3)}
