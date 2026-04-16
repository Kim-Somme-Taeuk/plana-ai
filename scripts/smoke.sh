#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"
SMOKE_SNAPSHOT_ID="${SMOKE_SNAPSHOT_ID:-41}"
SMOKE_SEASON_ID="${SMOKE_SEASON_ID:-33}"
SMOKE_COMPARE_SEASON_ID="${SMOKE_COMPARE_SEASON_ID:-18}"
SMOKE_COMPARE_LEFT_ID="${SMOKE_COMPARE_LEFT_ID:-24}"
SMOKE_COMPARE_RIGHT_ID="${SMOKE_COMPARE_RIGHT_ID:-25}"

retry_curl() {
  local url="$1"
  local attempts="${2:-20}"
  local delay="${3:-1}"

  for ((i=1; i<=attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done

  echo "[smoke] failed after retries: $url" >&2
  return 1
}

echo "[smoke] docker compose up -d --build"
docker compose up -d --build >/dev/null

echo "[smoke] backend health"
retry_curl "$BACKEND_URL/health"

echo "[smoke] backend snapshot validation report"
retry_curl "$BACKEND_URL/ranking-snapshots/$SMOKE_SNAPSHOT_ID/validation-report"

echo "[smoke] backend season validation overview"
retry_curl "$BACKEND_URL/seasons/$SMOKE_SEASON_ID/validation-overview"

echo "[smoke] backend season validation series"
retry_curl "$BACKEND_URL/seasons/$SMOKE_SEASON_ID/validation-series"

echo "[smoke] frontend root"
retry_curl "$FRONTEND_URL/"

echo "[smoke] frontend season detail"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_SEASON_ID"

echo "[smoke] frontend season collector filter"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_SEASON_ID?collector=with_diagnostics"

echo "[smoke] frontend season compare"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_COMPARE_SEASON_ID?compareLeft=$SMOKE_COMPARE_LEFT_ID&compareRight=$SMOKE_COMPARE_RIGHT_ID"

echo "[smoke] frontend snapshot detail"
retry_curl "$FRONTEND_URL/snapshots/$SMOKE_SNAPSHOT_ID?validationIssue=low_ocr_confidence&limit=50&offset=0"

echo "[smoke] ok"
