from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import audio as au

AGENT, CUSTOMER = "A", "C"


@dataclass(frozen=True)
class DiarizeConfig:
    min_silence_ms: int = 200
    min_speech_ms: int = 200
    min_feature_s: float = 0.4
    n_bands: int = 24


def _spans(audio: np.ndarray, cfg: DiarizeConfig) -> list[tuple[int, int]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    options = VadOptions(min_speech_duration_ms=cfg.min_speech_ms, min_silence_duration_ms=cfg.min_silence_ms,
                         speech_pad_ms=30)
    return [(c["start"], c["end"]) for c in get_speech_timestamps(audio, vad_options=options)]


def features(chunk: np.ndarray, n_bands: int = 24) -> np.ndarray:
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
    loud = logb.sum(axis=1) > np.percentile(logb.sum(axis=1), 30)
    logb = logb[loud] if loud.any() else logb
    logb = logb - logb.mean(axis=1, keepdims=True)
    return np.concatenate([logb.mean(axis=0), logb.std(axis=0)])


def _kmeans2(x: np.ndarray, iters: int = 50) -> np.ndarray:
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
    global _SESSION
    if _SESSION is None:
        try:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download

            from .asr import MODEL_DIR
            path = hf_hub_download(EMBED_REPO, EMBED_FILE, local_dir=str(MODEL_DIR / EMBED_REPO.replace("/", "--")))
            _SESSION = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        except Exception:
            _SESSION = False
    return _SESSION or None


def fbank(chunk: np.ndarray, n_mels: int = 80) -> np.ndarray:
    sr, win, hop, nfft = au.SAMPLE_RATE, 400, 160, 512
    x = chunk.astype(np.float32) * 32768.0
    if x.size < win:
        x = np.pad(x, (0, win - x.size))
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop].astype(np.float64)
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = np.concatenate([frames[:, :1] * (1 - 0.97), frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    frames *= np.hanning(win) ** 0.85
    power = np.abs(np.fft.rfft(frames, n=nfft)) ** 2
    mel = lambda f: 1127 * np.log(1 + f / 700)
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
    agent = int(np.argmax(talk))
    out: list[dict] = []
    for (s, e), lab in zip(spans, labels):
        speaker = AGENT if lab == agent else CUSTOMER
        if out and out[-1]["speaker"] == speaker:
            out[-1]["end"] = e
        else:
            out.append({"start": s, "end": e, "speaker": speaker})
    for a, b in zip(out, out[1:]):
        a["end"] = b["start"] = (a["end"] + b["start"]) // 2
    out[0]["start"], out[-1]["end"] = 0, max(out[-1]["end"], len(audio))
    return out


def split_by_speaker(start: int, end: int, turns: list[dict]) -> list[tuple[int, int, str | None]]:
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
