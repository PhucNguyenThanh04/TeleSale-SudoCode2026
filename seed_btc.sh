#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if [ ! -f .env ]; then
  printf '%s\n' 'Place the completed .env in the repository root first.' >&2
  exit 1
fi
export SUBMISSION_RUN_AS="${SUBMISSION_RUN_AS:-$(id -u):$(id -g)}"
docker compose --env-file .env -f compose.submission.yml run --rm seed
docker compose --env-file .env -f compose.submission.yml up -d --wait --wait-timeout 180
