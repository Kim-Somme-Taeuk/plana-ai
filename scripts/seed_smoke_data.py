#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="빈 환경 smoke 검증용 season/snapshot 데이터를 backend API로 생성합니다.",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="backend API base URL",
    )
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    seed_suffix = str(int(time.time()))
    started_at = datetime.now(UTC)
    ended_at = started_at + timedelta(days=7)

    season = request_json(
        base_url,
        "POST",
        "/seasons",
        {
            "event_type": "grand_assault",
            "server": "global",
            "boss_name": "Kaiten FX",
            "armor_type": "light",
            "terrain": "urban",
            "season_label": f"ci-smoke-season-{seed_suffix}",
            "started_at": started_at.isoformat().replace("+00:00", "Z"),
            "ended_at": ended_at.isoformat().replace("+00:00", "Z"),
        },
    )
    season_id = season["id"]

    left_snapshot = request_json(
        base_url,
        "POST",
        f"/seasons/{season_id}/ranking-snapshots",
        {
            "captured_at": (started_at + timedelta(hours=1)).isoformat().replace(
                "+00:00", "Z"
            ),
            "source_type": "image_tesseract",
            "note": (
                "ci smoke left snapshot\n"
                "collector: pages=2/3; capture_stop=noisy_last_page; "
                "ignored=2(non_entry_line=2); ocr_stop=noisy_last_page(hard)"
            ),
        },
    )
    right_snapshot = request_json(
        base_url,
        "POST",
        f"/seasons/{season_id}/ranking-snapshots",
        {
            "captured_at": (started_at + timedelta(hours=2)).isoformat().replace(
                "+00:00", "Z"
            ),
            "source_type": "image_sidecar",
            "note": (
                "ci smoke right snapshot\n"
                "collector: pages=3/3; ignored=1(blank_line=1); "
                "ocr_stop=sparse_last_page(soft)"
            ),
        },
    )

    create_entries(
        base_url,
        left_snapshot["id"],
        [
            {
                "rank": 1,
                "score": 9988776,
                "player_name": "Momo",
                "ocr_confidence": 0.98,
                "raw_text": "1 Momo 9988776",
                "image_path": "/ci/left/momo.png",
                "is_valid": True,
                "validation_issue": None,
            },
            {
                "rank": 10,
                "score": 9654321,
                "player_name": "Yuzu",
                "ocr_confidence": 0.41,
                "raw_text": "10 Yuzu 9654321",
                "image_path": "/ci/left/yuzu.png",
                "is_valid": True,
                "validation_issue": None,
            },
        ],
    )
    create_entries(
        base_url,
        right_snapshot["id"],
        [
            {
                "rank": 1,
                "score": 9977000,
                "player_name": "Arona",
                "ocr_confidence": 0.97,
                "raw_text": "1 Arona 9977000",
                "image_path": "/ci/right/arona.png",
                "is_valid": True,
                "validation_issue": None,
            },
            {
                "rank": 10,
                "score": 9543210,
                "player_name": "Noa",
                "ocr_confidence": 0.95,
                "raw_text": "10 Noa 9543210",
                "image_path": "/ci/right/noa.png",
                "is_valid": True,
                "validation_issue": None,
            },
            {
                "rank": 100,
                "score": 8123456,
                "player_name": "   ",
                "ocr_confidence": 0.92,
                "raw_text": "100 Mari 8123456",
                "image_path": "/ci/right/mari.png",
                "is_valid": True,
                "validation_issue": None,
            },
        ],
    )

    request_json(
        base_url,
        "PATCH",
        f"/ranking-snapshots/{left_snapshot['id']}/status",
        {"status": "completed"},
    )
    request_json(
        base_url,
        "PATCH",
        f"/ranking-snapshots/{right_snapshot['id']}/status",
        {"status": "completed"},
    )

    result = {
        "season_id": season_id,
        "snapshot_id": left_snapshot["id"],
        "compare_left_id": left_snapshot["id"],
        "compare_right_id": right_snapshot["id"],
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


def create_entries(base_url: str, snapshot_id: int, entries: list[dict[str, object]]) -> None:
    for entry in entries:
        request_json(
            base_url,
            "POST",
            f"/ranking-snapshots/{snapshot_id}/entries",
            entry,
        )


def request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request) as response:
            raw_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"API request failed: {method} {path} status={exc.code} body={body}"
        ) from exc

    return json.loads(raw_body)


if __name__ == "__main__":
    raise SystemExit(main())
