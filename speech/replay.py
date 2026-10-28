"""Customer-only offline replay. Dataset speaker boundaries are annotations, not diarization."""
from __future__ import annotations

import json
import math
import re
import shutil
import time
from dataclasses import asdict
from collections.abc import Callable
from datetime import date
from pathlib import Path

import numpy as np

from . import audio as au
from .asr import DecodeConfig, VadConfig, decode_segments, finalize, hotword_filter_terms, load_model
from .baseline import new_directory, runtime_fingerprint, write_json
from .btc import load_catalog, read_json, read_json_object, text_sha256
from .normalize import default_lexicon
from .tts import file_sha256

SESSION_FIELDS = {"dataset", "dialogue_id", "conversation_key", "session_key", "session_index",
                  "identity_ref", "call_date"}
TURN_FIELDS = {"conversation_key", "session_key", "session_index", "identity_ref", "call_date",
               "turn_index", "source_turn_index", "text", "customer_input_mode", "audio_sha256"}
BOUNDARY_PAD_S = 0.3


def _key(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", value):
        raise ValueError("Keys must contain 1-100 ASCII letters, digits, underscores or hyphens")
    return value


def validate_sessions(mapping: dict) -> list[dict]:
    if (not isinstance(mapping, dict) or set(mapping) != {"schema_version", "sessions"}
            or type(mapping["schema_version"]) is not int or mapping["schema_version"] != 1):
        raise ValueError("Expected replay mapping schema_version=1 and sessions")
    sessions = mapping["sessions"]
    if not isinstance(sessions, list) or not sessions:
        raise ValueError("At least one mapped session is required")
    seen, conversations = set(), {}
    for session in sessions:
        if not isinstance(session, dict) or set(session) != SESSION_FIELDS:
            raise ValueError("Missing/extra session fields; labels and answers are not accepted")
        for name in ("dialogue_id", "conversation_key", "session_key", "identity_ref"):
            _key(session[name])
        if not isinstance(session["dataset"], str) or not session["dataset"].strip():
            raise ValueError("Dataset path is required")
        if not isinstance(session["call_date"], str):
            raise ValueError("call_date must be an ISO date")
        on = date.fromisoformat(session["call_date"])
        if on.isoformat() != session["call_date"]:
            raise ValueError("call_date must be YYYY-MM-DD")
        index = session["session_index"]
        if type(index) is not int or index < 1 or session["session_key"] in seen:
            raise ValueError("Session index must be positive and session keys unique")
        seen.add(session["session_key"])
        conv = session["conversation_key"]
        previous = conversations.get(conv)
        if previous is not None:
            if (index != previous["session_index"] + 1 or session["call_date"] < previous["call_date"]
                    or session["identity_ref"] != previous["identity_ref"]):
                raise ValueError("Conversation sessions must be ordered with the same identity reference")
        elif index != 1:
            raise ValueError("First session_index must be 1")
        conversations[conv] = session
    return sessions


def customer_segments(payload: dict, duration_s: float) -> list[dict]:
    if not isinstance(payload, dict) or not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("Invalid segment payload/audio duration")
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Missing annotated segments")
    selected, previous_end, previous_idx = [], 0.0, 0
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("Expected segment object")
        idx, speaker = segment.get("idx"), segment.get("speaker")
        start, end = segment.get("start"), segment.get("end")
        if (type(idx) is not int or idx <= previous_idx or speaker not in ("A", "C")
                or type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or not (previous_end <= start < end <= duration_s)):
            raise ValueError("Invalid/overlapping/out-of-bounds annotated segment")
        previous_end, previous_idx = end, idx
        if speaker == "C":
            selected.append({"idx": idx, "start": start, "end": end})
    if not selected:
        raise ValueError("Session contains no annotated customer turns")
    return selected


def _seal(out: Path, kind: str, files: list[Path], metadata: dict) -> dict:
    manifest = {"schema_version": 1, "kind": kind, "segmentation_source": "dataset_annotation",
                "files": {str(p.relative_to(out)): file_sha256(p) for p in files}, **metadata}
    write_json(out / "manifest.json", manifest)
    return manifest


def verify_bundle(out: Path, expected_kind: str | None = None) -> dict:
    manifest = read_json_object(out / "manifest.json")
    if (manifest.get("schema_version") != 1 or manifest.get("kind") not in ("prepared", "replay")
            or (expected_kind and manifest["kind"] != expected_kind)):
        raise ValueError("Unsupported replay bundle kind/version")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Missing bundle files")
    root = out.resolve()
    for name, digest in files.items():
        path = (out / name).resolve()
        if not path.is_relative_to(root) or file_sha256(path) != digest:
            raise ValueError("Bundle file missing, outside root, or hash mismatch")
    if manifest["kind"] == "prepared":
        if "clips.json" not in files:
            raise ValueError("Missing clips metadata")
        clips = read_json(out / "clips.json")
        if not isinstance(clips, list) or not clips or len(clips) != manifest.get("turn_count"):
            raise ValueError("Clip count mismatch")
        seen = set()
        for clip in clips:
            key = _key(clip["clip_key"])
            name = str(Path("audio") / f"{key}.wav")
            if key in seen or name not in files or files[name] != clip["audio_sha256"]:
                raise ValueError("Clip identity/hash mismatch")
            seen.add(key)
        validate_turns([{**{k: clip[k] for k in TURN_FIELDS if k in clip},
                         "text": "pending ASR", "customer_input_mode": "asr_transcript"} for clip in clips])
    else:
        if "turns.jsonl" not in files or manifest.get("status") != "ready":
            raise ValueError("Replay is not ready")
        turns = [json.loads(line) for line in (out / "turns.jsonl").read_text(encoding="utf-8").splitlines()]
        validate_turns(turns)
        if len(turns) != manifest.get("turn_count"):
            raise ValueError("Turn count mismatch")
        for turn in turns:
            name = str(Path("audio") / f"{turn['session_key']}-{turn['source_turn_index']}.wav")
            if files.get(name) != turn["audio_sha256"]:
                raise ValueError("Replay turn references an unverified audio clip")
    return manifest


def prepare_replay(mapping_path: Path, out: Path) -> dict:
    mapping = read_json_object(mapping_path)
    sessions = validate_sessions(mapping)
    prepared = []
    sources = []
    # Validate all inputs before creating output or writing any clips.
    for session in sessions:
        dataset = Path(session["dataset"])
        if not dataset.is_absolute():
            dataset = mapping_path.parent / dataset
        audio_path = dataset / "audio" / f"{session['dialogue_id']}.wav"
        segments_path = audio_path.with_suffix(".segments.json")
        payload = read_json_object(segments_path)
        if payload.get("id") != session["dialogue_id"]:
            raise ValueError("Segment dialogue ID mismatch")
        audio = au.decode(audio_path)
        segments = customer_segments(payload, audio.size / au.SAMPLE_RATE)
        prepared.append((session, audio, segments))
        sources.append({"session_key": session["session_key"], "audio_sha256": file_sha256(audio_path),
                        "segments_sha256": text_sha256(segments_path)})
    new_directory(out)
    clips, files = [], []
    for session, audio, segments in prepared:
        for index, segment in enumerate(segments, 1):
            key = f"{session['session_key']}-{segment['idx']}"
            path = out / "audio" / f"{key}.wav"
            start, end = (round(segment[k] * au.SAMPLE_RATE) for k in ("start", "end"))
            if start >= end:
                raise ValueError("Segment is shorter than one audio sample")
            # Tight speech-onset crops can make VAD miss a voiced clip. Keep silence at both edges,
            # as in the original synthetic recordings, without borrowing neighbouring speaker audio.
            padded = np.concatenate((au.silence(BOUNDARY_PAD_S), audio[start:end], au.silence(BOUNDARY_PAD_S)))
            au.write_wav(path, padded)
            clips.append({k: session[k] for k in ("conversation_key", "session_key", "session_index",
                                                "identity_ref", "call_date")})
            clips[-1].update({"clip_key": key, "turn_index": index, "source_turn_index": segment["idx"],
                              "audio_sha256": file_sha256(path), "start": segment["start"], "end": segment["end"]})
            files.append(path)
    write_json(out / "clips.json", clips)
    files.append(out / "clips.json")
    return _seal(out, "prepared", files, {"turn_count": len(clips), "sources": sources,
                                         "boundary_padding_s": BOUNDARY_PAD_S,
                                         "mapping_sha256": text_sha256(mapping_path)})


def validate_turns(turns: list[dict]) -> None:
    if not turns:
        raise ValueError("Replay has no turns")
    sessions, conversations, closed = {}, {}, set()
    previous_session = None
    for turn in turns:
        if not isinstance(turn, dict) or set(turn) != TURN_FIELDS:
            raise ValueError("Unexpected turn fields; only the replay contract is allowed")
        for name in ("conversation_key", "session_key", "identity_ref"):
            _key(turn[name])
        text = turn["text"]
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 8000:
            raise ValueError("ASR text must contain 1-8000 characters; no truncation/fallback")
        if turn["customer_input_mode"] != "asr_transcript":
            raise ValueError("Replay input mode must be asr_transcript")
        if not isinstance(turn["audio_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", turn["audio_sha256"]):
            raise ValueError("Missing/invalid audio digest")
        session = turn["session_key"]
        for name in ("turn_index", "source_turn_index", "session_index"):
            if type(turn[name]) is not int or turn[name] < 1:
                raise ValueError("Turn/session indices must be positive integers")
        if not isinstance(turn["call_date"], str) or date.fromisoformat(turn["call_date"]).isoformat() != turn["call_date"]:
            raise ValueError("Invalid call_date")
        if session != previous_session:
            if session in closed:
                raise ValueError("Interleaved/repeated sessions are not supported")
            if previous_session:
                closed.add(previous_session)
            previous_session = session
        previous = sessions.get(session)
        if previous is not None:
            if (turn["turn_index"] != previous["turn_index"] + 1
                    or turn["source_turn_index"] <= previous["source_turn_index"]
                    or any(turn[k] != previous[k] for k in
                           ("identity_ref", "conversation_key", "session_index", "call_date"))):
                raise ValueError("Turn order or session metadata changed")
        else:
            conv = conversations.get(turn["conversation_key"])
            if turn["turn_index"] != 1:
                raise ValueError("First turn_index must be 1")
            if conv is not None:
                if (turn["session_index"] != conv["session_index"] + 1
                        or turn["identity_ref"] != conv["identity_ref"] or turn["call_date"] < conv["call_date"]):
                    raise ValueError("Conversation session order/identity changed")
            elif turn["session_index"] != 1:
                raise ValueError("First session_index must be 1")
            conversations[turn["conversation_key"]] = turn
        sessions[session] = turn


def export_replay(prepared: Path, out: Path, data_dir: Path, *, model_name: str = "whisper-turbo",
                  device: str = "cpu", compute_type: str = "int8",
                  progress: Callable[..., None] = print) -> dict:
    source = verify_bundle(prepared, "prepared")
    clips = read_json(prepared / "clips.json")
    if not isinstance(clips, list):
        raise ValueError("Expected clips list")
    new_directory(out)
    catalog, lexicon = load_catalog(data_dir), default_lexicon()
    cfg, vad = DecodeConfig(), VadConfig()
    fingerprint = runtime_fingerprint(model_name)
    model, used_device, used_type = load_model(model_name, device, compute_type)
    turns, errors, diagnostics, files = [], [], [], []
    raw_records = {}
    for clip in clips:
        key = clip["clip_key"]
        src = prepared / "audio" / f"{key}.wav"
        dst = out / "audio" / f"{key}.wav"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        files.append(dst)
        audio = au.decode(src)
        started = time.perf_counter()
        raw = decode_segments(model, audio, cfg=cfg, vad=vad, lexicon=lexicon)
        record = finalize(raw, lexicon, catalog, date.fromisoformat(clip["call_date"]),
                          hotword_filter_terms(lexicon, cfg))
        text = " ".join(s["text_written"] for s in record["asr_segments"]).strip()
        diagnostics.append({"clip_key": key, "audio_s": audio.size / au.SAMPLE_RATE,
                            "asr_s": time.perf_counter() - started, "text_length": len(text)})
        raw_records[key] = raw
        turn = {k: clip[k] for k in TURN_FIELDS if k in clip}
        turn.update({"text": text, "customer_input_mode": "asr_transcript"})
        if not 1 <= len(text) <= 8000:
            errors.append(key)
        turns.append(turn)
        progress(f"{key}: {len(record['asr_segments'])} ASR segments", flush=True)
    write_json(out / "diagnostics.json", {"turns": diagnostics, "invalid_text_clips": errors})
    write_json(out / "run" / "raw.json", {"schema_version": 1, "records": raw_records})
    if errors:
        raise ValueError(f"Replay not exported: invalid/empty text in {len(errors)} clips; see diagnostics.json")
    validate_turns(turns)
    write_json(out / "run" / "run.json", {"frozen": True, "profile": "B2", "decode": asdict(cfg),
                                        "vad": asdict(vad), "model": model_name, "device": used_device,
                                        "compute_type": used_type, "fingerprint": fingerprint,
                                        "replay_code_sha256": text_sha256(Path(__file__)),
                                        "catalog_sha256": text_sha256(data_dir / "catalog" / "products.json")})
    (out / "turns.jsonl").write_text(
        "".join(json.dumps(t, ensure_ascii=False, allow_nan=False) + "\n" for t in turns), encoding="utf-8")
    files += [out / "turns.jsonl", out / "diagnostics.json", out / "run" / "run.json"]
    manifest = _seal(out, "replay", files, {"status": "ready", "turn_count": len(turns),
                    "prepared_manifest_sha256": file_sha256(prepared / "manifest.json"),
                    "mapping_sha256": source["mapping_sha256"],
                    "privacy": "Local controlled synthetic/consented data only. Review before sharing."})
    verify_bundle(out, "replay")
    return manifest
