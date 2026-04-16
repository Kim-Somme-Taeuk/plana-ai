from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import collector.capture_import as capture_import
from collector.capture_import import (
    build_mock_payload_from_capture,
    import_capture_payload,
    load_capture_import_payload,
    parse_capture_payload,
    summarize_ignored_lines,
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
    assert payload.snapshot["source_type"] == "image_sidecar"
    assert payload.pages[0].image_path == "page-001.png"


def test_load_capture_import_payload_sets_tesseract_defaults(tmp_path: Path) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tPlana\t12345678\t0.99\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-tesseract-default-season",
        pages=[{"image_path": "page-001.png"}],
        snapshot={"captured_at": "2026-04-16T10:00:00Z"},
        ocr={"provider": "tesseract", "language": "kor", "psm": 6},
    )

    payload = load_capture_import_payload(tmp_path)

    assert payload.snapshot["source_type"] == "image_tesseract"
    assert payload.ocr.provider == "tesseract"
    assert payload.ocr.command == "tesseract"
    assert payload.ocr.language == "kor"
    assert payload.ocr.psm == 6


def test_load_capture_import_payload_overrides_snapshot_source_type_for_cli_provider(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tPlana\t12345678\t0.99\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-tesseract-cli-override-season",
        pages=[{"image_path": "page-001.png"}],
        snapshot={
            "captured_at": "2026-04-16T10:00:00Z",
            "source_type": "image_sidecar",
        },
    )

    payload = load_capture_import_payload(
        tmp_path,
        ocr_provider="tesseract",
    )

    assert payload.snapshot["source_type"] == "image_tesseract"
    assert payload.ocr.provider == "tesseract"


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
    assert mock_payload.entries[1]["player_name"] == ""


def test_build_mock_payload_from_capture_normalizes_tab_player_name_spacing(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\t  Player   2  \t12345678\t0.99\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-tab-player-spacing-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["player_name"] == "Player 2"


def test_parse_capture_payload_ignores_non_entry_lines(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "\nRANK PLAYER SCORE\n1\tPlana\t12345678\t0.99\n총 참여 인원 999\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-ignored-lines-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)
    ignored_summary = summarize_ignored_lines(parsed_payload.ignored_lines)

    assert len(parsed_payload.mock_payload.entries) == 1
    assert len(parsed_payload.ignored_lines) == 3
    assert parsed_payload.ignored_lines[0].reason == "blank_line"
    assert parsed_payload.ignored_lines[1].reason == "non_entry_line"
    assert parsed_payload.ignored_lines[2].raw_text == "총 참여 인원 999"
    assert ignored_summary == [
        {"reason": "blank_line", "count": 1},
        {"reason": "non_entry_line", "count": 2},
    ]


def test_parse_capture_payload_classifies_separator_lines(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "-----\n1\tPlana\t12345678\t0.99\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-separator-lines-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)
    ignored_summary = summarize_ignored_lines(parsed_payload.ignored_lines)

    assert len(parsed_payload.mock_payload.entries) == 1
    assert parsed_payload.ignored_lines[0].reason == "separator_line"
    assert ignored_summary == [{"reason": "separator_line", "count": 1}]


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


def test_build_mock_payload_from_capture_parses_whitespace_fallback_with_numeric_name(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1 Player 2 12345678\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-whitespace-player-number-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert len(mock_payload.entries) == 1
    assert mock_payload.entries[0]["rank"] == 1
    assert mock_payload.entries[0]["player_name"] == "Player 2"
    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] is None


def test_build_mock_payload_from_capture_normalizes_whitespace_player_spacing(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1   Player    2   12345678   0.87\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-whitespace-player-spacing-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["player_name"] == "Player 2"
    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] == 0.87


def test_build_mock_payload_from_capture_parses_whitespace_fallback_with_confidence(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1 Player 2 12345678 0.87\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-whitespace-confidence-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["player_name"] == "Player 2"
    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] == 0.87


def test_build_mock_payload_from_capture_parses_grouped_score_tokens(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1 Player 2 12 345 678 0.87\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-grouped-score-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["player_name"] == "Player 2"
    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] == 0.87


def test_build_mock_payload_from_capture_normalizes_grouped_score_tokens(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1 Plana l2 34O 678 O.87\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-grouped-score-normalized-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["player_name"] == "Plana"
    assert mock_payload.entries[0]["score"] == 12340678
    assert mock_payload.entries[0]["ocr_confidence"] == 0.87


def test_build_mock_payload_from_capture_normalizes_whitespace_confidence_token(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1 Player 2 12345678 O.87\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-whitespace-confidence-normalized-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["player_name"] == "Player 2"
    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] == 0.87


def test_build_mock_payload_from_capture_normalizes_common_ocr_numeric_tokens(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "l\tPlana\t12O,OOO\tO.87\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-ocr-token-normalization-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["rank"] == 1
    assert mock_payload.entries[0]["score"] == 120000
    assert mock_payload.entries[0]["ocr_confidence"] == 0.87


def test_build_mock_payload_from_capture_strips_trailing_numeric_punctuation(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "10\tArona\t9,876,543.\t0.95.\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-ocr-punctuation-normalization-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["rank"] == 10
    assert mock_payload.entries[0]["score"] == 9876543
    assert mock_payload.entries[0]["ocr_confidence"] == 0.95


def test_build_mock_payload_from_capture_strips_trailing_float_punctuation_variants(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "10\tArona\t9,876,543:\t0.95;\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-ocr-float-punctuation-variants-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["score"] == 9876543
    assert mock_payload.entries[0]["ocr_confidence"] == 0.95


def test_build_mock_payload_from_capture_runs_tesseract_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "unused sidecar\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-tesseract-build-season",
        pages=[{"image_path": "page-001.png"}],
        snapshot={"captured_at": "2026-04-16T10:00:00Z"},
        ocr={"provider": "tesseract", "language": "eng", "psm": 6},
    )

    def fake_run(args, capture_output, text, check):
        assert args == [
            "tesseract",
            str((tmp_path / "page-001.png").resolve()),
            "stdout",
            "-l",
            "eng",
            "--psm",
            "6",
        ]
        assert capture_output is True
        assert text is True
        assert check is False
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="1\tPlana\t12345678\t0.99\n10\tArona\t12000000\t0.97\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert len(mock_payload.entries) == 2
    assert mock_payload.entries[1]["rank"] == 10
    assert mock_payload.entries[1]["player_name"] == "Arona"


def test_build_mock_payload_from_capture_prefers_tesseract_over_explicit_sidecar_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "stale sidecar\n",
    )
    explicit_sidecar = tmp_path / "custom-ocr.txt"
    explicit_sidecar.write_text(
        "1\tStale\t11111111\t0.11\n",
        encoding="utf-8",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-tesseract-explicit-sidecar-season",
        pages=[
            {
                "image_path": "page-001.png",
                "ocr_text_path": "custom-ocr.txt",
            }
        ],
        snapshot={"captured_at": "2026-04-16T10:00:00Z"},
        ocr={"provider": "tesseract", "language": "eng", "psm": 6},
    )

    def fake_run(args, capture_output, text, check):
        assert args == [
            "tesseract",
            str((tmp_path / "page-001.png").resolve()),
            "stdout",
            "-l",
            "eng",
            "--psm",
            "6",
        ]
        assert capture_output is True
        assert text is True
        assert check is False
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="1\tFresh OCR\t12345678\t0.99\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert len(mock_payload.entries) == 1
    assert mock_payload.entries[0]["player_name"] == "Fresh OCR"
    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] == 0.99


def test_build_mock_payload_from_capture_fails_when_tesseract_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "unused sidecar\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-tesseract-missing-season",
        pages=[{"image_path": "page-001.png"}],
        snapshot={"captured_at": "2026-04-16T10:00:00Z"},
        ocr={"provider": "tesseract"},
    )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: None)

    payload = load_capture_import_payload(tmp_path)

    with pytest.raises(MockImportError) as exc_info:
        build_mock_payload_from_capture(payload)

    assert "tesseract 명령을 찾을 수 없습니다" in str(exc_info.value)


def _write_capture_manifest(
    base_dir: Path,
    *,
    season_label: str,
    pages: list[dict[str, object]],
    snapshot: dict[str, object] | None = None,
    ocr: dict[str, object] | None = None,
) -> None:
    manifest = {
        "season": {
            "event_type": "total_assault",
            "server": "kr",
            "boss_name": "Binah",
            "terrain": "outdoor",
            "season_label": season_label,
        },
        "snapshot": snapshot
        or {
            "captured_at": "2026-04-16T10:00:00Z",
            "source_type": "image_sidecar",
            "note": "capture import test fixture",
        },
        "pages": pages,
    }
    if ocr is not None:
        manifest["ocr"] = ocr
    (base_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_capture_page(base_dir: Path, image_name: str, ocr_text: str) -> None:
    image_path = base_dir / image_name
    image_path.write_bytes(b"PNG")
    image_path.with_suffix(".txt").write_text(ocr_text, encoding="utf-8")
