#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export OMP_NUM_THREADS=4

# Eager execution and a single sequence keep overhead low on the 4 GB GPU.
exec "$repo_root/.venv-vllm/bin/vllm" serve Qwen/Qwen3-0.6B \
  --host 127.0.0.1 \
  --port 8002 \
  --dtype half \
  --gpu-memory-utilization 0.80 \
  --max-model-len 4096 \
  --max-num-seqs 1 \
  --max-num-batched-tokens 512 \
  --enforce-eager \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --default-chat-template-kwargs '{"enable_thinking":false}' \
  "$@"
