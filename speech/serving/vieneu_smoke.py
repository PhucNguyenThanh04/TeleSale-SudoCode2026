"""Load VieNeu Turbo on CPU and check a real preset voice."""

import json
import os
import time

import numpy as np


if __name__ == "__main__":
    os.environ.setdefault("HF_HOME", "H:/TeleSaleVieNeu/hf-cache")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    from vieneu import Vieneu

    started = time.perf_counter()
    model = Vieneu(mode="v3turbo", backend="onnx")
    load_ms = round((time.perf_counter() - started) * 1000)
    voices = model.list_preset_voices()
    voice_ids = [voice_id for _, voice_id in voices]
    assert "Trúc Ly" in voice_ids, voice_ids
    started = time.perf_counter()
    audio = np.asarray(model.infer("Dạ em chào chị, em có thể tư vấn máy lọc không khí cho mình ạ.", voice="Trúc Ly"), dtype=np.float32).reshape(-1)
    infer_ms = round((time.perf_counter() - started) * 1000)
    assert len(audio) > 48_000
    print(json.dumps({"ready": True, "mode": "v3turbo", "backend": "onnx", "voice_count": len(voices), "load_ms": load_ms, "infer_ms": infer_ms, "audio_s": round(len(audio) / 48_000, 3)}, ensure_ascii=True))
