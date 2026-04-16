#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"

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

retry_backend_ready() {
  local url="$1"
  local attempts="${2:-30}"
  local delay="${3:-1}"

  for ((i=1; i<=attempts; i++)); do
    local body
    body="$(curl -fsS "$url" 2>/dev/null || true)"
    if [[ -n "$body" ]] && HEALTH_BODY="$body" python3 - <<'PY'
import json
import os
import sys

try:
    body = json.loads(os.environ["HEALTH_BODY"])
except Exception:
    sys.exit(1)

sys.exit(0 if body.get("database") is True else 1)
PY
    then
      return 0
    fi
    sleep "$delay"
  done

  echo "[smoke] backend database was not ready: $url" >&2
  return 1
}

echo "[smoke] docker compose up -d --build"
docker compose up -d --build >/dev/null

echo "[smoke] backend health"
retry_backend_ready "$BACKEND_URL/health"

echo "[smoke] apply migrations"
docker compose exec -T backend alembic upgrade head >/dev/null

echo "[smoke] backend health after migrations"
retry_backend_ready "$BACKEND_URL/health"

echo "[smoke] seed smoke data"
SEED_JSON="$(python3 scripts/seed_smoke_data.py --base-url "$BACKEND_URL")"
export SEED_JSON
SMOKE_SEASON_ID="$(python3 - <<'PY'
import json, os
print(json.loads(os.environ["SEED_JSON"])["season_id"])
PY
)"
SMOKE_SNAPSHOT_ID="$(python3 - <<'PY'
import json, os
print(json.loads(os.environ["SEED_JSON"])["snapshot_id"])
PY
)"
SMOKE_COMPARE_LEFT_ID="$(python3 - <<'PY'
import json, os
print(json.loads(os.environ["SEED_JSON"])["compare_left_id"])
PY
)"
SMOKE_COMPARE_RIGHT_ID="$(python3 - <<'PY'
import json, os
print(json.loads(os.environ["SEED_JSON"])["compare_right_id"])
PY
)"

echo "[smoke] backend snapshot validation report"
retry_curl "$BACKEND_URL/ranking-snapshots/$SMOKE_SNAPSHOT_ID/validation-report"

echo "[smoke] backend season validation overview"
retry_curl "$BACKEND_URL/seasons/$SMOKE_SEASON_ID/validation-overview"

echo "[smoke] backend season validation series"
retry_curl "$BACKEND_URL/seasons/$SMOKE_SEASON_ID/validation-series?collector_filter=with_diagnostics"

echo "[smoke] backend season validation reason filters"
retry_curl "$BACKEND_URL/seasons/$SMOKE_SEASON_ID/validation-overview?collector_filter=capture_stop&capture_stop_reason=noisy_last_page"
retry_curl "$BACKEND_URL/seasons/$SMOKE_SEASON_ID/validation-series?ocr_stop_reason=sparse_last_page"
retry_curl "$BACKEND_URL/seasons/$SMOKE_SEASON_ID/validation-overview?ignored_reason=blank_line&ocr_stop_level=soft"

echo "[smoke] frontend root"
retry_curl "$FRONTEND_URL/"

echo "[smoke] frontend season detail"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_SEASON_ID"

echo "[smoke] frontend season collector filter"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_SEASON_ID?collector=with_diagnostics"

echo "[smoke] frontend season reason drilldown"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_SEASON_ID?collector=capture_stop&captureStopReason=noisy_last_page"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_SEASON_ID?collector=with_diagnostics&ignoredReason=blank_line&ocrStopLevel=soft"

echo "[smoke] frontend season compare"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_SEASON_ID?compareLeft=$SMOKE_COMPARE_LEFT_ID&compareRight=$SMOKE_COMPARE_RIGHT_ID&collector=with_diagnostics"

echo "[smoke] frontend snapshot detail"
retry_curl "$FRONTEND_URL/snapshots/$SMOKE_SNAPSHOT_ID?validationIssue=low_ocr_confidence&isValid=false"

echo "[smoke] ok"
