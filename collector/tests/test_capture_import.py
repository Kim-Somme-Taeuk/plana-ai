from __future__ import annotations

import json
from pathlib import Path

import pytest

from collector.capture_import import (
    build_mock_payload_from_capture,
    import_capture_payload,
    load_capture_import_payload,
)
from collector.mock_import import MockImportError


def test_load_capture_import_payload_reads_manifest_directory(tmp_path: Path) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tPlana\t12345678\t0.99\n10\tArona\t12000000\t0.97\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-test-season",
        pages=[
            {
                "image_path": "page-001.png",
            }
        ],
    )

    payload = load_capture_import_payload(tmp_path)

    assert payload.season["season_label"] == "capture-test-season"
    assert payload.snapshot["captured_at"] == "2026-04-16T10:00:00Z"
    assert payload.pages[0].image_path == "page-001.png"


def test_build_mock_payload_from_capture_parses_entries_and_keeps_invalid_candidate(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tPlana\t12345678\t0.99\n1000\t   \t8123456\t0.91\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-build-test-season",
        pages=[
            {
                "image_path": "page-001.png",
            }
        ],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert len(mock_payload.entries) == 2
    assert mock_payload.entries[0]["rank"] == 1
    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] == 0.99
    assert mock_payload.entries[1]["player_name"] == "   "


def test_import_capture_payload_calls_api_in_order(tmp_path: Path) -> None:
    class FakeApiClient:
        def __init__(self):
            self.calls: list[tuple[str, dict[str, object] | str]] = []

        def create_season(self, payload):
            self.calls.append(("create_season", payload))
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            self.calls.append(("create_snapshot", {"season_id": season_id, **payload}))
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            self.calls.append(("create_entry", {"snapshot_id": snapshot_id, **payload}))
            return {"id": len([call for call in self.calls if call[0] == "create_entry"])}

        def update_snapshot_status(self, snapshot_id, status):
            self.calls.append(
                ("update_snapshot_status", {"snapshot_id": snapshot_id, "status": status})
            )
            return {
                "id": snapshot_id,
                "status": status,
                "total_rows_collected": 2,
            }

    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tPlana\t12345678\t0.99\n10\tArona\t12000000\t0.97\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-import-test-season",
        pages=[
            {
                "image_path": "page-001.png",
            }
        ],
    )

    payload = load_capture_import_payload(tmp_path)
    client = FakeApiClient()

    result = import_capture_payload(payload, client)

    assert result.season_id == 101
    assert result.snapshot_id == 202
    assert result.status == "completed"
    assert result.total_rows_collected == 2
    assert [call[0] for call in client.calls] == [
        "create_season",
        "create_snapshot",
        "create_entry",
        "create_entry",
        "update_snapshot_status",
    ]


def test_build_mock_payload_from_capture_rejects_duplicate_ranks(tmp_path: Path) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tPlana\t12345678\t0.99\n",
    )
    _write_capture_page(
        tmp_path,
        "page-002.png",
        "1\tArona\t12000000\t0.97\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-duplicate-rank-season",
        pages=[
            {
                "image_path": "page-001.png",
            },
            {
                "image_path": "page-002.png",
            },
        ],
    )

    payload = load_capture_import_payload(tmp_path)

    with pytest.raises(MockImportError) as exc_info:
        build_mock_payload_from_capture(payload)

    assert "duplicate_rank" in str(exc_info.value)


def _write_capture_manifest(
    base_dir: Path,
    *,
    season_label: str,
    pages: list[dict[str, object]],
) -> None:
    manifest = {
        "season": {
            "event_type": "total_assault",
            "server": "kr",
            "boss_name": "Binah",
            "terrain": "outdoor",
            "season_label": season_label,
        },
        "snapshot": {
            "captured_at": "2026-04-16T10:00:00Z",
            "source_type": "image_sidecar",
            "note": "capture import test fixture",
        },
        "pages": pages,
    }
    (base_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_capture_page(base_dir: Path, image_name: str, ocr_text: str) -> None:
    image_path = base_dir / image_name
    image_path.write_bytes(b"PNG")
    image_path.with_suffix(".txt").write_text(ocr_text, encoding="utf-8")
