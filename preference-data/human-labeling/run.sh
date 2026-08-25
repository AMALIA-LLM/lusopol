#!/usr/bin/env bash
# Start the labeling app with its data on local disk (WAL-capable, unlike /mnt/home).
set -euo pipefail
cd "$(dirname "$0")"
export LABELING_DB="${LABELING_DB:-/mnt/scratch-artemis/giuseppe/lusopol/labeling/annotations.db}"
export PORT="${PORT:-8000}"
echo "database: $LABELING_DB"
exec .venv/bin/waitress-serve --host 0.0.0.0 --port "$PORT" app:app
