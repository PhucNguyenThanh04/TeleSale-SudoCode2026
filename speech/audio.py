"""Đọc/ghi âm thanh mono 16 kHz và giả lập kênh điện thoại cho dữ liệu tổng hợp (chỉ cần numpy + PyAV)."""
from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


def decode(source: str | Path | bytes, sampling_rate: int = SAMPLE_RATE) -> np.ndarray:
    """mp3/wav/m4a… → float32 mono [-1, 1]. Dùng PyAV đi kèm faster-whisper, không cần ffmpeg."""
    from faster_whisper.audio import decode_audio

    if isinstance(source, bytes):
        return decode_audio(io.BytesIO(source), sampling_rate=sampling_rate)
    return decode_audio(str(source), sampling_rate=sampling_rate)


def from_pcm16(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def write_wav(path: str | Path | io.BytesIO, audio: np.ndarray, sampling_rate: int = SAMPLE_RATE) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    if not isinstance(path, io.BytesIO):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        path = str(path)
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sampling_rate)
        fh.writeframes(pcm.tobytes())


def silence(seconds: float, sampling_rate: int = SAMPLE_RATE) -> np.ndarray:
    return np.zeros(int(round(seconds * sampling_rate)), dtype=np.float32)


def trim(audio: np.ndarray, threshold: float = 0.01, pad_s: float = 0.05, sampling_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Cắt khoảng lặng đầu/cuối của từng câu TTS để tự kiểm soát khoảng nghỉ giữa các lượt."""
    loud = np.flatnonzero(np.abs(audio) > threshold)
    if loud.size == 0:
        return audio
    pad = int(pad_s * sampling_rate)
    return audio[max(0, loud[0] - pad):loud[-1] + pad]


def peak_normalize(audio: np.ndarray, peak: float = 0.89) -> np.ndarray:
    top = float(np.max(np.abs(audio))) if audio.size else 0.0
    return audio if top == 0 else (audio * (peak / top)).astype(np.float32)


def _band_limit(audio: np.ndarray, low_hz: float, high_hz: float, sampling_rate: int) -> np.ndarray:
    spectrum = np.fft.rfft(audio)
    freqs = np.fft.rfftfreq(audio.size, 1.0 / sampling_rate)
    gain = np.clip((freqs - low_hz * 0.8) / (low_hz * 0.2), 0, 1) * np.clip((high_hz * 1.1 - freqs) / (high_hz * 0.1), 0, 1)
    return np.fft.irfft(spectrum * gain, n=audio.size).astype(np.float32)


def telephone(audio: np.ndarray, sampling_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Giả lập cuộc gọi: băng thông 300–3400 Hz và lượng tử μ-law 8 bit như kênh G.711."""
    narrow = peak_normalize(_band_limit(audio, 300.0, 3400.0, sampling_rate))
    mu = 255.0
    companded = np.sign(narrow) * np.log1p(mu * np.abs(narrow)) / np.log1p(mu)
    quantized = np.round((companded + 1.0) * 127.5) / 127.5 - 1.0
    return (np.sign(quantized) * np.expm1(np.abs(quantized) * np.log1p(mu)) / mu).astype(np.float32)


def pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n)
    freqs[0] = freqs[1] if n > 1 else 1.0
    noise = np.fft.irfft(spectrum / np.sqrt(freqs), n=n)
    return (noise / (np.std(noise) + 1e-9)).astype(np.float32)


def add_noise(audio: np.ndarray, snr_db: float, rng: np.random.Generator, noise: np.ndarray | None = None) -> np.ndarray:
    """Trộn nhiễu (mặc định nhiễu hồng; có thể truyền tiếng ồn thật) ở SNR cho trước, tính trên đoạn có tiếng."""
    if noise is None or noise.size == 0:
        noise = pink_noise(audio.size, rng)
    else:
        start = int(rng.integers(0, max(1, noise.size - audio.size)))
        noise = np.resize(noise[start:], audio.size).astype(np.float32)
    voiced = audio[np.abs(audio) > 0.02]
    speech_rms = float(np.sqrt(np.mean(np.square(voiced)))) if voiced.size else float(np.sqrt(np.mean(np.square(audio))))
    noise_rms = float(np.sqrt(np.mean(np.square(noise)))) + 1e-9
    scaled = noise * (speech_rms / (10 ** (snr_db / 20.0)) / noise_rms)
    return np.clip(audio + scaled, -1.0, 1.0).astype(np.float32)
