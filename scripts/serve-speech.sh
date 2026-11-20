#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PYTHON="$PWD/.venv-speech-serving/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo 'Create .venv-speech-serving and install speech/serving/requirements.txt plus vieneu first.' >&2
  exit 1
fi
"$PYTHON" - <<'PY'
import socket
for port in (18110, 18111):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))
PY
export SPEECH_MODEL_DIR="${SPEECH_MODEL_DIR:-$PWD/speech/serving/models}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-4}"
pids=()
cleanup() {
  trap - EXIT INT TERM
  kill "${pids[@]}" 2>/dev/null || true
  wait "${pids[@]}" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$PYTHON" -m uvicorn speech.serving.vieneu_sidecar:app --host 127.0.0.1 --port 18111 &
pids+=("$!")
"$PYTHON" -m uvicorn speech.serving.app:app --host 127.0.0.1 --port 18110 &
pids+=("$!")
wait -n "${pids[@]}"
