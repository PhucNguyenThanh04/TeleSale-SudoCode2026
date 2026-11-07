"""Replace only VieNeu's cached HF snapshot symlinks with local copies for ORT."""

import os
import shutil
from pathlib import Path


REPOS = (
    "models--pnnbao-ump--VieNeu-TTS-v3-Turbo",
    "models--OpenMOSS-Team--MOSS-Audio-Tokenizer-Nano-ONNX",
)


if __name__ == "__main__":
    hub = (Path(os.environ.get("HF_HOME", "H:/TeleSaleVieNeu/hf-cache")) / "hub").resolve()
    expected = Path("H:/TeleSaleVieNeu/hf-cache/hub").resolve()
    if hub != expected:
        raise RuntimeError(f"Refusing to modify unexpected Hugging Face cache: {hub}")
    copied = 0
    for repo in REPOS:
        snapshots = (hub / repo / "snapshots").resolve()
        if not snapshots.is_relative_to(hub) or not snapshots.is_dir():
            continue
        for path in snapshots.rglob("*"):
            if not path.is_symlink():
                continue
            target = path.resolve(strict=True)
            if not target.is_file() or not target.is_relative_to(hub):
                raise RuntimeError(f"Unexpected snapshot link: {path}")
            temporary = path.with_name(path.name + ".materializing")
            shutil.copyfile(target, temporary)
            temporary.replace(path)
            copied += 1
    print(f"Materialized {copied} VieNeu snapshot links under {hub}")
