"""ASR offline: Silero VAD (đi kèm faster-whisper) → faster-whisper (PhoWhisper/Whisper) → chuẩn hóa Việt-Anh.

Mặc định khóa ngôn ngữ "vi": Whisper đa ngôn ngữ vẫn viết được từ tiếng Anh xen trong câu tiếng Việt
("size", "ship", "voucher"), còn tự nhận ngôn ngữ theo từng đoạn ngắn dễ nhảy sang "en" và dịch sai cả câu.
``language="auto"`` chỉ đổi sang "en" khi đoạn đó chắc chắn là tiếng Anh.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import numpy as np

from . import audio as au
from .entities import REFERENCE_DATE, Product, extract_entities
from .lexicon import Lexicon, hotwords as lexicon_hotwords
from .normalize import default_lexicon, normalize_text, rules_fingerprint
from .textutil import fold

PRESETS = {
    "whisper-small": "Systran/faster-whisper-small",
    "whisper-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "whisper-large-v3": "Systran/faster-whisper-large-v3",
    "phowhisper-small": "mad1999/pho-whisper-small-ct2",
    "phowhisper-medium": "mad1999/pho-whisper-medium-ct2",
    "phowhisper-large": "kiendt/PhoWhisper-large-ct2",
}
MODEL_DIR = Path(os.environ.get("SPEECH_MODEL_DIR", Path.home() / ".cache" / "telesale-speech" / "models"))
EN_THRESHOLD = 0.75

# Câu Whisper hay "bịa" khi gặp khoảng lặng/nhiễu (học từ phụ đề YouTube).
_HALLUCINATIONS = re.compile(
    r"subscribe|đăng ký kênh|ghiền mì gõ|cảm ơn các bạn đã (?:theo dõi|xem|lắng nghe)|hẹn gặp lại các bạn|"
    r"like (?:và|and) share|bấm chuông|thanks for watching|thank you for watching|vietsub|phụ đề|"
    r"la la school|chào mừng (?:các bạn )?quay trở lại", re.I)
_REPEAT_RE = re.compile(r"\b((?:\w+\s+){0,3}\w+)(?:\s+\1\b){3,}", re.I)


@dataclass(frozen=True)
class VadConfig:
    threshold: float = 0.5
    min_speech_ms: int = 250
    min_silence_ms: int = 500
    speech_pad_ms: int = 200
    max_speech_s: float = 28.0


@dataclass(frozen=True)
class DecodeConfig:
    language: str = "vi"         # "vi" | "en" | "auto"
    beam_size: int = 5
    use_hotwords: bool = True
    segmentation: str = "utterance"  # "utterance": VAD cắt từng câu như agent thoại thật; "file": cả file


def resolve_model(name: str) -> Path:
    """Tên preset hoặc thư mục CTranslate2 → thư mục cục bộ (tải về MODEL_DIR nếu chưa có)."""
    if Path(name).is_dir():
        return Path(name)
    repo = PRESETS.get(name, name)
    target = MODEL_DIR / repo.replace("/", "--")
    if not (target / "model.bin").exists():
        from huggingface_hub import snapshot_download

        # local_dir: tránh lỗi symlink (WinError 1314) của cache Hugging Face trên Windows.
        snapshot_download(repo, local_dir=str(target))
    if not (target / "tokenizer.json").exists():
        donor = MODEL_DIR / PRESETS["whisper-small"].replace("/", "--") / "tokenizer.json"
        if donor.exists():  # PhoWhisper-large CT2 thiếu tokenizer; cùng bộ từ vựng 51865 với Whisper small
            shutil.copy(donor, target / "tokenizer.json")
    return target


def load_model(name: str, device: str = "auto", compute_type: str = "auto"):
    """→ (WhisperModel, device thật sự dùng, compute_type). "auto" thử GPU rồi lùi về CPU nếu thiếu CUDA/cuDNN."""
    from faster_whisper import WhisperModel

    path = str(resolve_model(name))
    devices = ["cuda", "cpu"] if device == "auto" else [device]
    last_error: Exception | None = None
    for dev in devices:
        ctype = compute_type if compute_type != "auto" else ("int8_float16" if dev == "cuda" else "int8")
        try:
            model = WhisperModel(path, device=dev, compute_type=ctype, cpu_threads=os.cpu_count() or 4)
            if dev == "cuda":  # thiếu cublas/cudnn chỉ lộ ra khi chạy thật
                list(model.transcribe(np.zeros(au.SAMPLE_RATE, dtype=np.float32), language="vi")[0])
            return model, dev, ctype
        except Exception as err:  # noqa: BLE001 - lùi về thiết bị kế tiếp
            last_error = err
    raise RuntimeError(f"Không nạp được model {name}: {last_error}")


def speech_chunks(audio: np.ndarray, vad: VadConfig) -> list[tuple[int, int]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    options = VadOptions(threshold=vad.threshold, min_speech_duration_ms=vad.min_speech_ms,
                         min_silence_duration_ms=vad.min_silence_ms, speech_pad_ms=vad.speech_pad_ms,
                         max_speech_duration_s=vad.max_speech_s)
    return [(c["start"], c["end"]) for c in get_speech_timestamps(audio, vad_options=options)]


def clean_hypothesis(text: str, hotword_terms: frozenset[str] = frozenset()) -> str:
    """Bỏ câu ảo giác quen thuộc, lặp n-gram, và trường hợp model đọc lại nguyên danh sách hotword."""
    text = text.strip()
    if not text or _HALLUCINATIONS.search(text):
        return ""
    text = _REPEAT_RE.sub(r"\1", text)
    if hotword_terms:
        words = [fold(w) for w in re.findall(r"\w+", text)]
        hits = sum(1 for w in words if w in hotword_terms)
        if hits >= 3 and hits >= 0.6 * len(words):
            return ""
    return text


def _pick_language(model, chunk: np.ndarray, language: str) -> str:
    if language != "auto":
        return language
    lang, prob, _ = model.detect_language(audio=chunk)
    return "en" if lang == "en" and prob >= EN_THRESHOLD else "vi"


def _decode(model, chunk: np.ndarray, language: str, cfg: DecodeConfig, hotwords: str | None):
    segments, _ = model.transcribe(
        chunk, language=language, beam_size=cfg.beam_size, vad_filter=False, without_timestamps=True,
        condition_on_previous_text=False, hotwords=hotwords, temperature=(0.0, 0.2, 0.4))
    return list(segments)


def transcribe_audio(model, audio: np.ndarray, *, cfg: DecodeConfig, vad: VadConfig, lexicon: Lexicon,
                     catalog: tuple[Product, ...] = (), reference_date: date = REFERENCE_DATE) -> dict:
    """Một file âm thanh → bản ghi theo format ``hypotheses.json`` của BTC (+ đoạn debug ``asr_segments``)."""
    sr = au.SAMPLE_RATE
    hotwords = lexicon_hotwords(lexicon) if cfg.use_hotwords else None
    hotword_terms = frozenset(fold(t) for t in re.findall(r"\w+", hotwords or ""))
    pieces: list[dict] = []
    if cfg.segmentation == "file":
        from faster_whisper.vad import VadOptions

        segments, _ = model.transcribe(
            audio, language=None if cfg.language == "auto" else cfg.language, beam_size=cfg.beam_size,
            vad_filter=True, vad_parameters=VadOptions(
                threshold=vad.threshold, min_speech_duration_ms=vad.min_speech_ms,
                min_silence_duration_ms=vad.min_silence_ms, speech_pad_ms=vad.speech_pad_ms),
            condition_on_previous_text=False, hotwords=hotwords, temperature=(0.0, 0.2, 0.4))
        for seg in segments:
            pieces.append({"start": seg.start, "end": seg.end, "raw": seg.text, "lang": cfg.language,
                           "avg_logprob": seg.avg_logprob, "no_speech_prob": seg.no_speech_prob})
    else:
        for start, end in speech_chunks(audio, vad):
            chunk = audio[start:end]
            lang = _pick_language(model, chunk, cfg.language)
            segs = _decode(model, chunk, lang, cfg, hotwords)
            if not segs:
                continue
            pieces.append({"start": start / sr, "end": end / sr, "raw": " ".join(s.text.strip() for s in segs),
                           "lang": lang, "avg_logprob": float(np.mean([s.avg_logprob for s in segs])),
                           "no_speech_prob": float(max(s.no_speech_prob for s in segs))})
    return finalize(pieces, lexicon, catalog, reference_date, hotword_terms)


def finalize(pieces: list[dict], lexicon: Lexicon, catalog: tuple[Product, ...] = (),
             reference_date: date = REFERENCE_DATE, hotword_terms: frozenset[str] = frozenset()) -> dict:
    """Các đoạn ASR thô → chuẩn hóa + entity. Tách riêng để sửa lexicon xong chấm lại mà không cần chạy lại ASR."""
    turns = []
    for piece in pieces:
        if piece["no_speech_prob"] > 0.6 and piece["avg_logprob"] < -1.0:
            continue
        raw = clean_hypothesis(piece["raw"], hotword_terms)
        if not raw:
            continue
        norm = normalize_text(raw, lexicon)
        turns.append({"start": round(piece["start"], 2), "end": round(piece["end"], 2), "text": norm.spoken,
                      "text_written": norm.written, "raw": raw, "lang": piece["lang"],
                      "avg_logprob": round(piece["avg_logprob"], 3), "no_speech_prob": round(piece["no_speech_prob"], 3)})
    merged, per_turn = extract_entities([t["text_written"] for t in turns], catalog, reference_date)
    for turn, entities in zip(turns, per_turn):
        turn["entities"] = entities
    return {"text": " ".join(t["text"] for t in turns if t["text"]), "entities": merged, "asr_segments": turns}


def transcribe_files(paths: list[Path], model_name: str, *, cfg: DecodeConfig, vad: VadConfig = VadConfig(),
                     device: str = "auto", compute_type: str = "auto", catalog: tuple[Product, ...] = (),
                     reference_date: date = REFERENCE_DATE, lexicon: Lexicon | None = None,
                     progress=print) -> tuple[dict, dict]:
    """→ (hypotheses theo id file, thông tin run). Chỉ in id + thời lượng, không in nội dung hội thoại (PII)."""
    lexicon = lexicon or default_lexicon()
    started = time.perf_counter()
    model, used_device, used_type = load_model(model_name, device, compute_type)
    load_s = time.perf_counter() - started
    hypotheses: dict[str, dict] = {}
    total_audio = total_asr = 0.0
    for path in paths:
        audio = au.decode(path)
        t0 = time.perf_counter()
        record = transcribe_audio(model, audio, cfg=cfg, vad=vad, lexicon=lexicon, catalog=catalog,
                                  reference_date=reference_date)
        asr_s = time.perf_counter() - t0
        audio_s = audio.size / au.SAMPLE_RATE
        record["meta"] = {"audio_s": round(audio_s, 2), "asr_s": round(asr_s, 2), "rtf": round(asr_s / audio_s, 3)}
        hypotheses[path.stem] = record
        total_audio, total_asr = total_audio + audio_s, total_asr + asr_s
        progress(f"  {path.stem}: {audio_s:.1f}s audio → {asr_s:.1f}s ({asr_s / audio_s:.2f}x thời gian thực), "
                 f"{len(record['asr_segments'])} đoạn")
    info = {"model": model_name, "model_path": str(resolve_model(model_name)), "device": used_device,
            "compute_type": used_type, "decode": asdict(cfg), "vad": asdict(vad), "load_s": round(load_s, 2),
            "audio_s": round(total_audio, 2), "asr_s": round(total_asr, 2),
            "rtf": round(total_asr / total_audio, 3) if total_audio else None, **rules_fingerprint()}
    return hypotheses, info
