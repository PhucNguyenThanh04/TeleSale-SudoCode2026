"""Exercise TTS -> VAD -> STT on actual model weights, without storing audio."""

import os
import json
from pathlib import Path

from .models import Models, read_wav


if __name__ == "__main__":
    models = Models(Path(os.getenv("SPEECH_MODEL_DIR", "models")))
    audio, tts_debug = models.synthesize("Xin chào, em tư vấn máy lọc không khí cho chị ạ.", "khanh_vy")
    result = models.transcribe(read_wav(audio))
    print(json.dumps({"tts": tts_debug, "stt": result}, ensure_ascii=True))
