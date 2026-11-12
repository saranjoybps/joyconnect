#!/usr/bin/env bash
# Health-check every connected account (no LLM calls). Usage: scripts/check-connections.sh [--user ID] [--provider ID]
set -euo pipefail
cd "$(dirname "$0")/../apps/api"
PY=".venv/Scripts/python.exe"; [ -x "$PY" ] || PY=".venv/bin/python"
exec "$PY" -m app.cli.check_connections "$@"
