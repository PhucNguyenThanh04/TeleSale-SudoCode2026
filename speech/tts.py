"""Tạo audio hội thoại từ kịch bản (cùng format ``asr/ground_truth.json`` BTC) bằng edge-tts hoặc ElevenLabs.

Mỗi lượt được đọc bằng giọng theo vai (A = nhân viên, C = khách) và vùng miền/giới tính ghi trong kịch bản,
rồi ghép với khoảng nghỉ ngẫu nhiên có seed. Đầu ra có ``audio/<id>.segments.json`` (mốc thời gian + người nói)
để chấm diarization ở M2, và bản sao ``ground_truth.json`` để chấm WER bằng script BTC.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

from . import audio as au
from .btc import text_sha256
from .team import VALIDATOR_ONLY_FIELDS, VOICE_FIELDS

ELEVEN_API = "https://api.elevenlabs.io"
DEFAULT_ELEVEN_MODEL = "eleven_flash_v2_5"
ELEVEN_LANGUAGE_CODE_MODELS = frozenset({"eleven_flash_v2_5", "eleven_turbo_v2_5"})
_VOICE_ID_RE = re.compile(r"^[A-Za-z0-9]{20}$")


def credits_per_char(model_id: str) -> float:
    """Ước tính theo bảng giá ElevenLabs (Flash/Turbo rẻ hơn một nửa); kiểm tra lại trên trang Usage."""
    return 0.5 if model_id in ELEVEN_LANGUAGE_CODE_MODELS else 1.0


def resolve_voice(config: dict, engine: str, role: str, region: str | None, gender: str | None) -> dict:
    section = config.get(engine, {})
    voices = section.get("voices", {})
    keys = [f"{role}:{region}_{gender}", f"{region}_{gender}", f"{role}:bac_{gender}", f"bac_{gender}"]
    for key in keys:
        if key in voices:
            params = {**voices[key], **section.get("roles", {}).get(role, {})}
            if engine == "elevenlabs":
                params.setdefault("model_id", section.get("model_id", DEFAULT_ELEVEN_MODEL))
                params.setdefault("voice_settings", section.get("voice_settings", {}))
            return {"key": key, **params}
    raise KeyError(f"Chưa cấu hình giọng {engine} cho vai {role}, vùng {region}, giới tính {gender} (thử các khóa {keys}).")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

async def _edge_bytes(text: str, params: dict) -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(text, params["voice"], rate=params.get("rate", "+0%"),
                                       pitch=params.get("pitch", "+0Hz"), volume=params.get("volume", "+0%"))
    data = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            data.extend(chunk["data"])
    return bytes(data)


def _edge(text: str, params: dict) -> np.ndarray:
    # Dịch vụ edge-tts thỉnh thoảng trả NoAudioReceived ngẫu nhiên với cùng tham số → thử lại vài lần.
    attempts = 6
    for attempt in range(attempts):
        try:
            return au.decode(asyncio.run(_edge_bytes(text, params)))
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("unreachable")


def eleven_request(method: str, path: str, api_key: str, body: dict | None = None,
                   query: dict | None = None, accept: str = "application/json") -> bytes:
    url = ELEVEN_API + path + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"xi-api-key": api_key, "Accept": accept}
    if data is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(4):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:500]
            if err.code == 429 and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            hint = ""
            if "voice_not_found" in detail:
                hint = (" — giọng trong Voice Library phải được 'Add to My Voices' trước "
                        "(trên web hoặc `python -m speech voices --engine elevenlabs --add OWNER_ID:VOICE_ID`).")
            elif err.code == 401:
                hint = " — kiểm tra biến môi trường ELEVENLABS_API_KEY."
            raise RuntimeError(f"ElevenLabs HTTP {err.code}: {detail}{hint}") from None
    raise RuntimeError("ElevenLabs: hết lượt thử lại")


def _eleven(text: str, params: dict) -> np.ndarray:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("Thiếu biến môi trường ELEVENLABS_API_KEY.")
    voice_id = params.get("voice_id", "")
    if not _VOICE_ID_RE.match(voice_id):
        raise RuntimeError(f"voice_id chưa hợp lệ cho khóa {params.get('key')}: điền voice_id thật vào voices.json.")
    body = {"text": text, "model_id": params["model_id"]}
    if params.get("voice_settings"):
        body["voice_settings"] = params["voice_settings"]
    if params["model_id"] in ELEVEN_LANGUAGE_CODE_MODELS:
        body["language_code"] = "vi"
    pcm = eleven_request("POST", f"/v1/text-to-speech/{voice_id}", api_key, body,
                         {"output_format": "pcm_16000"}, accept="audio/pcm")
    return au.from_pcm16(pcm)


_VIENEU_MODELS: dict[str, object] = {}
_VIENEU_CLONES: dict[tuple[str, str], str] = {}  # (mode, sha256 mẫu giọng) → tên giọng đã add_voice
_VIENEU_INFER_KEYS = ("temperature", "top_k")


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _vieneu(text: str, params: dict) -> np.ndarray:
    """VieNeu-TTS chạy offline trên CPU (pip ``vieneu``; cần Python ≤ 3.13 vì phụ thuộc kaldi-native-fbank).

    Mô hình tự đọc chen tiếng Anh nên không cần bảng ``pronounce``. Audio gốc 24/48 kHz được giải mã lại
    về 16 kHz bằng cùng bộ resample PyAV như edge-tts để hai nguồn đi qua một đường xử lý giống nhau.
    ``ref_audio`` (giọng clone): mẫu giọng được ``add_voice`` một lần cho mỗi nội dung file (sha256), không lưu
    vào thư viện giọng của VieNeu (``save=False``).
    """
    mode = params.get("mode", "v3turbo")
    if mode not in _VIENEU_MODELS:
        from vieneu import Vieneu

        _VIENEU_MODELS[mode] = Vieneu(mode=mode)
    model = _VIENEU_MODELS[mode]
    voice = params.get("voice")
    if params.get("ref_audio"):
        digest = params.get("ref_audio_sha256") or file_sha256(params["ref_audio"])
        if (mode, digest) not in _VIENEU_CLONES:
            _VIENEU_CLONES[(mode, digest)] = model.add_voice(
                f"clone-{digest[:12]}", str(params["ref_audio"]), denoise=params.get("denoise", True), save=False)
        voice = _VIENEU_CLONES[(mode, digest)]
    kwargs = {k: params[k] for k in _VIENEU_INFER_KEYS if k in params}
    wav = np.asarray(model.infer(text, voice=voice, **kwargs), dtype=np.float32).reshape(-1)
    buffer = io.BytesIO()
    au.write_wav(buffer, wav, sampling_rate=int(getattr(model, "sample_rate", 24_000)))
    return au.decode(buffer.getvalue())


_MMS_MODELS: dict[str, tuple] = {}


def _mms(text: str, params: dict) -> np.ndarray:
    """Meta MMS-TTS (VITS, 1 giọng, giấy phép CC-BY-NC 4.0). Cần ``torch`` + ``transformers``; không đọc được tiếng Anh."""
    import torch
    from transformers import AutoTokenizer, VitsModel

    name = params.get("voice", "facebook/mms-tts-vie")
    if name not in _MMS_MODELS:
        _MMS_MODELS[name] = (VitsModel.from_pretrained(name), AutoTokenizer.from_pretrained(name))
    model, tokenizer = _MMS_MODELS[name]
    model.speaking_rate = float(params.get("speaking_rate", 1.0))
    # VITS dự đoán độ dài ngẫu nhiên → seed theo câu để chạy lại ra cùng audio.
    torch.manual_seed(int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16))
    with torch.no_grad():
        wav = model(**tokenizer(text, return_tensors="pt")).waveform[0].numpy().astype(np.float32)
    buffer = io.BytesIO()
    au.write_wav(buffer, wav, sampling_rate=int(model.config.sampling_rate))
    return au.decode(buffer.getvalue())


def _files(text: str, params: dict) -> np.ndarray:
    """Clip có sẵn (ElevenLabs tạo thủ công trên web, xem ``manual.py``); ``text`` chỉ để báo cáo."""
    return au.decode(params["path"])


ENGINES = {"edge": _edge, "elevenlabs": _eleven, "vieneu": _vieneu, "mms": _mms, "files": _files}


def synth_text(text: str, engine: str, params: dict, cache_dir: Path) -> tuple[np.ndarray, bool]:
    """→ (audio, lấy từ cache?). Cache theo (engine, tham số giọng, câu) để chạy lại không tốn credit.

    Giọng clone được khóa theo sha256 nội dung file mẫu (không theo đường dẫn): thay mẫu giọng thì tạo lại.
    Engine ``files`` đọc thẳng clip có sẵn, không cache và không tính ký tự mới.
    """
    if engine == "files":
        return ENGINES[engine](text, params), True
    settings = {k: v for k, v in params.items() if k not in ("key", "name", "note")}
    if settings.get("ref_audio"):
        settings["ref_audio_sha256"] = settings.get("ref_audio_sha256") or file_sha256(settings["ref_audio"])
        del settings["ref_audio"]
        params = {**params, "ref_audio_sha256": settings["ref_audio_sha256"]}
    digest = hashlib.sha1(json.dumps([engine, settings, text], sort_keys=True, ensure_ascii=False).encode("utf-8"))
    path = cache_dir / f"{engine}-{digest.hexdigest()[:16]}.wav"
    if path.exists():
        return au.decode(path), True
    clip = ENGINES[engine](text, params)
    au.write_wav(path, clip)
    return clip, False


# ---------------------------------------------------------------------------
# Hội thoại
# ---------------------------------------------------------------------------

def with_full_text(dialogue: dict) -> dict:
    dialogue = copy.deepcopy(dialogue)
    for name in VALIDATOR_ONLY_FIELDS:
        dialogue.pop(name, None)
    for turn in dialogue["turns"]:
        turn.pop("tts_text", None)
    dialogue.setdefault("full_text", " ".join(turn["text"] for turn in dialogue["turns"]))
    dialogue.setdefault("n_turns", len(dialogue["turns"]))
    return dialogue


def respell(text: str, mapping: dict[str, str]) -> str:
    """Thay từ tiếng Anh bằng cách người Việt hay đọc ("size" → "sai") trước khi đưa cho giọng TTS tiếng Việt."""
    if not mapping:
        return text
    lowered = {k.lower(): v for k, v in mapping.items()}
    alternatives = "|".join(re.escape(k) for k in sorted(lowered, key=len, reverse=True))
    return re.sub(rf"(?<!\w)({alternatives})(?!\w)", lambda m: lowered[m.group(0).lower()], text, flags=re.IGNORECASE)


def _turn_params(dialogue: dict, turn: dict, engine: str, config: dict) -> dict:
    speaker = turn["speaker"]
    section = config.get(engine, {})
    if engine == "files":
        key = f"{dialogue['id']}#{turn.get('idx')}"
        path = section.get("clips", {}).get(key)
        if not path:
            raise KeyError(f"Thiếu clip cho {dialogue['id']} lượt {turn.get('idx')} (vai {speaker}).")
        return {"key": f"files:{speaker}", "path": path}
    voice_field, region_field, gender_field = VOICE_FIELDS.get(speaker, VOICE_FIELDS["C"])
    team_key = dialogue.get(voice_field)
    if team_key and team_key in section.get("voices", {}):  # giọng clone của thành viên (tv1–tv3)
        return {"key": team_key, **section["voices"][team_key], **section.get("roles", {}).get(speaker, {})}
    return resolve_voice(config, engine, speaker, dialogue.get(region_field), dialogue.get(gender_field))


def plan(dialogues: list[dict], engine: str, config: dict) -> list[dict]:
    """Bảng phân giọng + số ký tự cần đọc (để xem trước chi phí trước khi gọi API)."""
    pronounce = config.get(engine, {}).get("pronounce", {})
    rows = []
    for dialogue in dialogues:
        for turn in dialogue["turns"]:
            params = _turn_params(dialogue, turn, engine, config)
            rows.append({"dialogue": dialogue["id"], "idx": turn.get("idx"), "speaker": turn["speaker"],
                         "voice_key": params["key"], "params": params,
                         "text": turn.get("tts_text") or respell(turn["text"], pronounce)})
    return rows


def _voice_label(params: dict) -> str:
    """Nhãn giọng ghi vào manifest; giọng clone chỉ ghi hash mẫu, không ghi đường dẫn/tên người."""
    if params.get("ref_audio"):
        return f"clone-{file_sha256(params['ref_audio'])[:12]}"
    if params.get("path"):
        return "files"
    return str(params.get("voice") or params.get("voice_id") or "")


def synth_dataset(source: dict, out_dir: Path, *, engine: str, config: dict, cache_dir: Path,
                  channel: str = "phone", snr_db: float = 10.0, seed: int = 7,
                  noise: np.ndarray | None = None, only: set[str] | None = None, add_noise: bool = True,
                  provenance: dict | None = None) -> dict:
    """``add_noise=False``: bỏ trộn nhiễu cả với hội thoại ``noisy`` (bản sạch để nghe thử/so sánh).

    ``provenance``: nguồn của dataset (file kịch bản + hash, file nhiễu…) ghi nguyên vào ``manifest.json``.
    Manifest luôn có ``ground_truth_sha256`` để run ASR ghi lại và ``eval`` kiểm đúng cặp run–dataset;
    engine ``files`` ghi thêm ``clips`` (thư mục hội thoại/tên file + sha256 từng clip đã dùng).
    """
    dialogues = [d for d in source["dialogues"] if not only or d["id"] in only]
    rows = plan(dialogues, engine, config)
    rng = np.random.default_rng(seed)
    out_dir = Path(out_dir)
    sr = au.SAMPLE_RATE
    manifest = {"engine": engine, "channel": channel, "snr_db_noisy": snr_db if add_noise else None, "seed": seed,
                "pronounce": config.get(engine, {}).get("pronounce", {}), **(provenance or {}), "dialogues": []}
    new_chars = 0
    for dialogue in dialogues:
        pieces, segments, cursor = [au.silence(0.3)], [], 0.3
        for row in (r for r in rows if r["dialogue"] == dialogue["id"]):
            clip, cached = synth_text(row["text"], engine, row["params"], cache_dir)
            new_chars += 0 if cached else len(row["text"])
            clip = au.peak_normalize(au.trim(clip))
            gap = float(rng.uniform(0.25, 0.8))
            start, end = cursor, cursor + clip.size / sr
            segments.append({"idx": row["idx"], "speaker": row["speaker"], "start": round(start, 3),
                             "end": round(end, 3), "voice_key": row["voice_key"]})
            pieces += [clip, au.silence(gap)]
            cursor = end + gap
        mix = np.concatenate(pieces)
        if dialogue.get("noisy") and add_noise:
            mix = au.add_noise(mix, snr_db, rng, noise)
        if channel == "phone":
            mix = au.telephone(mix)
        mix = au.peak_normalize(mix)
        au.write_wav(out_dir / "audio" / f"{dialogue['id']}.wav", mix)
        with open(out_dir / "audio" / f"{dialogue['id']}.segments.json", "w", encoding="utf-8") as fh:
            json.dump({"id": dialogue["id"], "segments": segments}, fh, ensure_ascii=False, indent=1)
        manifest["dialogues"].append({"id": dialogue["id"], "duration_s": round(mix.size / sr, 2),
                                      "noisy": bool(dialogue.get("noisy")),
                                      "noise_added": bool(dialogue.get("noisy")) and add_noise,
                                      "n_turns": len(segments)})
    ground_truth = {k: v for k, v in source.items() if k != "dialogues"}
    ground_truth["dialogues"] = [with_full_text(d) for d in dialogues]
    with open(out_dir / "ground_truth.json", "w", encoding="utf-8") as fh:
        json.dump(ground_truth, fh, ensure_ascii=False, indent=1)
    manifest["ground_truth_sha256"] = text_sha256(out_dir / "ground_truth.json")
    manifest["new_chars_synthesized"] = new_chars
    manifest["voices"] = sorted({(r["speaker"], r["voice_key"], _voice_label(r["params"])) for r in rows})
    if engine == "files":
        manifest["clips"] = [{"dialogue": r["dialogue"], "idx": r["idx"],
                              "file": f"{Path(r['params']['path']).parent.name}/{Path(r['params']['path']).name}",
                              "sha256": file_sha256(r["params"]["path"])} for r in rows]
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1, default=list)
    return manifest


# ---------------------------------------------------------------------------
# Liệt kê / thêm giọng
# ---------------------------------------------------------------------------

def list_edge_voices(locale_prefix: str = "vi-") -> list[dict]:
    import edge_tts

    voices = asyncio.run(edge_tts.list_voices())
    return [{"voice": v["ShortName"], "gender": v["Gender"], "locale": v["Locale"]}
            for v in voices if v["Locale"].startswith(locale_prefix)]


def list_eleven_shared(api_key: str, *, language: str = "vi", accent: str | None = None,
                       gender: str | None = None, page_size: int = 30) -> list[dict]:
    query = {"language": language, "page_size": page_size}
    if accent:
        query["accent"] = accent
    if gender:
        query["gender"] = gender
    payload = json.loads(eleven_request("GET", "/v1/shared-voices", api_key, query=query))
    return [{"voice_id": v.get("voice_id"), "public_owner_id": v.get("public_owner_id"), "name": v.get("name"),
             "gender": v.get("gender"), "accent": v.get("accent"), "age": v.get("age"),
             "use_case": v.get("use_case"), "free_users_allowed": v.get("free_users_allowed")}
            for v in payload.get("voices", [])]


def add_eleven_shared(api_key: str, public_owner_id: str, voice_id: str, new_name: str) -> dict:
    return json.loads(eleven_request("POST", f"/v1/voices/add/{public_owner_id}/{voice_id}", api_key,
                                     {"new_name": new_name}))
