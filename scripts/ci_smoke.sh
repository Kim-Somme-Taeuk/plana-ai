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

  echo "[ci-smoke] failed after retries: $url" >&2
  return 1
}

echo "[ci-smoke] docker compose up -d --build"
docker compose up -d --build >/dev/null

echo "[ci-smoke] backend health"
retry_curl "$BACKEND_URL/health"

echo "[ci-smoke] seed smoke data"
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

echo "[ci-smoke] backend validation report"
retry_curl "$BACKEND_URL/ranking-snapshots/$SMOKE_SNAPSHOT_ID/validation-report"

echo "[ci-smoke] backend season validation overview"
retry_curl "$BACKEND_URL/seasons/$SMOKE_SEASON_ID/validation-overview"

echo "[ci-smoke] backend season validation series"
retry_curl "$BACKEND_URL/seasons/$SMOKE_SEASON_ID/validation-series?collector_filter=with_diagnostics"

echo "[ci-smoke] backend season validation reason filters"
retry_curl "$BACKEND_URL/seasons/$SMOKE_SEASON_ID/validation-overview?collector_filter=capture_stop&capture_stop_reason=noisy_last_page"
retry_curl "$BACKEND_URL/seasons/$SMOKE_SEASON_ID/validation-series?ocr_stop_reason=sparse_last_page"
retry_curl "$BACKEND_URL/seasons/$SMOKE_SEASON_ID/validation-overview?ignored_reason=blank_line&ocr_stop_level=soft"

echo "[ci-smoke] frontend root"
retry_curl "$FRONTEND_URL/"

echo "[ci-smoke] frontend season detail"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_SEASON_ID"

echo "[ci-smoke] frontend season collector filter"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_SEASON_ID?collector=with_diagnostics"

echo "[ci-smoke] frontend season reason drilldown"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_SEASON_ID?collector=capture_stop&captureStopReason=noisy_last_page"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_SEASON_ID?collector=with_diagnostics&ignoredReason=blank_line&ocrStopLevel=soft"

echo "[ci-smoke] frontend season compare"
retry_curl "$FRONTEND_URL/seasons/$SMOKE_SEASON_ID?compareLeft=$SMOKE_COMPARE_LEFT_ID&compareRight=$SMOKE_COMPARE_RIGHT_ID&collector=with_diagnostics"

echo "[ci-smoke] frontend snapshot detail"
retry_curl "$FRONTEND_URL/snapshots/$SMOKE_SNAPSHOT_ID?validationIssue=low_ocr_confidence&isValid=false"

echo "[ci-smoke] ok"
