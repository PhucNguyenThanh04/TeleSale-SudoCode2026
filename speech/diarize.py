"""Tách 2 người nói (agent/khách) không cần model nặng: VAD mịn → đặc trưng phổ → k-means 2 cụm.

Dùng để xuất ``turns[]`` có ``idx``/``speaker`` theo format ``hypotheses.json`` của BTC, phục vụ
``entity_accuracy_per_turn`` và ``diarization_turn_accuracy`` trong ``reference_eval.py``.

Giả định (ghi rõ vì ảnh hưởng nhãn A/C): cuộc gọi chỉ có 2 người, và agent ("A") là người nói nhiều hơn —
đúng ở cả 4 hội thoại mẫu BTC và 22 hội thoại team (không dùng "người nói trước": D02–D04 khách nói trước).
Nhúng giọng bằng WeSpeaker ResNet34 (ONNX); không tải được thì lùi về log-năng lượng băng tần ≤ 4 kHz. Đặc trưng là log-năng lượng
băng tần ≤ 4 kHz (băng thông điện thoại) nên không phụ thuộc kênh 16 kHz hay 8 kHz.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import audio as au

AGENT, CUSTOMER = "A", "C"


@dataclass(frozen=True)
class DiarizeConfig:
    min_silence_ms: int = 200    # mịn hơn VAD của ASR (500 ms): khoảng nghỉ đổi lượt thường chỉ 0,3–0,7 s
    min_speech_ms: int = 200
    min_feature_s: float = 0.4   # đoạn ngắn hơn không dùng để học tâm cụm, chỉ gán vào tâm gần nhất
    n_bands: int = 24


def _spans(audio: np.ndarray, cfg: DiarizeConfig) -> list[tuple[int, int]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    options = VadOptions(min_speech_duration_ms=cfg.min_speech_ms, min_silence_duration_ms=cfg.min_silence_ms,
                         speech_pad_ms=30)
    return [(c["start"], c["end"]) for c in get_speech_timestamps(audio, vad_options=options)]


def features(chunk: np.ndarray, n_bands: int = 24) -> np.ndarray:
    """Trung bình + độ lệch chuẩn log-năng lượng theo băng tần (100–4000 Hz), khung 25 ms / bước 10 ms."""
    sr = au.SAMPLE_RATE
    win, hop = int(0.025 * sr), int(0.010 * sr)
    if chunk.size < win:
        chunk = np.pad(chunk, (0, win - chunk.size))
    frames = np.lib.stride_tricks.sliding_window_view(chunk, win)[::hop] * np.hanning(win)
    power = np.abs(np.fft.rfft(frames, n=512)) ** 2
    freqs = np.fft.rfftfreq(512, 1 / sr)
    edges = np.geomspace(100, 4000, n_bands + 1)
    bands = np.stack([power[:, (freqs >= lo) & (freqs < hi)].sum(axis=1) for lo, hi in zip(edges, edges[1:])], 1)
    logb = np.log(bands + 1e-8)
    loud = logb.sum(axis=1) > np.percentile(logb.sum(axis=1), 30)  # bỏ khung gần lặng
    logb = logb[loud] if loud.any() else logb
    logb = logb - logb.mean(axis=1, keepdims=True)  # chuẩn hóa âm lượng: chỉ giữ hình dạng phổ
    return np.concatenate([logb.mean(axis=0), logb.std(axis=0)])


def _kmeans2(x: np.ndarray, iters: int = 50) -> np.ndarray:
    """k-means 2 cụm, khởi tạo bằng cặp điểm xa nhau nhất (xác định, không ngẫu nhiên)."""
    d = np.linalg.norm(x[:, None] - x[None], axis=2)
    i, j = np.unravel_index(np.argmax(d), d.shape)
    centers = x[[i, j]].copy()
    labels = np.zeros(len(x), dtype=int)
    for _ in range(iters):
        new = np.argmin(np.linalg.norm(x[:, None] - centers[None], axis=2), axis=1)
        if np.array_equal(new, labels) and _ > 0:
            break
        labels = new
        for k in (0, 1):
            if (labels == k).any():
                centers[k] = x[labels == k].mean(axis=0)
    return centers


EMBED_REPO, EMBED_FILE = "Wespeaker/wespeaker-voxceleb-resnet34-LM", "voxceleb_resnet34_LM.onnx"
_SESSION = None


def _embedder():
    """Model nhúng giọng WeSpeaker ResNet34 (ONNX, ~26 MB, CC BY 4.0) chạy bằng onnxruntime; None nếu không tải được."""
    global _SESSION
    if _SESSION is None:
        try:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download

            from .asr import MODEL_DIR
            path = hf_hub_download(EMBED_REPO, EMBED_FILE, local_dir=str(MODEL_DIR / EMBED_REPO.replace("/", "--")))
            _SESSION = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        except Exception:  # noqa: BLE001 - thiếu mạng/model → lùi về đặc trưng phổ
            _SESSION = False
    return _SESSION or None


def fbank(chunk: np.ndarray, n_mels: int = 80) -> np.ndarray:
    """Log-mel filterbank kiểu Kaldi (25/10 ms, cửa sổ Povey, pre-emphasis 0,97) + trừ trung bình (CMN)."""
    sr, win, hop, nfft = au.SAMPLE_RATE, 400, 160, 512
    x = chunk.astype(np.float32) * 32768.0
    if x.size < win:
        x = np.pad(x, (0, win - x.size))
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop].astype(np.float64)
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = np.concatenate([frames[:, :1] * (1 - 0.97), frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    frames *= np.hanning(win) ** 0.85
    power = np.abs(np.fft.rfft(frames, n=nfft)) ** 2
    mel = lambda f: 1127 * np.log(1 + f / 700)  # noqa: E731
    pts = np.linspace(mel(20), mel(sr / 2), n_mels + 2)
    bins = mel(np.fft.rfftfreq(nfft, 1 / sr))
    fb = np.maximum(0, np.minimum((bins[None] - pts[:-2, None]) / (pts[1:-1, None] - pts[:-2, None]),
                                  (pts[2:, None] - bins[None]) / (pts[2:, None] - pts[1:-1, None])))
    feats = np.log(np.maximum(power @ fb.T, np.finfo(np.float32).eps))
    return (feats - feats.mean(axis=0)).astype(np.float32)


def _embed(audio: np.ndarray, spans: list[tuple[int, int]], cfg: DiarizeConfig) -> np.ndarray:
    session = _embedder()
    if session is None:
        feats = np.stack([features(audio[s:e], cfg.n_bands) for s, e in spans])
        return (feats - feats.mean(axis=0)) / (feats.std(axis=0) + 1e-6)
    embs = np.stack([session.run(None, {"feats": fbank(audio[s:e])[None]})[0][0] for s, e in spans])
    return embs / (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-8)


def diarize(audio: np.ndarray, cfg: DiarizeConfig = DiarizeConfig()) -> list[dict]:
    """→ ``[{"start", "end", "speaker"}]`` (mẫu, theo thời gian), các đoạn liền kề cùng người đã gộp."""
    audio = np.asarray(audio, dtype=np.float32)
    spans = _spans(audio, cfg)
    if not spans:
        return []
    z = _embed(audio, spans, cfg)
    long_ = np.array([(e - s) / au.SAMPLE_RATE >= cfg.min_feature_s for s, e in spans])
    train = z[long_] if long_.sum() >= 2 else z
    if len(train) < 2:
        labels = np.zeros(len(spans), dtype=int)
    else:
        centers = _kmeans2(train)
        labels = np.argmin(np.linalg.norm(z[:, None] - centers[None], axis=2), axis=1)
    talk = [sum(e - s for (s, e), lab in zip(spans, labels) if lab == k) for k in (0, 1)]
    agent = int(np.argmax(talk))  # agent tư vấn nên nói nhiều hơn khách (26/26 hội thoại BTC + team)
    out: list[dict] = []
    for (s, e), lab in zip(spans, labels):
        speaker = AGENT if lab == agent else CUSTOMER
        if out and out[-1]["speaker"] == speaker:
            out[-1]["end"] = e
        else:
            out.append({"start": s, "end": e, "speaker": speaker})
    # Lượt phủ kín trục thời gian (chia đôi khoảng lặng giữa 2 lượt) để mốc giữa của lượt thật luôn rơi vào 1 lượt.
    for a, b in zip(out, out[1:]):
        a["end"] = b["start"] = (a["end"] + b["start"]) // 2
    out[0]["start"], out[-1]["end"] = 0, max(out[-1]["end"], len(audio))
    return out


def split_by_speaker(start: int, end: int, turns: list[dict]) -> list[tuple[int, int, str | None]]:
    """Cắt một đoạn ASR [start, end) tại các điểm đổi người nói (giữa khoảng lặng giữa 2 lượt khác người)."""
    inside = [t for t in turns if t["end"] > start and t["start"] < end]
    if not inside:
        return [(start, end, None)]
    pieces, cur = [], start
    for a, b in zip(inside, inside[1:]):
        cut = (a["end"] + b["start"]) // 2
        if start < cut < end:
            pieces.append((cur, cut, a["speaker"]))
            cur = cut
    pieces.append((cur, end, inside[-1]["speaker"]))
    return pieces
