#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example to .env and configure it first." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a
exec uv run uvicorn lab.api:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8765}"
