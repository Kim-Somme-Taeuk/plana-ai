from __future__ import annotations

import json
from itertools import cycle
import subprocess
from pathlib import Path

import pytest

import collector.capture_import as capture_import
from collector.capture_import import (
    build_ocr_stop_recommendation,
    build_ocr_stop_hints,
    build_mock_payload_from_capture,
    import_capture_payload,
    load_capture_import_payload,
    parse_capture_payload,
    summarize_ignored_lines,
)
from collector.mock_import import MockImportError


class SnapshotAwareApiClientMixin:
    def list_seasons(self):
        return []

    def list_snapshots(self, season_id):
        return []

    def list_entries(self, snapshot_id):
        return []


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


def test_build_mock_payload_from_capture_strips_wrapping_player_name_punctuation(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\t「 Plana 」\t12345678\t0.99\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-player-name-wrapper-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["player_name"] == "Plana"


def test_build_mock_payload_from_capture_parses_punctuated_score_and_percent_confidence(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1 Player 2 12.345.678 87%\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-punctuated-score-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["player_name"] == "Player 2"
    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] == pytest.approx(0.87)


def test_build_mock_payload_from_capture_parses_decimal_comma_confidence(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1 Player 2 12345678 O,87\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-decimal-comma-confidence-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["rank"] == 1
    assert mock_payload.entries[0]["player_name"] == "Player 2"
    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] == pytest.approx(0.87)


def test_build_mock_payload_from_capture_normalizes_unicode_rank_and_player_tokens(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "①　Player\u200b　2　１２３４５６７８　８７％\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-unicode-rank-player-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["rank"] == 1
    assert mock_payload.entries[0]["player_name"] == "Player 2"
    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] == pytest.approx(0.87)


def test_build_mock_payload_from_capture_parses_percent_tokens_split_by_space(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1 Player 2 12 345 678 87 %\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-split-percent-confidence-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] == pytest.approx(0.87)


def test_build_mock_payload_from_capture_parses_bracketed_score_and_confidence(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1 Player 2 [12.345.678] (87%)\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-bracketed-score-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["player_name"] == "Player 2"
    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] == pytest.approx(0.87)


def test_build_mock_payload_from_capture_parses_pipe_separated_structured_line(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "No.2|Player 2|12,345,678점|O.87\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-pipe-structured-line-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries == [
        {
            "rank": 2,
            "score": 12345678,
            "player_name": "Player 2",
            "ocr_confidence": pytest.approx(0.87),
            "raw_text": "No.2|Player 2|12,345,678점|O.87",
            "image_path": capture_import._build_entry_image_path(
                (tmp_path / "page-001.png").resolve()
            ),
            "is_valid": True,
            "validation_issue": None,
        }
    ]


def test_build_mock_payload_from_capture_parses_fullwidth_pipe_structured_line(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "2 ｜ Arona ｜ 9 876 543pts ｜ 0.91\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-fullwidth-pipe-structured-line-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["rank"] == 2
    assert mock_payload.entries[0]["player_name"] == "Arona"
    assert mock_payload.entries[0]["score"] == 9876543
    assert mock_payload.entries[0]["ocr_confidence"] == pytest.approx(0.91)


def test_build_mock_payload_from_capture_parses_structured_line_with_split_score_suffix(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "3｜Sensei｜8 765 432 점｜87 %\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-structured-split-score-suffix-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["rank"] == 3
    assert mock_payload.entries[0]["player_name"] == "Sensei"
    assert mock_payload.entries[0]["score"] == 8765432
    assert mock_payload.entries[0]["ocr_confidence"] == pytest.approx(0.87)


def test_build_mock_payload_from_capture_keeps_empty_player_in_structured_line(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1||12,345,678|\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-structured-empty-player-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert mock_payload.entries[0]["rank"] == 1
    assert mock_payload.entries[0]["player_name"] == ""
    assert mock_payload.entries[0]["score"] == 12345678
    assert mock_payload.entries[0]["ocr_confidence"] is None


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
    assert parsed_payload.ignored_lines[1].reason == "header_line"
    assert parsed_payload.ignored_lines[2].raw_text == "총 참여 인원 999"
    assert ignored_summary == [
        {"reason": "blank_line", "count": 1},
        {"reason": "header_line", "count": 1},
        {"reason": "metadata_line", "count": 1},
    ]
    assert parsed_payload.page_summaries == [
        {
            "page_index": 1,
            "image_path": capture_import._build_entry_image_path(
                (tmp_path / "page-001.png").resolve()
            ),
            "entry_count": 1,
            "ignored_line_count": 3,
            "ignored_line_reasons": [
                {"reason": "blank_line", "count": 1},
                {"reason": "header_line", "count": 1},
                {"reason": "metadata_line", "count": 1},
            ],
            "first_rank": 1,
            "last_rank": 1,
            "overlap_with_previous_count": 0,
            "overlap_with_previous_ratio": 0.0,
            "overlap_with_previous_ranks": [],
            "new_rank_count": 1,
            "new_rank_ratio": 1.0,
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
            "absolute_rank_base": None,
            "absolute_rank_base_source": None,
        }
    ]
    note_lines = parsed_payload.mock_payload.snapshot["note"].splitlines()
    assert note_lines[0] == "capture import test fixture"
    assert (
        note_lines[1]
        == "collector: ignored=3(blank_line=1,header_line=1,metadata_line=1); "
        "ocr_stop=noisy_last_page(hard)"
    )
    assert note_lines[2].startswith("collector_json: ")
    payload = json.loads(note_lines[2].split("collector_json: ", 1)[1])
    assert "ba" not in payload


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


def test_build_collector_details_payload_compacts_blue_archive_rank_debug() -> None:
    payload = capture_import._build_collector_details_payload(
        [
            {
                "page_index": 1,
                "entry_count": 3,
                "ignored_line_count": 0,
                "ignored_line_reasons": [],
                "first_rank": 3522,
                "last_rank": 3524,
                "overlap_with_previous_count": 0,
                "overlap_with_previous_ratio": 0.0,
                "overlap_with_previous_ranks": [],
                "new_rank_count": 3,
                "new_rank_ratio": 1.0,
                "absolute_rank_anchor": 3522,
                "absolute_rank_anchor_source": "original",
                "absolute_rank_base": 3522,
                "absolute_rank_base_source": "row_base",
            }
        ]
    )

    assert payload["ba"] == {
        "a": 3522,
        "s": "original",
        "b": 3522,
        "bs": "row_base",
        "f": 3522,
        "l": 3524,
    }


def test_parse_capture_payload_classifies_korean_header_footer_and_pagination_lines(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "순위 닉네임 점수\n1\tPlana\t12345678\t0.99\n2/5\n계속하려면 탭\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-korean-header-footer-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)
    ignored_summary = summarize_ignored_lines(parsed_payload.ignored_lines)

    assert len(parsed_payload.mock_payload.entries) == 1
    assert ignored_summary == [
        {"reason": "footer_line", "count": 1},
        {"reason": "header_line", "count": 1},
        {"reason": "pagination_line", "count": 1},
    ]


def test_parse_capture_payload_classifies_pipe_separated_header_lines(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "순위|닉네임|점수\n1|Plana|12,345,678\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-pipe-header-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert len(parsed_payload.mock_payload.entries) == 1
    assert summarize_ignored_lines(parsed_payload.ignored_lines) == [
        {"reason": "header_line", "count": 1}
    ]


def test_parse_capture_payload_classifies_datetime_metadata_lines(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "captured 2026-04-17 10:30:45 UTC\n1\tPlana\t12345678\t0.99\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-datetime-metadata-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert len(parsed_payload.mock_payload.entries) == 1
    assert summarize_ignored_lines(parsed_payload.ignored_lines) == [
        {"reason": "metadata_line", "count": 1}
    ]


def test_parse_capture_payload_classifies_status_lines(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "내 순위 123\n1\tPlana\t12345678\t0.99\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-status-line-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert len(parsed_payload.mock_payload.entries) == 1
    assert summarize_ignored_lines(parsed_payload.ignored_lines) == [
        {"reason": "status_line", "count": 1}
    ]


def test_parse_capture_payload_classifies_reward_lines(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "랭킹 보상 1200 청휘석\n1\tPlana\t12345678\t0.99\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-reward-line-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert len(parsed_payload.mock_payload.entries) == 1
    assert summarize_ignored_lines(parsed_payload.ignored_lines) == [
        {"reason": "reward_line", "count": 1}
    ]


def test_parse_capture_payload_classifies_ui_control_lines(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "정렬 | 점수 순\n1|Plana|12,345,678\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-ui-control-line-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert len(parsed_payload.mock_payload.entries) == 1
    assert summarize_ignored_lines(parsed_payload.ignored_lines) == [
        {"reason": "ui_control_line", "count": 1}
    ]


def test_parse_capture_payload_treats_unparseable_entry_like_line_as_malformed_ignored_line(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tPlana\t12345678\t0.99\n2 Broken Score ???\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-malformed-entry-line-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert len(parsed_payload.mock_payload.entries) == 1
    assert summarize_ignored_lines(parsed_payload.ignored_lines) == [
        {"reason": "malformed_entry_line", "count": 1}
    ]
    note_lines = parsed_payload.mock_payload.snapshot["note"].splitlines()
    assert (
        note_lines[1]
        == "collector: ignored=1(malformed_entry_line=1); ocr_stop=noisy_last_page(hard)"
    )


def test_parse_capture_payload_reports_multi_page_summaries(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tPlana\t12345678\t0.99\n2\tArona\t12000000\t0.97\n",
    )
    _write_capture_page(
        tmp_path,
        "page-002.png",
        "3\tSensei\t11000000\t0.95\n4\tMomoi\t10000000\t0.92\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-page-overlap-season",
        pages=[
            {"image_path": "page-001.png"},
            {"image_path": "page-002.png"},
        ],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert parsed_payload.page_summaries == [
        {
            "page_index": 1,
            "image_path": capture_import._build_entry_image_path(
                (tmp_path / "page-001.png").resolve()
            ),
            "entry_count": 2,
            "ignored_line_count": 0,
            "ignored_line_reasons": [],
            "first_rank": 1,
            "last_rank": 2,
            "overlap_with_previous_count": 0,
            "overlap_with_previous_ratio": 0.0,
            "overlap_with_previous_ranks": [],
            "new_rank_count": 2,
            "new_rank_ratio": 1.0,
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
            "absolute_rank_base": None,
            "absolute_rank_base_source": None,
        },
        {
            "page_index": 2,
            "image_path": capture_import._build_entry_image_path(
                (tmp_path / "page-002.png").resolve()
            ),
            "entry_count": 2,
            "ignored_line_count": 0,
            "ignored_line_reasons": [],
            "first_rank": 3,
            "last_rank": 4,
            "overlap_with_previous_count": 0,
            "overlap_with_previous_ratio": 0.0,
            "overlap_with_previous_ranks": [],
            "new_rank_count": 2,
            "new_rank_ratio": 1.0,
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
            "absolute_rank_base": None,
            "absolute_rank_base_source": None,
        },
    ]


def test_parse_capture_payload_uses_blue_archive_row_pipeline_without_loading_ocr_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_capture_page(tmp_path, "page-001.png", "unused\n")
    _write_capture_page(tmp_path, "page-002.png", "unused\n")
    _write_capture_manifest(
        tmp_path,
        season_label="capture-blue-archive-row-pipeline-season",
        pages=[
            {"image_path": "page-001.png"},
            {"image_path": "page-002.png"},
        ],
        ocr={"provider": "tesseract"},
    )

    monkeypatch.setattr(
        capture_import,
        "_is_blue_archive_fixed_layout_image",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        capture_import,
        "_load_ocr_text",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("blue archive row pipeline should not load OCR text")
        ),
    )

    page_entries = {
        1: [
            {"rank": 1, "player_name": "Lunatic", "score": 53404105},
            {"rank": 2, "player_name": "Lunatic", "score": 53393930},
            {"rank": 3, "player_name": "Lunatic", "score": 53393544},
        ],
        2: [
            {"rank": 3, "player_name": "Lunatic", "score": 53393544},
            {"rank": 4, "player_name": "Lunatic", "score": 53393449},
            {"rank": 5, "player_name": "Lunatic", "score": 53389034},
        ],
    }
    monkeypatch.setattr(
        capture_import,
        "_parse_blue_archive_page_entries",
        lambda **kwargs: [
            {
                **entry,
                "ocr_confidence": None,
                "raw_text": "",
                "image_path": kwargs["image_path"].name,
                "is_valid": True,
                "validation_issue": None,
            }
            for entry in page_entries[kwargs["page_index"]]
        ],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert [entry["rank"] for entry in parsed_payload.mock_payload.entries] == [1, 2, 3, 4, 5]
    assert [entry["player_name"] for entry in parsed_payload.mock_payload.entries] == [
        "Lunatic",
        "Lunatic",
        "Lunatic",
        "Lunatic",
        "Lunatic",
    ]
    assert parsed_payload.mock_payload.snapshot["note"] == "capture import test fixture"


def test_parse_capture_payload_retrofits_blue_archive_absolute_ranks_from_later_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_capture_page(tmp_path, "page-001.png", "unused\n")
    _write_capture_page(tmp_path, "page-002.png", "unused\n")
    _write_capture_page(tmp_path, "page-003.png", "unused\n")
    _write_capture_manifest(
        tmp_path,
        season_label="capture-blue-archive-retrofit-season",
        pages=[
            {"image_path": "page-001.png"},
            {"image_path": "page-002.png"},
            {"image_path": "page-003.png"},
        ],
    )

    page_entries = iter(
        [
            (
                [
                    {
                        "rank": 1,
                        "score": 40040720,
                        "player_name": "Torment",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": None,
                        "_absolute_rank_base_source": None,
                    },
                    {
                        "rank": 2,
                        "score": 40040720,
                        "player_name": "Torment",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": None,
                        "_absolute_rank_base_source": None,
                    },
                    {
                        "rank": 3,
                        "score": 40040641,
                        "player_name": "Torment",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": None,
                        "_absolute_rank_base_source": None,
                    },
                ],
                [],
            ),
            (
                [
                    {
                        "rank": 3,
                        "score": 40040641,
                        "player_name": "Torment",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": 12003,
                        "_absolute_rank_base_source": "row_base",
                    },
                    {
                        "rank": 4,
                        "score": 40040480,
                        "player_name": "Torment",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": 12003,
                        "_absolute_rank_base_source": "row_base",
                    },
                    {
                        "rank": 5,
                        "score": 40040160,
                        "player_name": "Torment",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": 12003,
                        "_absolute_rank_base_source": "row_base",
                    },
                ],
                [],
            ),
            (
                [
                    {
                        "rank": 5,
                        "score": 40040160,
                        "player_name": "Torment",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": None,
                        "_absolute_rank_base_source": None,
                    },
                    {
                        "rank": 6,
                        "score": 40040160,
                        "player_name": "Torment",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": None,
                        "_absolute_rank_base_source": None,
                    },
                    {
                        "rank": 7,
                        "score": 40039920,
                        "player_name": "Torment",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": None,
                        "_absolute_rank_base_source": None,
                    },
                ],
                [],
            ),
        ]
    )

    monkeypatch.setattr(capture_import, "_load_ocr_text", lambda **kwargs: "unused")
    monkeypatch.setattr(capture_import, "_parse_page_entries", lambda **kwargs: next(page_entries))

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload, validate_snapshot_entries=False)

    assert [entry["rank"] for entry in parsed_payload.mock_payload.entries] == [
        12001,
        12002,
        12003,
        12004,
        12005,
        12006,
        12007,
    ]
    assert parsed_payload.page_summaries[0]["first_rank"] == 12001
    assert parsed_payload.page_summaries[0]["absolute_rank_base"] == 12001
    assert parsed_payload.page_summaries[0]["absolute_rank_base_source"] == "retrofit"
    assert parsed_payload.page_summaries[1]["first_rank"] == 12003
    assert parsed_payload.page_summaries[1]["absolute_rank_base_source"] == "row_base"
    assert parsed_payload.page_summaries[2]["first_rank"] == 12005
    assert parsed_payload.page_summaries[2]["absolute_rank_base_source"] == "retrofit"


def test_parse_capture_payload_retrofits_blue_archive_absolute_ranks_without_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_capture_page(tmp_path, "page-001.png", "unused\n")
    _write_capture_page(tmp_path, "page-002.png", "unused\n")
    _write_capture_page(tmp_path, "page-003.png", "unused\n")
    _write_capture_manifest(
        tmp_path,
        season_label="capture-blue-archive-retrofit-no-overlap-season",
        pages=[
            {"image_path": "page-001.png"},
            {"image_path": "page-002.png"},
            {"image_path": "page-003.png"},
        ],
    )

    page_entries = iter(
        [
            (
                [
                    {
                        "rank": 1,
                        "score": 27771072,
                        "player_name": "Insane",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": None,
                        "_absolute_rank_base_source": None,
                    },
                    {
                        "rank": 2,
                        "score": 27770049,
                        "player_name": "Insane",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": None,
                        "_absolute_rank_base_source": None,
                    },
                    {
                        "rank": 3,
                        "score": 27768256,
                        "player_name": "Insane",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": None,
                        "_absolute_rank_base_source": None,
                    },
                ],
                [],
            ),
            (
                [
                    {
                        "rank": 4,
                        "score": 27768100,
                        "player_name": "Insane",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": 16112,
                        "_absolute_rank_base_source": "row_base",
                    },
                    {
                        "rank": 5,
                        "score": 27768000,
                        "player_name": "Insane",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": 16112,
                        "_absolute_rank_base_source": "row_base",
                    },
                ],
                [],
            ),
            (
                [
                    {
                        "rank": 5,
                        "score": 27768000,
                        "player_name": "Insane",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": None,
                        "_absolute_rank_base_source": None,
                    },
                    {
                        "rank": 6,
                        "score": 27767900,
                        "player_name": "Insane",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": None,
                        "_absolute_rank_base_source": None,
                    },
                    {
                        "rank": 7,
                        "score": 27767800,
                        "player_name": "Insane",
                        "_absolute_rank_anchor": None,
                        "_absolute_rank_anchor_source": None,
                        "_absolute_rank_base": None,
                        "_absolute_rank_base_source": None,
                    },
                ],
                [],
            ),
        ]
    )

    monkeypatch.setattr(capture_import, "_load_ocr_text", lambda **kwargs: "unused")
    monkeypatch.setattr(capture_import, "_parse_page_entries", lambda **kwargs: next(page_entries))

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload, validate_snapshot_entries=False)

    assert [entry["rank"] for entry in parsed_payload.mock_payload.entries] == [
        16109,
        16110,
        16111,
        16112,
        16113,
        16114,
        16115,
    ]
    assert parsed_payload.page_summaries[0]["first_rank"] == 16109
    assert parsed_payload.page_summaries[1]["first_rank"] == 16112
    assert parsed_payload.page_summaries[2]["first_rank"] == 16113
    assert parsed_payload.page_summaries[0]["absolute_rank_base_source"] == "retrofit"
    assert parsed_payload.page_summaries[1]["absolute_rank_base_source"] == "row_base"
    assert parsed_payload.page_summaries[2]["absolute_rank_base_source"] == "retrofit"


def test_parse_capture_payload_reports_empty_page_summary_without_crashing(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tPlana\t12345678\t0.99\n",
    )
    _write_capture_page(
        tmp_path,
        "page-002.png",
        "\n-----\n총 참여 인원 999\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-empty-last-page-season",
        pages=[
            {"image_path": "page-001.png"},
            {"image_path": "page-002.png"},
        ],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert parsed_payload.page_summaries[1] == {
        "page_index": 2,
        "image_path": capture_import._build_entry_image_path(
            (tmp_path / "page-002.png").resolve()
        ),
        "entry_count": 0,
        "ignored_line_count": 3,
        "ignored_line_reasons": [
            {"reason": "blank_line", "count": 1},
            {"reason": "metadata_line", "count": 1},
            {"reason": "separator_line", "count": 1},
        ],
        "first_rank": None,
        "last_rank": None,
        "overlap_with_previous_count": 0,
        "overlap_with_previous_ratio": 0.0,
        "overlap_with_previous_ranks": [],
        "new_rank_count": 0,
        "new_rank_ratio": 0.0,
        "absolute_rank_anchor": None,
        "absolute_rank_anchor_source": None,
        "absolute_rank_base": None,
        "absolute_rank_base_source": None,
    }
    note_lines = parsed_payload.mock_payload.snapshot["note"].splitlines()
    assert note_lines[0] == "capture import test fixture"
    assert (
        note_lines[1]
        == "collector: ignored=3(blank_line=1,metadata_line=1,separator_line=1); "
        "ocr_stop=empty_last_page(hard)"
    )
    assert note_lines[2].startswith("collector_json: ")


def test_parse_capture_payload_appends_capture_summary_to_snapshot_note(
    tmp_path: Path,
) -> None:
    _write_capture_page(tmp_path, "page-001.png", "1\tPlana\t12345678\t0.99\n")
    _write_capture_page(tmp_path, "page-002.png", "header\n2\tArona\t12000000\t0.98\n")
    _write_capture_manifest(
        tmp_path,
        season_label="capture-note-summary-season",
        pages=[
            {"image_path": "page-001.png"},
            {"image_path": "page-002.png"},
        ],
        capture={
            "requested_page_count": 3,
            "captured_page_count": 2,
            "stopped_reason": "noisy_last_page",
        },
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    note_lines = parsed_payload.mock_payload.snapshot["note"].splitlines()
    assert note_lines[0] == "capture import test fixture"
    assert (
        note_lines[1]
        == "collector: pages=2/3; capture_stop=noisy_last_page; "
        "ignored=1(non_entry_line=1); ocr_stop=noisy_last_page(hard)"
    )
    assert note_lines[2].startswith("collector_json: ")


def test_parse_capture_payload_raises_when_all_pages_are_empty(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "\n-----\n총 참여 인원 999\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-all-empty-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)

    with pytest.raises(MockImportError) as exc_info:
        parse_capture_payload(payload)

    assert str(exc_info.value) == "capture 전체에서 파싱 가능한 OCR entry가 없습니다."


def test_build_ocr_stop_hints_detects_sparse_and_noisy_last_page() -> None:
    page_summaries = [
        {
            "page_index": 1,
            "entry_count": 20,
            "ignored_line_count": 0,
        },
        {
            "page_index": 2,
            "entry_count": 1,
            "ignored_line_count": 2,
        },
    ]

    assert build_ocr_stop_hints(page_summaries) == [
        {"reason": "sparse_last_page", "page_index": 2, "entry_count": 1},
        {
            "reason": "noisy_last_page",
            "page_index": 2,
            "ignored_line_count": 2,
            "entry_count": 1,
        },
    ]
    assert build_ocr_stop_recommendation(
        build_ocr_stop_hints(page_summaries)
    ) == {
        "should_stop": True,
        "level": "hard",
        "primary_reason": "noisy_last_page",
        "reasons": ["sparse_last_page", "noisy_last_page"],
    }


def test_build_ocr_stop_hints_detects_empty_and_overlapping_last_page() -> None:
    assert build_ocr_stop_hints(
        [
            {
                "page_index": 1,
                "entry_count": 20,
                "ignored_line_count": 0,
                "overlap_with_previous_count": 0,
                "overlap_with_previous_ratio": 0.0,
            },
            {
                "page_index": 2,
                "entry_count": 0,
                "ignored_line_count": 2,
                "overlap_with_previous_count": 0,
                "overlap_with_previous_ratio": 0.0,
            },
        ]
    ) == [
        {"reason": "empty_last_page", "page_index": 2},
        {"reason": "sparse_last_page", "page_index": 2, "entry_count": 0},
        {
            "reason": "noisy_last_page",
            "page_index": 2,
            "ignored_line_count": 2,
            "entry_count": 0,
        },
    ]

    assert build_ocr_stop_hints(
        [
            {
                "page_index": 1,
                "entry_count": 20,
                "ignored_line_count": 0,
                "overlap_with_previous_count": 0,
                "overlap_with_previous_ratio": 0.0,
            },
            {
                "page_index": 2,
                "entry_count": 4,
                "ignored_line_count": 1,
                "overlap_with_previous_count": 3,
                "overlap_with_previous_ratio": 0.75,
                "new_rank_count": 1,
                "new_rank_ratio": 0.25,
            },
        ]
    ) == [
        {
            "reason": "overlapping_last_page",
            "page_index": 2,
            "overlap_with_previous_count": 3,
            "overlap_with_previous_ratio": 0.75,
        },
        {
            "reason": "stale_last_page",
            "page_index": 2,
            "new_rank_count": 1,
            "new_rank_ratio": 0.25,
        }
    ]

    assert build_ocr_stop_hints(
        [
            {
                "page_index": 1,
                "entry_count": 4,
                "ignored_line_count": 0,
                "overlap_with_previous_count": 0,
                "overlap_with_previous_ratio": 0.0,
            },
            {
                "page_index": 2,
                "entry_count": 4,
                "ignored_line_count": 0,
                "overlap_with_previous_count": 4,
                "overlap_with_previous_ratio": 1.0,
            },
        ]
    ) == [
        {
            "reason": "overlapping_last_page",
            "page_index": 2,
            "overlap_with_previous_count": 4,
            "overlap_with_previous_ratio": 1.0,
        },
        {
            "reason": "duplicate_last_page",
            "page_index": 2,
            "overlap_with_previous_count": 4,
            "overlap_with_previous_ratio": 1.0,
        },
    ]

    assert build_ocr_stop_recommendation(
        [
            {
                "reason": "overlapping_last_page",
                "page_index": 2,
                "overlap_with_previous_count": 3,
                "overlap_with_previous_ratio": 0.75,
            },
            {
                "reason": "stale_last_page",
                "page_index": 2,
                "new_rank_count": 1,
                "new_rank_ratio": 0.25,
            }
        ]
    ) == {
        "should_stop": True,
        "level": "soft",
        "primary_reason": "overlapping_last_page",
        "reasons": ["overlapping_last_page", "stale_last_page"],
    }

    assert build_ocr_stop_recommendation(
        [
            {
                "reason": "overlapping_last_page",
                "page_index": 2,
                "overlap_with_previous_count": 4,
                "overlap_with_previous_ratio": 1.0,
            },
            {
                "reason": "duplicate_last_page",
                "page_index": 2,
                "overlap_with_previous_count": 4,
                "overlap_with_previous_ratio": 1.0,
            },
        ]
    ) == {
        "should_stop": True,
        "level": "hard",
        "primary_reason": "duplicate_last_page",
        "reasons": ["overlapping_last_page", "duplicate_last_page"],
    }

    assert build_ocr_stop_hints(
        [
            {
                "page_index": 1,
                "entry_count": 20,
                "ignored_line_count": 0,
                "ignored_line_reasons": [],
                "overlap_with_previous_count": 0,
                "overlap_with_previous_ratio": 0.0,
            },
            {
                "page_index": 2,
                "entry_count": 2,
                "ignored_line_count": 2,
                "ignored_line_reasons": [
                    {"reason": "reward_line", "count": 1},
                    {"reason": "status_line", "count": 1},
                ],
                "overlap_with_previous_count": 0,
                "overlap_with_previous_ratio": 0.0,
                "new_rank_count": 2,
                "new_rank_ratio": 1.0,
            },
        ]
    ) == [
        {"reason": "sparse_last_page", "page_index": 2, "entry_count": 2},
        {
            "reason": "overlay_last_page",
            "page_index": 2,
            "ignored_overlay_count": 2,
            "entry_count": 2,
        },
        {
            "reason": "noisy_last_page",
            "page_index": 2,
            "ignored_line_count": 2,
            "entry_count": 2,
        },
    ]

    assert build_ocr_stop_recommendation(
        [
            {"reason": "sparse_last_page", "page_index": 2, "entry_count": 2},
            {
                "reason": "overlay_last_page",
                "page_index": 2,
                "ignored_overlay_count": 2,
                "entry_count": 2,
            },
        ]
    ) == {
        "should_stop": True,
        "level": "hard",
        "primary_reason": "overlay_last_page",
        "reasons": ["sparse_last_page", "overlay_last_page"],
    }

    assert build_ocr_stop_hints(
        [
            {
                "page_index": 1,
                "entry_count": 20,
                "ignored_line_count": 0,
                "ignored_line_reasons": [],
                "overlap_with_previous_count": 0,
                "overlap_with_previous_ratio": 0.0,
            },
            {
                "page_index": 2,
                "entry_count": 2,
                "ignored_line_count": 1,
                "ignored_line_reasons": [
                    {"reason": "header_line", "count": 1},
                ],
                "overlap_with_previous_count": 0,
                "overlap_with_previous_ratio": 0.0,
                "new_rank_count": 2,
                "new_rank_ratio": 1.0,
            },
        ]
    ) == [
        {"reason": "sparse_last_page", "page_index": 2, "entry_count": 2},
        {
            "reason": "header_repeat_last_page",
            "page_index": 2,
            "ignored_header_count": 1,
            "entry_count": 2,
        },
    ]

    assert build_ocr_stop_hints(
        [
            {
                "page_index": 1,
                "entry_count": 20,
                "ignored_line_count": 0,
                "ignored_line_reasons": [],
                "overlap_with_previous_count": 0,
                "overlap_with_previous_ratio": 0.0,
            },
            {
                "page_index": 2,
                "entry_count": 1,
                "ignored_line_count": 2,
                "ignored_line_reasons": [
                    {"reason": "malformed_entry_line", "count": 2},
                ],
                "overlap_with_previous_count": 0,
                "overlap_with_previous_ratio": 0.0,
                "new_rank_count": 1,
                "new_rank_ratio": 1.0,
            },
        ]
    ) == [
        {"reason": "sparse_last_page", "page_index": 2, "entry_count": 1},
        {
            "reason": "malformed_last_page",
            "page_index": 2,
            "malformed_entry_count": 2,
            "entry_count": 1,
        },
        {
            "reason": "noisy_last_page",
            "page_index": 2,
            "ignored_line_count": 2,
            "entry_count": 1,
        },
    ]

    assert build_ocr_stop_recommendation(
        [
            {"reason": "sparse_last_page", "page_index": 2, "entry_count": 1},
            {
                "reason": "malformed_last_page",
                "page_index": 2,
                "malformed_entry_count": 2,
                "entry_count": 1,
            },
        ]
    ) == {
        "should_stop": True,
        "level": "hard",
        "primary_reason": "malformed_last_page",
        "reasons": ["sparse_last_page", "malformed_last_page"],
    }


def test_build_mock_payload_from_capture_dedupes_overlapping_page_ranks(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tPlana\t12345678\t0.99\n2\tArona\t12000000\t0.97\n",
    )
    _write_capture_page(
        tmp_path,
        "page-002.png",
        "2\tArona\t12000000\t0.97\n3\tSensei\t11000000\t0.95\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-page-overlap-duplicate-season",
        pages=[
            {"image_path": "page-001.png"},
            {"image_path": "page-002.png"},
        ],
    )

    payload = load_capture_import_payload(tmp_path)

    mock_payload = build_mock_payload_from_capture(payload)

    assert [(entry["rank"], entry["player_name"], entry["score"]) for entry in mock_payload.entries] == [
        (1, "Plana", 12345678),
        (2, "Arona", 12000000),
        (3, "Sensei", 11000000),
    ]


def test_import_capture_payload_calls_api_in_order(tmp_path: Path) -> None:
    class FakeApiClient(SnapshotAwareApiClientMixin):
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


def test_build_mock_payload_from_capture_dedupes_duplicate_rank_across_pages(tmp_path: Path) -> None:
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

    mock_payload = build_mock_payload_from_capture(payload)

    assert [(entry["rank"], entry["player_name"], entry["score"]) for entry in mock_payload.entries] == [
        (1, "Plana", 12345678),
    ]


def test_build_mock_payload_from_capture_rejects_duplicate_ranks_within_page(tmp_path: Path) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tPlana\t12345678\t0.99\n1\tArona\t12000000\t0.97\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-same-page-duplicate-rank-season",
        pages=[{"image_path": "page-001.png"}],
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


def test_build_mock_payload_from_capture_parses_rank_token_variants(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "#1\tPlana\t12O,OOO\tO.87\n2위 Arona 9 876 543 0.95\nNo.3 Sensei 8 765 432 0.93\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-rank-token-variants-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert [entry["rank"] for entry in mock_payload.entries] == [1, 2, 3]
    assert mock_payload.entries[0]["score"] == 120000
    assert mock_payload.entries[1]["player_name"] == "Arona"
    assert mock_payload.entries[1]["score"] == 9876543
    assert mock_payload.entries[2]["player_name"] == "Sensei"
    assert mock_payload.entries[2]["score"] == 8765432


def test_parse_capture_payload_does_not_classify_rank_token_variants_as_non_entry_lines(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "#1\tPlana\t12345678\t0.99\nNo.2 Arona 12 345 678 0.95\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-rank-token-variant-lines-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert len(parsed_payload.mock_payload.entries) == 2
    assert parsed_payload.ignored_lines == []


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


def test_build_mock_payload_from_capture_parses_score_suffix_variants(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tPlana\t12,345,678점\t0.95\n2 Arona 9 876 543pt 0.87\n3 Sensei 8 765 432pts 0.86\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-score-suffix-variants-season",
        pages=[{"image_path": "page-001.png"}],
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert [entry["score"] for entry in mock_payload.entries] == [
        12345678,
        9876543,
        8765432,
    ]
    assert mock_payload.entries[0]["ocr_confidence"] == 0.95
    assert mock_payload.entries[1]["ocr_confidence"] == 0.87
    assert mock_payload.entries[2]["ocr_confidence"] == 0.86


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

    def fake_run(args, capture_output, text, encoding, errors, check):
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
        assert encoding == "utf-8"
        assert errors == "replace"
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
    assert (tmp_path / "page-001.txt").read_text(encoding="utf-8") == (
        "1\tPlana\t12345678\t0.99\n10\tArona\t12000000\t0.97\n"
    )


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

    def fake_run(args, capture_output, text, encoding, errors, check):
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
        assert encoding == "utf-8"
        assert errors == "replace"
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
    assert explicit_sidecar.read_text(encoding="utf-8") == "1\tFresh OCR\t12345678\t0.99\n"


def test_build_mock_payload_from_capture_can_reuse_cached_tesseract_sidecar(
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
        season_label="capture-tesseract-reuse-sidecar-season",
        pages=[{"image_path": "page-001.png"}],
        snapshot={"captured_at": "2026-04-16T10:00:00Z"},
        ocr={"provider": "tesseract", "reuse_cached_sidecar": True},
    )
    (tmp_path / "page-001.txt").write_text(
        "1\tCached OCR\t12345678\t0.88\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(
        capture_import.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cached sidecar를 재사용해야 합니다")),
    )

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert len(mock_payload.entries) == 1
    assert mock_payload.entries[0]["player_name"] == "Cached OCR"
    assert mock_payload.entries[0]["ocr_confidence"] == pytest.approx(0.88)


def test_build_mock_payload_from_capture_can_disable_tesseract_sidecar_persist(
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
        season_label="capture-tesseract-no-sidecar-persist-season",
        pages=[{"image_path": "page-001.png"}],
        snapshot={"captured_at": "2026-04-16T10:00:00Z"},
        ocr={"provider": "tesseract", "persist_sidecar": False},
    )
    (tmp_path / "page-001.txt").unlink()

    def fake_run(args, capture_output, text, encoding, errors, check):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="1\tPlana\t12345678\t0.99\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    payload = load_capture_import_payload(tmp_path)
    build_mock_payload_from_capture(payload)

    assert not (tmp_path / "page-001.txt").exists()


def test_build_mock_payload_from_capture_falls_back_to_tesseract_tsv_card_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "garbled ocr\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-tesseract-tsv-layout-season",
        pages=[{"image_path": "page-001.png"}],
        snapshot={"captured_at": "2026-04-16T10:00:00Z"},
        ocr={"provider": "tesseract", "language": "kor+eng", "psm": 11},
    )

    header = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    )
    tsv_output = header + "\n".join(
        [
            "5\t1\t1\t1\t1\t1\t100\t100\t40\t20\t96\t1위",
            "5\t1\t1\t1\t1\t2\t170\t100\t90\t20\t94\tLunatic",
            "5\t1\t1\t1\t1\t3\t290\t100\t180\t20\t95\t53,404,105",
            "5\t1\t1\t1\t2\t1\t100\t150\t40\t20\t96\t2위",
            "5\t1\t1\t1\t2\t2\t170\t150\t90\t20\t94\tLunatic",
            "5\t1\t1\t1\t2\t3\t290\t150\t180\t20\t95\t53,393,930",
        ]
    )

    def fake_run(args, capture_output, text, encoding, errors, check):
        assert args[0] == "tesseract"
        if args[-1] == "tsv":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=tsv_output,
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="garbled\nocr\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert len(mock_payload.entries) == 2
    assert mock_payload.entries[0]["rank"] == 1
    assert mock_payload.entries[0]["player_name"] == "Lunatic"
    assert mock_payload.entries[0]["score"] == 53404105
    assert mock_payload.entries[1]["rank"] == 2
    assert mock_payload.entries[1]["player_name"] == "Lunatic"
    assert mock_payload.entries[1]["score"] == 53393930


def test_build_mock_payload_from_capture_parses_tesseract_tsv_card_rank_from_nearby_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "garbled ocr\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-tesseract-tsv-nearby-rank-season",
        pages=[{"image_path": "page-001.png"}],
        snapshot={"captured_at": "2026-04-16T10:00:00Z"},
        ocr={"provider": "tesseract", "language": "kor+eng", "psm": 11},
    )

    header = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    )
    tsv_output = header + "\n".join(
        [
            "5\t1\t1\t1\t1\t1\t90\t70\t30\t18\t84\t1H",
            "5\t1\t1\t1\t2\t1\t170\t100\t90\t20\t94\tLunatic",
            "5\t1\t1\t1\t2\t2\t290\t100\t180\t20\t95\t53,404,105",
            "5\t1\t1\t1\t3\t1\t90\t170\t30\t18\t84\t2H",
            "5\t1\t1\t1\t4\t1\t170\t200\t90\t20\t94\tLunatic",
            "5\t1\t1\t1\t4\t2\t290\t200\t180\t20\t95\t53,393,930",
        ]
    )

    def fake_run(args, capture_output, text, encoding, errors, check):
        if args[-1] == "tsv":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=tsv_output,
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="bad\nocr\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert [entry["rank"] for entry in mock_payload.entries] == [1, 2]
    assert [entry["score"] for entry in mock_payload.entries] == [53404105, 53393930]


def test_build_mock_payload_from_capture_falls_back_to_score_anchor_lines(
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
        season_label="capture-score-anchor-lines-season",
        pages=[{"image_path": "page-001.png"}],
        snapshot={"captured_at": "2026-04-16T10:00:00Z"},
        ocr={"provider": "tesseract", "language": "eng", "psm": 11},
    )

    raw_ocr_output = "\n".join(
        [
            "ZA Ais",
            "1H",
            "Al Be 53,404,105",
            "OfFAU} E7]",
            "Lv.90 2Y",
            "Al Be",
            "[Lunatic] 53 393,930",
            "Lv.90 LfLt",
            "3H",
            "Al Be 53,393,544",
        ]
    )
    header = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    )

    def fake_run(args, capture_output, text, encoding, errors, check):
        if args[-1] == "tsv":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=header,
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=raw_ocr_output,
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert [entry["rank"] for entry in mock_payload.entries] == [1, 2, 3]
    assert [entry["player_name"] for entry in mock_payload.entries] == [
        "Lunatic",
        "Lunatic",
        "Lunatic",
    ]
    assert [entry["score"] for entry in mock_payload.entries] == [
        53404105,
        53393930,
        53393544,
    ]


def test_build_mock_payload_from_capture_score_anchor_lines_use_difficulty_aliases(
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
        season_label="capture-score-anchor-alias-season",
        pages=[{"image_path": "page-001.png"}],
        snapshot={"captured_at": "2026-04-16T10:00:00Z"},
        ocr={"provider": "tesseract", "language": "eng", "psm": 11},
    )

    raw_ocr_output = "\n".join(
        [
            "1H",
            "(Ginatie) 53,404,105",
            "Lv.90 ZY",
            ">",
            "(Inasane) 53,393,930",
            "3H",
            "(Tormemt) 53,393,544",
        ]
    )
    header = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    )

    def fake_run(args, capture_output, text, encoding, errors, check):
        if args[-1] == "tsv":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=header,
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=raw_ocr_output,
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    payload = load_capture_import_payload(tmp_path)
    mock_payload = build_mock_payload_from_capture(payload)

    assert [entry["rank"] for entry in mock_payload.entries] == [1, 2, 3]
    assert [entry["player_name"] for entry in mock_payload.entries] == [
        "Lunatic",
        "Insane",
        "Torment",
    ]
    assert [entry["score"] for entry in mock_payload.entries] == [
        53404105,
        53393930,
        53393544,
    ]


def test_find_layout_difficulty_accepts_common_ocr_variants() -> None:
    assert capture_import._resolve_difficulty_label("GINATIE") == "Lunatic"
    assert capture_import._resolve_difficulty_label("GMATI") == "Lunatic"
    assert capture_import._resolve_difficulty_label("INASANE") == "Insane"
    assert capture_import._resolve_difficulty_label("TORMEMT") == "Torment"


def test_resolve_anchor_ranks_interpolates_from_later_known_rank() -> None:
    assert capture_import._resolve_anchor_ranks([None, None, 12003]) == [
        12001,
        12002,
        12003,
    ]


def test_resolve_anchor_ranks_drops_inconsistent_outlier_rank() -> None:
    assert capture_import._resolve_anchor_ranks([1, None, 341]) == [1, 2, 3]


def test_realign_overlapping_page_entry_ranks_uses_score_and_difficulty_overlap() -> None:
    previous_page_entries = [
        {"rank": 1, "player_name": "Lunatic", "score": 53404105},
        {"rank": 2, "player_name": "Lunatic", "score": 53393930},
        {"rank": 3, "player_name": "Lunatic", "score": 53393544},
    ]
    current_page_entries = [
        {"rank": 1, "player_name": "Lunatic", "score": 53393544},
        {"rank": 2, "player_name": "Lunatic", "score": 53393449},
        {"rank": 3, "player_name": "Lunatic", "score": 53393449},
    ]

    realigned = capture_import._realign_overlapping_page_entry_ranks(
        previous_page_entries=previous_page_entries,
        current_page_entries=current_page_entries,
    )

    assert [entry["rank"] for entry in realigned] == [3, 4, 5]


def test_realign_overlapping_page_entry_ranks_anchors_from_middle_overlap() -> None:
    previous_page_entries = [
        {"rank": 3, "player_name": "Lunatic", "score": 53393544},
        {"rank": 4, "player_name": "Lunatic", "score": 53393449},
        {"rank": 5, "player_name": "Lunatic", "score": 53393449},
    ]
    current_page_entries = [
        {"rank": 1, "player_name": "Lunatic", "score": 99999999},
        {"rank": 2, "player_name": "Lunatic", "score": 53393449},
        {"rank": 3, "player_name": "Lunatic", "score": 53389034},
        {"rank": 4, "player_name": "Lunatic", "score": 53388458},
    ]

    realigned = capture_import._realign_overlapping_page_entry_ranks(
        previous_page_entries=previous_page_entries,
        current_page_entries=current_page_entries,
    )

    assert [entry["rank"] for entry in realigned] == [4, 5, 6, 7]


def test_realign_overlapping_page_entry_ranks_advances_past_trailing_duplicate_score_cluster() -> None:
    previous_page_entries = [
        {"rank": 3524, "player_name": "Torment", "score": 40090480},
        {"rank": 3525, "player_name": "Torment", "score": 40090160},
        {"rank": 3526, "player_name": "Torment", "score": 40090160},
    ]
    current_page_entries = [
        {"rank": 1, "player_name": "Torment", "score": 40090160},
        {"rank": 2, "player_name": "Torment", "score": 40089920},
    ]

    realigned = capture_import._realign_overlapping_page_entry_ranks(
        previous_page_entries=previous_page_entries,
        current_page_entries=current_page_entries,
    )

    assert [entry["rank"] for entry in realigned] == [3527, 3528]


def test_realign_overlapping_page_entry_ranks_continues_without_overlap_when_scores_descend() -> None:
    previous_page_entries = [
        {"rank": 3, "player_name": "Insane", "score": 27768256},
        {"rank": 4, "player_name": "Insane", "score": 27768256},
        {"rank": 5, "player_name": "Insane", "score": 27768192},
    ]
    current_page_entries = [
        {"rank": 1, "player_name": "Insane", "score": 27768064},
        {"rank": 2, "player_name": "Insane", "score": 27767936},
    ]

    realigned = capture_import._realign_overlapping_page_entry_ranks(
        previous_page_entries=previous_page_entries,
        current_page_entries=current_page_entries,
    )

    assert [entry["rank"] for entry in realigned] == [6, 7]


def test_parse_capture_payload_realigns_blue_archive_page_ranks_from_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _entry(rank: int, score: int, image_name: str) -> dict[str, object]:
        return {
            "rank": rank,
            "player_name": "Lunatic",
            "score": score,
            "ocr_confidence": None,
            "raw_text": "",
            "image_path": image_name,
            "is_valid": True,
            "validation_issue": None,
        }

    _write_capture_page(tmp_path, "page-001.png", "unused\n")
    _write_capture_page(tmp_path, "page-002.png", "unused\n")
    _write_capture_page(tmp_path, "page-003.png", "unused\n")
    _write_capture_manifest(
        tmp_path,
        season_label="capture-blue-archive-overlap-realign-season",
        pages=[
            {"image_path": "page-001.png"},
            {"image_path": "page-002.png"},
            {"image_path": "page-003.png"},
        ],
    )

    page_entries_by_index = {
        1: [
            _entry(1, 53404105, "page-001.png"),
            _entry(2, 53393930, "page-001.png"),
            _entry(3, 53393544, "page-001.png"),
        ],
        2: [
            _entry(1, 53393544, "page-002.png"),
            _entry(2, 53393449, "page-002.png"),
            _entry(3, 53393449, "page-002.png"),
        ],
        3: [
            _entry(1, 53393449, "page-003.png"),
            _entry(2, 53389034, "page-003.png"),
            _entry(3, 53388458, "page-003.png"),
        ],
    }

    monkeypatch.setattr(capture_import, "_load_ocr_text", lambda **kwargs: "unused")
    monkeypatch.setattr(
        capture_import,
        "_parse_page_entries",
        lambda **kwargs: (page_entries_by_index[kwargs["page_index"]], []),
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert [entry["rank"] for entry in parsed_payload.mock_payload.entries] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [
        (
            summary["first_rank"],
            summary["last_rank"],
            summary["overlap_with_previous_count"],
            summary["new_rank_count"],
        )
        for summary in parsed_payload.page_summaries
    ] == [
        (1, 3, 0, 3),
        (3, 5, 1, 2),
        (6, 8, 0, 3),
    ]


def test_parse_capture_payload_realigns_blue_archive_page_ranks_from_middle_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _entry(rank: int, score: int, image_name: str) -> dict[str, object]:
        return {
            "rank": rank,
            "player_name": "Lunatic",
            "score": score,
            "ocr_confidence": None,
            "raw_text": "",
            "image_path": image_name,
            "is_valid": True,
            "validation_issue": None,
        }

    _write_capture_page(tmp_path, "page-001.png", "unused\n")
    _write_capture_page(tmp_path, "page-002.png", "unused\n")
    _write_capture_page(tmp_path, "page-003.png", "unused\n")
    _write_capture_manifest(
        tmp_path,
        season_label="capture-blue-archive-middle-overlap-season",
        pages=[
            {"image_path": "page-001.png"},
            {"image_path": "page-002.png"},
            {"image_path": "page-003.png"},
        ],
    )

    page_entries_by_index = {
        1: [
            _entry(1, 53404105, "page-001.png"),
            _entry(2, 53393930, "page-001.png"),
            _entry(3, 53393544, "page-001.png"),
        ],
        2: [
            _entry(1, 53393544, "page-002.png"),
            _entry(2, 53393449, "page-002.png"),
            _entry(3, 53393449, "page-002.png"),
        ],
        3: [
            _entry(1, 99999999, "page-003.png"),
            _entry(2, 53393449, "page-003.png"),
            _entry(3, 53389034, "page-003.png"),
            _entry(4, 53388458, "page-003.png"),
        ],
    }

    monkeypatch.setattr(capture_import, "_load_ocr_text", lambda **kwargs: "unused")
    monkeypatch.setattr(
        capture_import,
        "_parse_page_entries",
        lambda **kwargs: (page_entries_by_index[kwargs["page_index"]], []),
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert [entry["rank"] for entry in parsed_payload.mock_payload.entries] == [1, 2, 3, 4, 5, 6, 7]
    assert parsed_payload.page_summaries[2]["first_rank"] == 4
    assert parsed_payload.page_summaries[2]["last_rank"] == 7
    assert parsed_payload.page_summaries[2]["overlap_with_previous_ranks"] == [4, 5]


def test_parse_capture_payload_realigns_blue_archive_torment_duplicate_score_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _entry(rank: int, score: int, image_name: str) -> dict[str, object]:
        return {
            "rank": rank,
            "player_name": "Torment",
            "score": score,
            "ocr_confidence": None,
            "raw_text": "",
            "image_path": image_name,
            "is_valid": True,
            "validation_issue": None,
        }

    _write_capture_page(tmp_path, "page-001.png", "unused\n")
    _write_capture_page(tmp_path, "page-002.png", "unused\n")
    _write_capture_page(tmp_path, "page-003.png", "unused\n")
    _write_capture_manifest(
        tmp_path,
        season_label="capture-blue-archive-torment-overlap-season",
        pages=[
            {"image_path": "page-001.png"},
            {"image_path": "page-002.png"},
            {"image_path": "page-003.png"},
        ],
    )

    page_entries_by_index = {
        1: [
            _entry(3522, 40100000, "page-001.png"),
            _entry(3523, 40097600, "page-001.png"),
            _entry(3524, 40090640, "page-001.png"),
        ],
        2: [
            _entry(1, 40090640, "page-002.png"),
            _entry(2, 40090480, "page-002.png"),
            _entry(3, 40090160, "page-002.png"),
        ],
        3: [
            _entry(1, 40090160, "page-003.png"),
            _entry(2, 40089920, "page-003.png"),
        ],
    }

    monkeypatch.setattr(capture_import, "_load_ocr_text", lambda **kwargs: "unused")
    monkeypatch.setattr(
        capture_import,
        "_parse_page_entries",
        lambda **kwargs: (page_entries_by_index[kwargs["page_index"]], []),
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert [entry["rank"] for entry in parsed_payload.mock_payload.entries] == [
        3522,
        3523,
        3524,
        3525,
        3526,
        3527,
        3528,
    ]
    assert [
        (summary["first_rank"], summary["last_rank"])
        for summary in parsed_payload.page_summaries
    ] == [
        (3522, 3524),
        (3524, 3526),
        (3527, 3528),
    ]


def test_parse_capture_payload_realigns_blue_archive_insane_duplicate_score_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _entry(rank: int, score: int, image_name: str) -> dict[str, object]:
        return {
            "rank": rank,
            "player_name": "Insane",
            "score": score,
            "ocr_confidence": None,
            "raw_text": "",
            "image_path": image_name,
            "is_valid": True,
            "validation_issue": None,
        }

    _write_capture_page(tmp_path, "page-001.png", "unused\n")
    _write_capture_page(tmp_path, "page-002.png", "unused\n")
    _write_capture_manifest(
        tmp_path,
        season_label="capture-blue-archive-insane-overlap-season",
        pages=[
            {"image_path": "page-001.png"},
            {"image_path": "page-002.png"},
        ],
    )

    page_entries_by_index = {
        1: [
            _entry(16109, 27771072, "page-001.png"),
            _entry(16110, 27770049, "page-001.png"),
            _entry(16111, 27768256, "page-001.png"),
        ],
        2: [
            _entry(1, 27768256, "page-002.png"),
            _entry(2, 27768256, "page-002.png"),
            _entry(3, 27768192, "page-002.png"),
        ],
    }

    monkeypatch.setattr(capture_import, "_load_ocr_text", lambda **kwargs: "unused")
    monkeypatch.setattr(
        capture_import,
        "_parse_page_entries",
        lambda **kwargs: (page_entries_by_index[kwargs["page_index"]], []),
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert [entry["rank"] for entry in parsed_payload.mock_payload.entries] == [
        16109,
        16110,
        16111,
        16112,
        16113,
    ]
    assert parsed_payload.page_summaries[1]["first_rank"] == 16111
    assert parsed_payload.page_summaries[1]["last_rank"] == 16113


def test_parse_capture_payload_realigns_blue_archive_insane_without_overlap_from_score_descent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _entry(rank: int, score: int, image_name: str) -> dict[str, object]:
        return {
            "rank": rank,
            "player_name": "Insane",
            "score": score,
            "ocr_confidence": None,
            "raw_text": "",
            "image_path": image_name,
            "is_valid": True,
            "validation_issue": None,
        }

    _write_capture_page(tmp_path, "page-001.png", "unused\n")
    _write_capture_page(tmp_path, "page-002.png", "unused\n")
    _write_capture_page(tmp_path, "page-003.png", "unused\n")
    _write_capture_manifest(
        tmp_path,
        season_label="capture-blue-archive-insane-non-overlap-season",
        pages=[
            {"image_path": "page-001.png"},
            {"image_path": "page-002.png"},
            {"image_path": "page-003.png"},
        ],
    )

    page_entries_by_index = {
        1: [
            _entry(16109, 27771072, "page-001.png"),
            _entry(16110, 27770049, "page-001.png"),
            _entry(16111, 27768256, "page-001.png"),
        ],
        2: [
            _entry(1, 27768256, "page-002.png"),
            _entry(2, 27768256, "page-002.png"),
            _entry(3, 27768192, "page-002.png"),
        ],
        3: [
            _entry(1, 27768064, "page-003.png"),
            _entry(2, 27767936, "page-003.png"),
        ],
    }

    monkeypatch.setattr(capture_import, "_load_ocr_text", lambda **kwargs: "unused")
    monkeypatch.setattr(
        capture_import,
        "_parse_page_entries",
        lambda **kwargs: (page_entries_by_index[kwargs["page_index"]], []),
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)

    assert [entry["rank"] for entry in parsed_payload.mock_payload.entries] == [
        16109,
        16110,
        16111,
        16112,
        16113,
        16114,
        16115,
    ]
    assert [
        (summary["first_rank"], summary["last_rank"])
        for summary in parsed_payload.page_summaries
    ] == [
        (16109, 16111),
        (16111, 16113),
        (16114, 16115),
    ]


def test_select_blue_archive_absolute_retrofit_anchor_prefers_consistent_later_base() -> None:
    parsed_pages = [
        [
            {"rank": 1, "player_name": "Torment", "score": 40100000},
            {"rank": 2, "player_name": "Torment", "score": 40097600},
            {"rank": 3, "player_name": "Torment", "score": 40090640},
        ],
        [
            {"rank": 1, "player_name": "Torment", "score": 40090640},
            {"rank": 2, "player_name": "Torment", "score": 40090480},
            {"rank": 3, "player_name": "Torment", "score": 40090160},
        ],
        [
            {"rank": 1, "player_name": "Torment", "score": 40090160},
            {"rank": 2, "player_name": "Torment", "score": 40089920},
        ],
    ]
    page_metadata = [
        {
            "absolute_rank_base": 2001,
            "absolute_rank_base_source": "row_base",
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
        },
        {
            "absolute_rank_base": 3524,
            "absolute_rank_base_source": "row_base",
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
        },
        {
            "absolute_rank_base": None,
            "absolute_rank_base_source": None,
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
        },
    ]

    assert capture_import._select_blue_archive_absolute_retrofit_anchor(
        parsed_pages=parsed_pages,
        page_metadata=page_metadata,
    ) == (1, 3524)


def test_parse_blue_archive_rank_candidate_trims_common_ui_suffix_noise() -> None:
    assert capture_import._parse_blue_archive_rank_candidate("1200147") == 12001
    assert capture_import._parse_blue_archive_rank_candidate("1200291") == 12002
    assert capture_import._parse_blue_archive_rank_candidate("1200347") == 12003
    assert capture_import._parse_blue_archive_rank_candidate("1611091") == 16110
    assert capture_import._parse_blue_archive_rank_candidate("Rank 3522") == 3522
    assert capture_import._parse_blue_archive_rank_candidate("Rank16109") == 16109


def test_extract_rank_candidates_from_text_accepts_rank_prefix() -> None:
    assert capture_import._extract_rank_candidates_from_text("Rank 3522") == [3522]
    assert capture_import._extract_rank_candidates_from_text("Rank16109") == [16109]


def test_normalize_tesseract_page_entry_ranks_resolves_duplicate_rank() -> None:
    entries = [
        {"rank": 1, "score": 53404105, "player_name": "Lunatic"},
        {"rank": 1, "score": 53393930, "player_name": "Lunatic"},
        {"rank": 3, "score": 53393544, "player_name": "Lunatic"},
    ]

    normalized = capture_import._normalize_tesseract_page_entry_ranks(entries)

    assert [entry["rank"] for entry in normalized] == [1, 2, 3]


def test_parse_blue_archive_fixed_rows_assembles_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_combined_fields",
        lambda **kwargs: (None, None, None),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank",
        lambda **kwargs: {0.02: 12001, 0.35: 12002, 0.69: 12003}[kwargs["top_ratio"]],
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_difficulty",
        lambda **kwargs: "Torment",
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_score",
        lambda **kwargs: {0.02: 40040720, 0.35: 40040720, 0.69: 40040641}[kwargs["top_ratio"]],
    )

    entries = capture_import._parse_blue_archive_fixed_rows(
        prepared_image_path=Path("page-001.png"),
        image_path=Path("page-001.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=None,
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        default_ocr_confidence=None,
        page_index=1,
    )

    assert [(entry["rank"], entry["player_name"], entry["score"]) for entry in entries] == [
        (12001, "Torment", 40040720),
        (12002, "Torment", 40040720),
        (12003, "Torment", 40040641),
    ]


def test_parse_blue_archive_fixed_rows_propagates_page_difficulty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_detect_blue_archive_row_bands",
        lambda prepared_image_path: (
            (0.02, 0.31),
            (0.35, 0.65),
            (0.69, 0.98),
        ),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_combined_fields",
        lambda **kwargs: (None, None, None),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank",
        lambda **kwargs: {0.02: 12001, 0.35: 12002, 0.69: 12003}[kwargs["top_ratio"]],
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_difficulty",
        lambda **kwargs: "Torment" if kwargs["top_ratio"] == 0.02 else None,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_score",
        lambda **kwargs: {
            0.02: 40040720,
            0.35: 40040720,
            0.69: 40040641,
        }[kwargs["top_ratio"]],
    )

    entries = capture_import._parse_blue_archive_fixed_rows(
        prepared_image_path=Path("page.png"),
        image_path=Path("page.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=None,
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        default_ocr_confidence=None,
        page_index=1,
    )

    assert [(entry["rank"], entry["player_name"], entry["score"]) for entry in entries] == [
        (12001, "Torment", 40040720),
        (12002, "Torment", 40040720),
        (12003, "Torment", 40040641),
    ]


def test_parse_blue_archive_fixed_rows_uses_absolute_rank_anchor_when_row_ranks_fall_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_detect_blue_archive_row_bands",
        lambda prepared_image_path: (
            (0.02, 0.31),
            (0.35, 0.65),
            (0.69, 0.98),
        ),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_combined_fields",
        lambda **kwargs: (None, None, None),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor",
        lambda **kwargs: 3522,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_difficulty",
        lambda **kwargs: "Torment",
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_score",
        lambda **kwargs: {
            0.02: 40100000,
            0.35: 40097600,
            0.69: 40090640,
        }[kwargs["top_ratio"]],
    )

    entries = capture_import._parse_blue_archive_fixed_rows(
        prepared_image_path=Path("page.png"),
        image_path=Path("page.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=None,
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        default_ocr_confidence=None,
        page_index=1,
    )

    assert [entry["rank"] for entry in entries] == [3522, 3523, 3524]


def test_parse_blue_archive_fixed_rows_uses_original_anchor_when_prepared_anchor_is_small_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_detect_blue_archive_row_bands",
        lambda prepared_image_path: (
            (0.02, 0.31),
            (0.35, 0.65),
            (0.69, 0.98),
        ),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_combined_fields",
        lambda **kwargs: (None, "Torment", 40_100_000),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank_from_original_image",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_difficulty",
        lambda **kwargs: "Torment",
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_score",
        lambda **kwargs: 40_100_000,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor",
        lambda **kwargs: 20,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor_from_original_image",
        lambda **kwargs: 3522,
    )

    entries = capture_import._parse_blue_archive_fixed_rows(
        image_path=Path("page.png"),
        prepared_image_path=Path("prepared.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.37,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        default_ocr_confidence=0.9,
        page_index=1,
    )

    assert [entry["rank"] for entry in entries] == [3522, 3523, 3524]
    assert entries[0]["_absolute_rank_anchor_source"] == "original"


def test_parse_blue_archive_fixed_rows_ignores_small_absolute_anchor_on_later_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_detect_blue_archive_row_bands",
        lambda prepared_image_path: (
            (0.02, 0.31),
            (0.35, 0.65),
            (0.69, 0.98),
        ),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_combined_fields",
        lambda **kwargs: (None, "Torment", 40_100_000),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank_from_original_image",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_difficulty",
        lambda **kwargs: "Torment",
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_score",
        lambda **kwargs: 40_100_000,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor",
        lambda **kwargs: 20,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor_from_original_image",
        lambda **kwargs: None,
    )

    entries = capture_import._parse_blue_archive_fixed_rows(
        image_path=Path("page.png"),
        prepared_image_path=Path("prepared.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.37,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        default_ocr_confidence=0.9,
        page_index=2,
    )

    assert [entry["rank"] for entry in entries] == [1, 2, 3]
    assert entries[0]["_absolute_rank_anchor"] is None


def test_parse_blue_archive_fixed_rows_keeps_row_base_when_anchor_deviates_too_far(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_detect_blue_archive_row_bands",
        lambda prepared_image_path: (
            (0.02, 0.31),
            (0.35, 0.65),
            (0.69, 0.98),
        ),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_combined_fields",
        lambda **kwargs: (None, "Torment", 40_100_000),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank",
        lambda **kwargs: None,
    )
    row_ranks = iter([3522, 3523, 3524])
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank_from_original_image",
        lambda **kwargs: next(row_ranks),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_difficulty",
        lambda **kwargs: "Torment",
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_score",
        lambda **kwargs: 40_100_000,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor",
        lambda **kwargs: 12001,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor_from_original_image",
        lambda **kwargs: 12001,
    )

    entries = capture_import._parse_blue_archive_fixed_rows(
        image_path=Path("page.png"),
        prepared_image_path=Path("prepared.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.37,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        default_ocr_confidence=0.9,
        page_index=1,
    )

    assert [entry["rank"] for entry in entries] == [3522, 3523, 3524]
    assert entries[0]["_absolute_rank_anchor_source"] == "row_base"


def test_parse_blue_archive_fixed_rows_ignores_small_original_row_rank_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_detect_blue_archive_row_bands",
        lambda prepared_image_path: (
            (0.02, 0.31),
            (0.35, 0.65),
            (0.69, 0.98),
        ),
    )
    combined = iter(
        [
            (1, "Torment", 40_100_000),
            (2, "Torment", 40_097_600),
            (3, "Torment", 40_090_640),
        ]
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_combined_fields",
        lambda **kwargs: next(combined),
    )
    small_original_ranks = iter([20, 21, 22, 20, 21, 22])
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank_from_original_image",
        lambda **kwargs: next(small_original_ranks),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor_from_original_image",
        lambda **kwargs: None,
    )

    entries = capture_import._parse_blue_archive_fixed_rows(
        image_path=Path("page.png"),
        prepared_image_path=Path("prepared.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.37,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        default_ocr_confidence=0.9,
        page_index=1,
    )

    assert [entry["rank"] for entry in entries] == [1, 2, 3]


def test_parse_blue_archive_fixed_rows_uses_original_row_rank_on_later_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_detect_blue_archive_row_bands",
        lambda prepared_image_path: (
            (0.02, 0.31),
            (0.35, 0.65),
            (0.69, 0.98),
        ),
    )
    combined = iter(
        [
            (1, "Insane", 27_771_072),
            (2, "Insane", 27_770_049),
            (3, "Insane", 27_768_256),
        ]
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_combined_fields",
        lambda **kwargs: next(combined),
    )
    original_ranks = iter([16109, 16110, 16111, 16109, 16110, 16111])
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank_from_original_image",
        lambda **kwargs: next(original_ranks),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor_from_original_image",
        lambda **kwargs: None,
    )

    entries = capture_import._parse_blue_archive_fixed_rows(
        image_path=Path("page.png"),
        prepared_image_path=Path("prepared.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.37,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        default_ocr_confidence=0.9,
        page_index=2,
    )

    assert [entry["rank"] for entry in entries] == [16109, 16110, 16111]
    assert entries[0]["_absolute_rank_base"] == 16109
    assert entries[0]["_absolute_rank_base_source"] == "row_base"


def test_parse_blue_archive_fixed_rows_skips_anchor_ocr_when_row_ranks_are_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_detect_blue_archive_row_bands",
        lambda prepared_image_path: (
            (0.02, 0.31),
            (0.35, 0.65),
            (0.69, 0.98),
        ),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_combined_fields",
        lambda **kwargs: (None, "Torment", 40_100_000),
    )
    original_ranks = iter([3522, 3523, 3524])
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank_from_original_image",
        lambda **kwargs: next(original_ranks),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("anchor OCR should be skipped")),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_page_absolute_rank_anchor_from_original_image",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("original anchor OCR should be skipped")),
    )

    entries = capture_import._parse_blue_archive_fixed_rows(
        image_path=Path("page.png"),
        prepared_image_path=Path("prepared.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.37,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        default_ocr_confidence=0.9,
        page_index=1,
    )

    assert [entry["rank"] for entry in entries] == [3522, 3523, 3524]
    assert entries[0]["_absolute_rank_base"] == 3522


def test_select_blue_archive_row_rank_prefers_original_absolute_rank() -> None:
    assert capture_import._select_blue_archive_row_rank(
        prepared_rank=10001,
        original_rank=3522,
        visible_row_count=3,
    ) == 3522


def test_select_blue_archive_row_rank_prefers_small_original_top_rank_over_large_noise() -> None:
    assert capture_import._select_blue_archive_row_rank(
        prepared_rank=534,
        original_rank=1,
        visible_row_count=3,
    ) == 1


def test_select_blue_archive_row_rank_keeps_prepared_small_rank_when_original_is_small_noise() -> None:
    assert capture_import._select_blue_archive_row_rank(
        prepared_rank=3,
        original_rank=20,
        visible_row_count=3,
    ) == 3


def test_ocr_blue_archive_page_absolute_rank_anchor_accepts_large_numeric_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_ocr_prepared_image_ratio_region_candidates",
        lambda **kwargs: ["3522", "3522", "40,100,000"] if kwargs["x_ratios"][1] <= 0.52 else ["40,100,000"],
    )

    anchor = capture_import._ocr_blue_archive_page_absolute_rank_anchor(
        prepared_image_path=Path("page.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=None,
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        row_bands=((0.02, 0.31), (0.35, 0.65), (0.69, 0.98)),
        resolved_ranks=[1, 2, 3],
    )

    assert anchor == 3522


def test_ocr_blue_archive_page_absolute_rank_anchor_from_original_image_uses_rank_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_prepare_image_for_ocr",
        lambda image_path, ocr: (Path("prepared.png"), lambda: None),
    )
    monkeypatch.setattr(
        capture_import,
        "_run_tesseract_command",
        lambda **kwargs: "Rank 3522\nTorment 40,100,000",
    )

    anchor = capture_import._ocr_blue_archive_page_absolute_rank_anchor_from_original_image(
        image_path=Path(__file__),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=None,
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        row_bands=((0.02, 0.31), (0.35, 0.65), (0.69, 0.98)),
        resolved_ranks=[1, 2, 3],
        page_index=1,
    )

    assert anchor == 3522


def test_ocr_blue_archive_page_absolute_rank_anchor_from_original_image_accepts_small_relative_ranks_on_page_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_prepare_image_for_ocr",
        lambda image_path, ocr: (Path("prepared.png"), lambda: None),
    )
    monkeypatch.setattr(
        capture_import,
        "_run_tesseract_command",
        lambda **kwargs: "3522",
    )

    anchor = capture_import._ocr_blue_archive_page_absolute_rank_anchor_from_original_image(
        image_path=Path(__file__),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.39,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        row_bands=((0.02, 0.31), (0.35, 0.65), (0.69, 0.98)),
        resolved_ranks=[20, 21],
        page_index=1,
    )

    assert anchor == 3522


def test_ocr_blue_archive_page_absolute_rank_anchor_from_original_image_keeps_parsing_after_noisy_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_prepare_image_for_ocr",
        lambda image_path, ocr: (Path("prepared.png"), lambda: None),
    )
    texts = cycle(["Rank 20", "3522"])
    monkeypatch.setattr(
        capture_import,
        "_run_tesseract_command",
        lambda **kwargs: next(texts),
    )

    anchor = capture_import._ocr_blue_archive_page_absolute_rank_anchor_from_original_image(
        image_path=Path(__file__),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.37,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        row_bands=((0.02, 0.31), (0.35, 0.65), (0.69, 0.98)),
        resolved_ranks=[1, 2, 3],
        page_index=1,
    )

    assert anchor == 3522


def test_ocr_blue_archive_row_rank_from_original_image_prefers_longer_absolute_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_prepare_image_for_ocr",
        lambda image_path, ocr: (Path("prepared.png"), lambda: None),
    )
    texts = cycle(["Rank 20", "Rank 3522"])
    monkeypatch.setattr(
        capture_import,
        "_run_tesseract_command",
        lambda **kwargs: next(texts),
    )

    rank = capture_import._ocr_blue_archive_row_rank_from_original_image(
        image_path=Path(__file__),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.37,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        top_ratio=0.02,
        bottom_ratio=0.31,
    )

    assert rank == 3522


def test_ocr_blue_archive_row_rank_from_original_image_joins_split_rank_digits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_prepare_image_for_ocr",
        lambda image_path, ocr: (Path("prepared.png"), lambda: None),
    )
    monkeypatch.setattr(
        capture_import,
        "_run_tesseract_command",
        lambda **kwargs: "Rank 35 22\nTorment 40,100,000",
    )

    rank = capture_import._ocr_blue_archive_row_rank_from_original_image(
        image_path=Path(__file__),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.37,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        top_ratio=0.02,
        bottom_ratio=0.31,
    )

    assert rank == 3522


def test_parse_blue_archive_rank_candidate_accepts_common_ocr_digit_substitutions() -> None:
    assert capture_import._parse_blue_archive_rank_candidate("3S22") == 3522
    assert capture_import._parse_blue_archive_rank_candidate("16I09") == 16109
    assert capture_import._parse_blue_archive_rank_candidate("12OO1") == 12001


def test_resolve_tesseract_input_path_converts_wsl_path_for_windows_exe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(args, **kwargs):
        assert args == ["wslpath", "-w", "/tmp/plana-ocr-crop-demo.png"]
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="C:\\Temp\\plana-ocr-crop-demo.png\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    resolved = capture_import._resolve_tesseract_input_path(
        "/mnt/c/Program Files/Tesseract-OCR/tesseract.exe",
        Path("/tmp/plana-ocr-crop-demo.png"),
    )

    assert resolved == "C:\\Temp\\plana-ocr-crop-demo.png"


def test_resolve_tesseract_input_path_keeps_path_for_non_windows_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_run(args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("wslpath should not be called")

    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    resolved = capture_import._resolve_tesseract_input_path(
        "tesseract",
        Path("/tmp/plana-ocr-crop-demo.png"),
    )

    assert resolved == "/tmp/plana-ocr-crop-demo.png"
    assert called is False


def test_extract_rank_candidates_from_text_joins_split_rank_digits() -> None:
    assert capture_import._extract_rank_candidates_from_text("Rank 35 22 Torment 40,100,000") == [3522]
    assert capture_import._extract_rank_candidates_from_text("Rank 16 109 Insane 27,771,072") == [16109]


def test_ocr_blue_archive_row_rank_from_original_image_uses_rank_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_prepare_image_for_ocr",
        lambda image_path, ocr: (Path("prepared.png"), lambda: None),
    )
    monkeypatch.setattr(
        capture_import,
        "_run_tesseract_command",
        lambda **kwargs: "Rank 3522\nTorment 40,100,000",
    )

    rank = capture_import._ocr_blue_archive_row_rank_from_original_image(
        image_path=Path(__file__),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.37,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        top_ratio=0.02,
        bottom_ratio=0.31,
    )

    assert rank == 3522


def test_should_attempt_blue_archive_absolute_rank_anchor_for_small_contiguous_ranks() -> None:
    assert capture_import._should_attempt_blue_archive_absolute_rank_anchor([1, 2, 3]) is True
    assert capture_import._should_attempt_blue_archive_absolute_rank_anchor([20, 21]) is True
    assert capture_import._should_attempt_blue_archive_absolute_rank_anchor([3522, 3523]) is False
    assert capture_import._should_attempt_blue_archive_absolute_rank_anchor([20, 22]) is False


def test_resolve_blue_archive_absolute_rank_base_from_detected_ranks() -> None:
    assert (
        capture_import._resolve_blue_archive_absolute_rank_base_from_detected_ranks(
            [3522, None, 3524]
        )
        == 3522
    )
    assert (
        capture_import._resolve_blue_archive_absolute_rank_base_from_detected_ranks(
            [None, 16110, None]
        )
        == 16109
    )
    assert (
        capture_import._resolve_blue_archive_absolute_rank_base_from_detected_ranks(
            [1, 2, 3]
        )
        is None
    )


def test_select_preferred_blue_archive_rank_candidate_prefers_longer_numbers() -> None:
    assert capture_import._select_preferred_blue_archive_rank_candidate([20, 3522, 20]) == 3522
    assert capture_import._select_preferred_blue_archive_rank_candidate([16109, 12001, 12001]) == 12001
    assert capture_import._select_preferred_blue_archive_rank_candidate([]) is None


def test_is_valid_blue_archive_absolute_anchor() -> None:
    assert capture_import._is_valid_blue_archive_absolute_anchor(3522, page_index=1) is True
    assert capture_import._is_valid_blue_archive_absolute_anchor(20, page_index=1) is False
    assert capture_import._is_valid_blue_archive_absolute_anchor(None, page_index=1) is False
    assert capture_import._is_valid_blue_archive_absolute_anchor(20, page_index=2) is False


def test_resolve_blue_archive_absolute_rank_base_from_original_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row_ranks = iter([None, 16110, None])
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank_from_original_image",
        lambda **kwargs: next(row_ranks),
    )

    base_rank = capture_import._resolve_blue_archive_absolute_rank_base_from_original_rows(
        image_path=Path("page.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.37,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        row_bands=((0.02, 0.31), (0.35, 0.65), (0.69, 0.98)),
    )

    assert base_rank == 16109


def test_resolve_blue_archive_page_difficulty_prefers_higher_difficulty_on_tie() -> None:
    difficulty = capture_import._resolve_blue_archive_page_difficulty(
        [
            {"player_name": "Torment"},
            {"player_name": "Insane"},
            {"player_name": "Lunatic"},
            {"player_name": "Torment"},
            {"player_name": "Lunatic"},
        ]
    )

    assert difficulty == "Lunatic"


def test_retrofit_blue_archive_absolute_page_ranks_uses_later_page_base() -> None:
    parsed_pages = [
        [
            {"rank": 1, "score": 100, "player_name": "Torment"},
            {"rank": 2, "score": 90, "player_name": "Torment"},
            {"rank": 3, "score": 80, "player_name": "Torment"},
        ],
        [
            {"rank": 3, "score": 80, "player_name": "Torment"},
            {"rank": 4, "score": 70, "player_name": "Torment"},
            {"rank": 5, "score": 60, "player_name": "Torment"},
        ],
        [
            {"rank": 5, "score": 60, "player_name": "Torment"},
            {"rank": 6, "score": 50, "player_name": "Torment"},
            {"rank": 7, "score": 40, "player_name": "Torment"},
        ],
    ]
    page_metadata = [
        {
            "page_index": 1,
            "image_path": "page-001.png",
            "ignored_lines": [],
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
            "absolute_rank_base": None,
            "absolute_rank_base_source": None,
        },
        {
            "page_index": 2,
            "image_path": "page-002.png",
            "ignored_lines": [],
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
            "absolute_rank_base": 3524,
            "absolute_rank_base_source": "row_base",
        },
        {
            "page_index": 3,
            "image_path": "page-003.png",
            "ignored_lines": [],
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
            "absolute_rank_base": None,
            "absolute_rank_base_source": None,
        },
    ]

    adjusted_pages, adjusted_metadata = capture_import._retrofit_blue_archive_absolute_page_ranks(
        parsed_pages=parsed_pages,
        page_metadata=page_metadata,
    )

    assert [entry["rank"] for entry in adjusted_pages[0]] == [3522, 3523, 3524]
    assert [entry["rank"] for entry in adjusted_pages[1]] == [3524, 3525, 3526]
    assert [entry["rank"] for entry in adjusted_pages[2]] == [3526, 3527, 3528]
    assert adjusted_metadata[0]["absolute_rank_base"] == 3522
    assert adjusted_metadata[0]["absolute_rank_base_source"] == "retrofit"
    assert adjusted_metadata[1]["absolute_rank_base"] == 3524
    assert adjusted_metadata[1]["absolute_rank_base_source"] == "row_base"
    assert adjusted_metadata[2]["absolute_rank_base"] == 3526
    assert adjusted_metadata[2]["absolute_rank_base_source"] == "retrofit"


def test_parse_blue_archive_fixed_rows_rejects_increasing_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_detect_blue_archive_row_bands",
        lambda prepared_image_path: (
            (0.02, 0.31),
            (0.35, 0.65),
            (0.69, 0.98),
        ),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_combined_fields",
        lambda **kwargs: (None, None, None),
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank",
        lambda **kwargs: {0.02: 12001, 0.35: 12002, 0.69: 12003}[kwargs["top_ratio"]],
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_difficulty",
        lambda **kwargs: "Torment",
    )
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_score",
        lambda **kwargs: {
            0.02: 40040720,
            0.35: 40050000,
            0.69: 40040641,
        }[kwargs["top_ratio"]],
    )

    entries = capture_import._parse_blue_archive_fixed_rows(
        prepared_image_path=Path("page.png"),
        image_path=Path("page.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=None,
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        default_ocr_confidence=None,
        page_index=1,
    )

    assert entries == []


def test_ocr_blue_archive_row_rank_uses_majority_vote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_ocr_prepared_image_ratio_region_candidates",
        lambda **kwargs: ["1200147", "12001", "1200147"],
    )

    rank = capture_import._ocr_blue_archive_row_rank(
        prepared_image_path=Path("page.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=None,
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        top_ratio=0.02,
        bottom_ratio=0.31,
    )

    assert rank == 12001


def test_ocr_blue_archive_row_rank_prefers_rank_prefixed_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_ocr_prepared_image_ratio_region_candidates",
        lambda **kwargs: ["3522", "Rank 3522", "Rank 3522"],
    )

    rank = capture_import._ocr_blue_archive_row_rank(
        prepared_image_path=Path("page.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=None,
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        top_ratio=0.02,
        bottom_ratio=0.31,
    )

    assert rank == 3522


def test_ocr_blue_archive_row_difficulty_uses_majority_vote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_ocr_prepared_image_ratio_region_candidates",
        lambda **kwargs: ["Ginatie", "Lunatic", "Ginatie"],
    )

    difficulty = capture_import._ocr_blue_archive_row_difficulty(
        prepared_image_path=Path("page.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=None,
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        top_ratio=0.02,
        bottom_ratio=0.31,
    )

    assert difficulty == "Lunatic"


def test_ocr_blue_archive_row_score_uses_majority_vote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_ocr_prepared_image_ratio_region_candidates",
        lambda **kwargs: ["40,040,720", "40,040,720", "40,040,120"],
    )

    score = capture_import._ocr_blue_archive_row_score(
        prepared_image_path=Path("page.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=None,
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        top_ratio=0.02,
        bottom_ratio=0.31,
        page_index=1,
    )

    assert score == 40040720


@pytest.mark.parametrize("image_size", [(2400, 1080), (2340, 1080), (1600, 900)])
def test_parse_tesseract_layout_entries_prefers_blue_archive_fixed_rows(
    image_size: tuple[int, int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "blue-archive-page.png"
    from PIL import Image

    Image.new("RGB", image_size, color="white").save(image_path)

    monkeypatch.setattr(
        capture_import,
        "_prepare_image_for_ocr",
        lambda image_path, ocr: (image_path, lambda: None),
    )
    monkeypatch.setattr(
        capture_import,
        "_parse_blue_archive_fixed_rows",
        lambda **kwargs: [
            {"rank": 12001, "score": 40040720, "player_name": "Torment"},
            {"rank": 12002, "score": 40040720, "player_name": "Torment"},
            {"rank": 12003, "score": 40040641, "player_name": "Torment"},
        ],
    )
    monkeypatch.setattr(
        capture_import,
        "_run_tesseract_command",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("TSV보다 fixed rows가 먼저여야 합니다")),
    )

    entries = capture_import._parse_tesseract_layout_entries(
        image_path=image_path,
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.39,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        default_ocr_confidence=None,
        page_index=1,
    )

    assert [(entry["rank"], entry["player_name"], entry["score"]) for entry in entries] == [
        (12001, "Torment", 40040720),
        (12002, "Torment", 40040720),
        (12003, "Torment", 40040641),
    ]


@pytest.mark.parametrize(
    ("fixture_name", "expected_starts"),
    [
        ("lunatic-page-001.png", (0.036, 0.258, 0.568)),
        ("torment-page-001.png", (0.036, 0.258, 0.568)),
        ("insane-page-001.png", (0.036, 0.258, 0.568)),
    ],
)
def test_detect_blue_archive_row_bands_from_fixture_images(
    fixture_name: str,
    expected_starts: tuple[float, float, float],
) -> None:
    fixture_path = Path("collector/tests/fixtures/blue_archive") / fixture_name
    prepared_image_path, cleanup = capture_import._prepare_image_for_ocr(
        fixture_path,
        capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=("-c", "preserve_interword_spaces=1"),
            crop=capture_import.OcrCrop(
                left_ratio=0.39,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=2.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
    )
    try:
        row_bands = capture_import._detect_blue_archive_row_bands(prepared_image_path)
    finally:
        cleanup()

    assert len(row_bands) == 3
    for index, (start_ratio, end_ratio) in enumerate(row_bands):
        assert start_ratio == pytest.approx(expected_starts[index], abs=0.03)
        assert end_ratio > start_ratio
        assert end_ratio - start_ratio > 0.12


def test_select_visible_blue_archive_row_bands_keeps_full_top_row() -> None:
    row_bands = (
        (0.0008, 0.2330),
        (0.2569, 0.5910),
        (0.6165, 0.9506),
    )

    selected = capture_import._select_visible_blue_archive_row_bands(row_bands)

    assert selected == row_bands


def test_select_visible_blue_archive_row_bands_drops_partial_top_row() -> None:
    row_bands = (
        (0.0, 0.12),
        (0.18, 0.50),
        (0.54, 0.88),
    )

    selected = capture_import._select_visible_blue_archive_row_bands(row_bands)

    assert selected == (
        (0.18, 0.50),
        (0.54, 0.88),
    )


def test_apply_blue_archive_original_row_ranks_prefers_existing_entries_when_no_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_recover_blue_archive_original_row_ranks",
        lambda **kwargs: None,
    )

    entries = [
        {"rank": 1, "score": 40100000, "player_name": "Torment"},
        {"rank": 2, "score": 40097600, "player_name": "Torment"},
        {"rank": 3, "score": 40090640, "player_name": "Torment"},
    ]

    applied = capture_import._apply_blue_archive_original_row_ranks(
        entries=entries,
        recovered_ranks=None,
    )

    assert applied == entries


def test_apply_blue_archive_original_row_ranks_uses_recovered_ranks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_recover_blue_archive_original_row_ranks",
        lambda **kwargs: [3522, 3523, 3524],
    )

    entries = [
        {"rank": 1, "score": 40100000, "player_name": "Torment"},
        {"rank": 2, "score": 40097600, "player_name": "Torment"},
        {"rank": 3, "score": 40090640, "player_name": "Torment"},
    ]

    applied = capture_import._apply_blue_archive_original_row_ranks(
        entries=entries,
        recovered_ranks=[3522, 3523, 3524],
    )

    assert [(entry["rank"], entry["score"]) for entry in applied] == [
        (3522, 40100000),
        (3523, 40097600),
        (3524, 40090640),
    ]
    assert applied[0]["_absolute_rank_base"] == 3522
    assert applied[0]["_absolute_rank_base_source"] == "original_row_ranks"


def test_parse_tesseract_layout_entries_does_not_fallback_to_generic_ocr_for_blue_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "blue-archive-page.png"
    from PIL import Image

    Image.new("RGB", (1600, 900), color="white").save(image_path)

    monkeypatch.setattr(
        capture_import,
        "_prepare_image_for_ocr",
        lambda image_path, ocr: (image_path, lambda: None),
    )
    monkeypatch.setattr(
        capture_import,
        "_parse_blue_archive_fixed_rows",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        capture_import,
        "_run_tesseract_command",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("blue archive fixed layout should not use generic OCR fallback")
        ),
    )

    entries = capture_import._parse_tesseract_layout_entries(
        image_path=image_path,
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=capture_import.OcrCrop(
                left_ratio=0.37,
                top_ratio=0.34,
                right_ratio=0.56,
                bottom_ratio=0.94,
            ),
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
        default_ocr_confidence=None,
        page_index=1,
    )

    assert entries == []


def test_iter_tesseract_layout_ocr_attempts_limits_variants_in_blue_archive_fast_path() -> None:
    ocr = capture_import.OcrConfig(
        provider="tesseract",
        command="tesseract",
        language="eng",
        psm=11,
        extra_args=(),
        crop=capture_import.OcrCrop(
            left_ratio=0.37,
            top_ratio=0.34,
            right_ratio=0.56,
            bottom_ratio=0.94,
        ),
        upscale_ratio=2.0,
        reuse_cached_sidecar=False,
        persist_sidecar=False,
        blue_archive_fast_path=True,
    )

    attempts = capture_import._iter_tesseract_layout_ocr_attempts(ocr)

    assert len(attempts) == 1
    assert all(attempt.blue_archive_fast_path is True for attempt in attempts)


def test_parse_tesseract_layout_entries_prefers_richer_later_blue_archive_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "blue-archive-page.png"
    from PIL import Image

    Image.new("RGB", (1600, 900), color="white").save(image_path)

    attempt_one = capture_import.OcrConfig(
        provider="tesseract",
        command="tesseract",
        language="eng",
        psm=11,
        extra_args=(),
        crop=capture_import.OcrCrop(
            left_ratio=0.37,
            top_ratio=0.34,
            right_ratio=0.56,
            bottom_ratio=0.94,
        ),
        upscale_ratio=1.0,
        reuse_cached_sidecar=False,
        persist_sidecar=False,
    )
    attempt_two = capture_import.OcrConfig(
        provider="tesseract",
        command="tesseract",
        language="eng",
        psm=11,
        extra_args=(),
        crop=capture_import.OcrCrop(
            left_ratio=0.34,
            top_ratio=0.34,
            right_ratio=0.58,
            bottom_ratio=0.94,
        ),
        upscale_ratio=1.0,
        reuse_cached_sidecar=False,
        persist_sidecar=False,
    )
    monkeypatch.setattr(
        capture_import,
        "_iter_tesseract_layout_ocr_attempts",
        lambda ocr: [attempt_one, attempt_two],
    )
    monkeypatch.setattr(
        capture_import,
        "_prepare_image_for_ocr",
        lambda image_path, ocr: (image_path, lambda: None),
    )
    fixed_rows = iter(
        [
            [],
            [
                {"rank": 3522, "score": 40100000, "player_name": "Torment"},
                {"rank": 3523, "score": 40097600, "player_name": "Torment"},
                {"rank": 3524, "score": 40090640, "player_name": "Torment"},
            ],
        ]
    )
    monkeypatch.setattr(
        capture_import,
        "_parse_blue_archive_fixed_rows",
        lambda **kwargs: next(fixed_rows),
    )
    monkeypatch.setattr(
        capture_import,
        "_run_tesseract_command",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("blue archive fixed layout should not use generic OCR fallback")
        ),
    )
    recoveries = iter([[3522, 3523, 3524]])
    monkeypatch.setattr(
        capture_import,
        "_recover_blue_archive_original_row_ranks",
        lambda **kwargs: next(recoveries, [3522, 3523, 3524]),
    )

    entries = capture_import._parse_tesseract_layout_entries(
        image_path=image_path,
        ocr=attempt_one,
        default_ocr_confidence=None,
        page_index=1,
    )

    assert [(entry["rank"], entry["score"]) for entry in entries] == [
        (3522, 40100000),
        (3523, 40097600),
        (3524, 40090640),
    ]


def test_parse_blue_archive_page_entries_limits_attempts_to_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "blue-archive-page.png"
    from PIL import Image

    Image.new("RGB", (1600, 900), color="white").save(image_path)

    attempt_one = capture_import.OcrConfig(
        provider="tesseract",
        command="tesseract",
        language="eng",
        psm=11,
        extra_args=(),
        crop=capture_import.OcrCrop(
            left_ratio=0.37,
            top_ratio=0.34,
            right_ratio=0.56,
            bottom_ratio=0.94,
        ),
        upscale_ratio=1.0,
        reuse_cached_sidecar=False,
        persist_sidecar=False,
    )
    attempt_two = capture_import.OcrConfig(
        provider="tesseract",
        command="tesseract",
        language="eng",
        psm=11,
        extra_args=(),
        crop=capture_import.OcrCrop(
            left_ratio=0.34,
            top_ratio=0.34,
            right_ratio=0.58,
            bottom_ratio=0.94,
        ),
        upscale_ratio=1.0,
        reuse_cached_sidecar=False,
        persist_sidecar=False,
    )
    attempt_three = capture_import.OcrConfig(
        provider="tesseract",
        command="tesseract",
        language="eng",
        psm=11,
        extra_args=(),
        crop=capture_import.OcrCrop(
            left_ratio=0.31,
            top_ratio=0.33,
            right_ratio=0.59,
            bottom_ratio=0.94,
        ),
        upscale_ratio=1.0,
        reuse_cached_sidecar=False,
        persist_sidecar=False,
    )
    monkeypatch.setattr(
        capture_import,
        "_iter_tesseract_layout_ocr_attempts",
        lambda ocr: [attempt_one, attempt_two, attempt_three],
    )
    monkeypatch.setattr(
        capture_import,
        "_prepare_image_for_ocr",
        lambda image_path, ocr: (image_path, lambda: None),
    )

    attempt_calls: list[float] = []
    monkeypatch.setattr(
        capture_import,
        "_parse_blue_archive_fixed_rows",
        lambda **kwargs: (attempt_calls.append(kwargs["ocr"].crop.left_ratio) or []),
    )

    entries = capture_import._parse_blue_archive_page_entries(
        image_path=image_path,
        ocr=attempt_one,
        default_ocr_confidence=None,
        page_index=1,
    )

    assert entries == []
    assert attempt_calls == [0.37, 0.34]


def test_has_strong_blue_archive_absolute_row_rank_signal_requires_two_close_hits() -> None:
    assert capture_import._has_strong_blue_archive_absolute_row_rank_signal(
        [3522, 3523, None]
    ) is True
    assert capture_import._has_strong_blue_archive_absolute_row_rank_signal(
        [None, 55566, None]
    ) is False
    assert capture_import._has_strong_blue_archive_absolute_row_rank_signal(
        [3522, 40090640, None]
    ) is False


def test_recover_blue_archive_original_row_ranks_does_not_promote_single_large_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_import,
        "_detect_blue_archive_row_bands",
        lambda prepared_image_path: (
            (0.02, 0.31),
            (0.35, 0.65),
            (0.69, 0.98),
        ),
    )
    original_ranks = iter([None, 55566, None])
    monkeypatch.setattr(
        capture_import,
        "_ocr_blue_archive_row_rank_from_original_image",
        lambda **kwargs: next(original_ranks),
    )

    recovered = capture_import._recover_blue_archive_original_row_ranks(
        prepared_image_path=Path("prepared.png"),
        image_path=Path("page.png"),
        ocr=capture_import.OcrConfig(
            provider="tesseract",
            command="tesseract",
            language="eng",
            psm=11,
            extra_args=(),
            crop=None,
            upscale_ratio=1.0,
            reuse_cached_sidecar=False,
            persist_sidecar=False,
        ),
    )

    assert recovered is None


def test_prune_blue_archive_sparse_rank_violation_pages_drops_sparse_jump_pages() -> None:
    parsed_pages = [
        [
            {"rank": 1, "score": 53404105, "player_name": "Lunatic"},
            {"rank": 2, "score": 53393930, "player_name": "Lunatic"},
            {"rank": 3, "score": 53393544, "player_name": "Lunatic"},
        ],
        [
            {"rank": 10, "score": 53390000, "player_name": "Lunatic"},
        ],
        [
            {"rank": 5, "score": 53388000, "player_name": "Lunatic"},
        ],
    ]
    page_metadata = [
        {
            "page_index": 1,
            "image_path": "page-001.png",
            "ignored_lines": [],
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
            "absolute_rank_base": None,
            "absolute_rank_base_source": None,
            "is_blue_archive_layout": True,
        },
        {
            "page_index": 2,
            "image_path": "page-002.png",
            "ignored_lines": [],
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
            "absolute_rank_base": None,
            "absolute_rank_base_source": None,
            "is_blue_archive_layout": True,
        },
        {
            "page_index": 3,
            "image_path": "page-003.png",
            "ignored_lines": [],
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
            "absolute_rank_base": None,
            "absolute_rank_base_source": None,
            "is_blue_archive_layout": True,
        },
    ]

    adjusted_pages, adjusted_metadata = capture_import._prune_blue_archive_sparse_rank_violation_pages(
        parsed_pages=parsed_pages,
        page_metadata=page_metadata,
    )

    assert adjusted_pages[0] == parsed_pages[0]
    assert adjusted_pages[1] == []
    assert adjusted_pages[2] == []
    assert adjusted_metadata == page_metadata


def test_select_visible_blue_archive_row_bands_drops_partial_bottom_row() -> None:
    row_bands = (
        (0.04, 0.34),
        (0.38, 0.70),
        (0.82, 1.0),
    )

    selected = capture_import._select_visible_blue_archive_row_bands(row_bands)

    assert selected == (
        (0.04, 0.34),
        (0.38, 0.70),
    )


def test_find_score_anchor_value_prefers_eight_digit_blue_archive_score() -> None:
    assert capture_import._find_score_anchor_value(": be 8 53,393,544  (noise)") == 53393544


def test_parse_tesseract_score_anchor_lines_handles_realistic_blue_archive_noise() -> None:
    raw_ocr_output = """AeA Apts

“Al Be

Bey YA Be

a

ee

>.

WE

+

© ole

—

Lv.13 Temp

(0120)

(0190)

[Lee SD

Ce

1H

+e

Q

eee

ti

Led

iA

©

SA BS

—— Ss

(lunatic) 53,404,105

vey SS Gt)

i

&

8) Ga aass)

AlZ SAH

Lv.90 ZY

OfADF 7]

&

(Evi20)

Q

beast

Al Be

> (Lunatic) 53,393,930

5.

fs hows he @, of

isi

TSE

-9

Lv.90 UU

341

(0120)

(0190

exe0

Q

-

<->

ie.

<=

&

(lunatic) 53,393,544

ti

% Bearer, bt Gt)

Led

33

O) So adiltt ts) 5:

©

A Be"""

    entries = capture_import._parse_tesseract_score_anchor_lines(
        ocr_text=raw_ocr_output,
        image_path=Path("page-001.png"),
        default_ocr_confidence=None,
        page_index=1,
    )

    assert [(entry["rank"], entry["player_name"], entry["score"]) for entry in entries] == [
        (1, "Lunatic", 53404105),
        (2, "Lunatic", 53393930),
        (3, "Lunatic", 53393544),
    ]


def test_parse_tesseract_score_anchor_lines_handles_rank_noise_outlier() -> None:
    raw_ocr_output = """1H

il

(Lunatic) 53,404,105

(24

il

(lunatic) 53,393,930

}

341

(Rigg

(tunatic} 53,393,544"""

    entries = capture_import._parse_tesseract_score_anchor_lines(
        ocr_text=raw_ocr_output,
        image_path=Path("page-001.png"),
        default_ocr_confidence=None,
        page_index=1,
    )

    assert [(entry["rank"], entry["player_name"], entry["score"]) for entry in entries] == [
        (1, "Lunatic", 53404105),
        (2, "Lunatic", 53393930),
        (3, "Lunatic", 53393544),
    ]


def test_build_mock_payload_from_capture_keeps_snapshot_note_within_backend_limit(
    tmp_path: Path,
) -> None:
    _write_capture_page(
        tmp_path,
        "page-001.png",
        "1\tLunatic\t53404105\t0.99\n",
    )
    _write_capture_manifest(
        tmp_path,
        season_label="capture-note-length-season",
        pages=[{"image_path": "page-001.png"}],
        snapshot={
            "captured_at": "2026-04-16T10:00:00Z",
            "note": "x" * 220,
        },
    )

    payload = load_capture_import_payload(tmp_path)
    parsed_payload = parse_capture_payload(payload)
    note = parsed_payload.mock_payload.snapshot["note"]

    assert isinstance(note, str)
    assert len(note) <= 255


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
    capture: dict[str, object] | None = None,
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
    if capture is not None:
        manifest["capture"] = capture
    (base_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_capture_page(base_dir: Path, image_name: str, ocr_text: str) -> None:
    image_path = base_dir / image_name
    image_path.write_bytes(b"PNG")
    image_path.with_suffix(".txt").write_text(ocr_text, encoding="utf-8")
