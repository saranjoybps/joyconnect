#!/usr/bin/env bash
# Optional: expose ONLY the API's OAuth callback over public HTTPS with cloudflared.
# Off by default. Needed for providers that reject http://localhost redirect URIs (Slack, Meta).
#
#   scripts/dev-tunnel.sh                      quick tunnel (random https://<words>.trycloudflare.com)
#   TUNNEL_HOSTNAME=api.example.com \
#   TUNNEL_NAME=connect-dev scripts/dev-tunnel.sh   named tunnel (stable hostname; see README)
#
# It writes PUBLIC_API_BASE_URL into apps/api/.env.local and removes it again on exit.
# Quick tunnels do not support Server-Sent Events, so chat/SSE keeps using API_BASE_URL
# (http://localhost:8000); only OAuth redirect URIs use PUBLIC_API_BASE_URL.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/apps/api/.env.local"
API_PORT="${API_PORT:-8000}"
LOG="$(mktemp -t cloudflared.XXXXXX)"

if ! command -v cloudflared >/dev/null 2>&1; then
  cat >&2 <<'MSG'
cloudflared is not installed. This script never installs anything; install it yourself:

  macOS:    brew install cloudflared
  Linux:    https://pkg.cloudflare.com/ (apt/yum repos) or download a binary from
            https://github.com/cloudflare/cloudflared/releases/latest
  Windows:  winget install --id Cloudflare.cloudflared
            (or scripts\dev-tunnel.ps1 after installing)

Then run this script again.
MSG
  exit 1
fi

set_public_url() {  # write/replace PUBLIC_API_BASE_URL in apps/api/.env.local
  touch "$ENV_FILE"
  grep -v '^PUBLIC_API_BASE_URL=' "$ENV_FILE" > "$ENV_FILE.tmp" || true
  echo "PUBLIC_API_BASE_URL=$1" >> "$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"
  touch "$ROOT/apps/api/app/core/config.py"   # nudges `uvicorn --reload` to restart and re-read it
}

cleanup() {
  [[ -n "${CF_PID:-}" ]] && kill "$CF_PID" 2>/dev/null || true
  if [[ -f "$ENV_FILE" ]]; then
    grep -v '^PUBLIC_API_BASE_URL=' "$ENV_FILE" > "$ENV_FILE.tmp" || true
    mv "$ENV_FILE.tmp" "$ENV_FILE"
    touch "$ROOT/apps/api/app/core/config.py"
  fi
  rm -f "$LOG"
  echo "Tunnel stopped; PUBLIC_API_BASE_URL removed (redirect URIs are back to localhost)."
}
trap cleanup EXIT INT TERM

if [[ -n "${TUNNEL_HOSTNAME:-}" ]]; then
  # Named tunnel: stable hostname, created once with `cloudflared tunnel create` + `route dns`.
  URL="https://${TUNNEL_HOSTNAME}"
  cloudflared tunnel run ${TUNNEL_NAME:+"$TUNNEL_NAME"} >"$LOG" 2>&1 &
  CF_PID=$!
else
  cloudflared tunnel --url "http://localhost:${API_PORT}" >"$LOG" 2>&1 &
  CF_PID=$!
  URL=""
  for _ in $(seq 1 60); do
    URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -n1 || true)"
    [[ -n "$URL" ]] && break
    kill -0 "$CF_PID" 2>/dev/null || { echo "cloudflared exited early:" >&2; cat "$LOG" >&2; exit 1; }
    sleep 0.5
  done
  [[ -n "$URL" ]] || { echo "Timed out waiting for the trycloudflare.com URL:" >&2; cat "$LOG" >&2; exit 1; }
fi

set_public_url "$URL"

echo
echo "PUBLIC_API_BASE_URL=$URL   (written to apps/api/.env.local)"
echo "If your API is not running with --reload, restart it now so it picks this up."
echo
echo "Register these redirect URIs in each provider's console:"
for fam in google slack notion github meta; do
  echo "  $fam: $URL/api/oauth/callback/$fam"
done
echo
echo "Chat/SSE still goes to http://localhost:${API_PORT}. Press Ctrl+C to stop the tunnel."
wait "$CF_PID"
