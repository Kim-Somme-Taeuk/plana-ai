#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[collector-smoke] collector targeted tests"
backend/.venv/bin/pytest \
  collector/tests/test_adb_capture.py \
  collector/tests/test_capture_import.py \
  collector/tests/test_run_capture_pipeline.py \
  -q

echo "[collector-smoke] capture_import help"
backend/.venv/bin/python collector/capture_import.py --help >/dev/null

echo "[collector-smoke] adb_capture help"
backend/.venv/bin/python collector/adb_capture.py --help >/dev/null

echo "[collector-smoke] run_capture_pipeline help"
backend/.venv/bin/python collector/run_capture_pipeline.py --help >/dev/null

echo "[collector-smoke] ok"
