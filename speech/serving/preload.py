"""Download and initialize all model assets before opening the service port."""

import os
from pathlib import Path

from .models import Models


if __name__ == "__main__":
    Models(Path(os.getenv("SPEECH_MODEL_DIR", "models")))
    print("MODELS_READY")
