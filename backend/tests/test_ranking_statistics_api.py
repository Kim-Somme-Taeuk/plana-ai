from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.ranking_entry import RankingEntry
from app.models.ranking_snapshot import RankingSnapshot


def test_get_ranking_snapshot_summary_returns_expected_values(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=1,
                score=9000,
                player_name="Top",
                ocr_confidence=0.99,
                raw_text="1 Top 9000",
                image_path="/tmp/top.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=2,
                score=7000,
                player_name="Mid",
                ocr_confidence=0.95,
                raw_text="2 Mid 7000",
                image_path="/tmp/mid.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=3,
                score=1000,
                player_name="Bad OCR",
                ocr_confidence=0.40,
                raw_text="3 Bad OCR 1000",
                image_path="/tmp/bad.png",
                is_valid=False,
                validation_issue="ocr mismatch",
            ),
        ]
    )
    db_session.commit()

    response = client.get(f"/ranking-snapshots/{ranking_snapshot.id}/summary")

    assert response.status_code == 200
    assert response.json() == {
        "snapshot_id": ranking_snapshot.id,
        "season_id": ranking_snapshot.season_id,
        "status": "collecting",
        "captured_at": ranking_snapshot.captured_at.isoformat().replace("+00:00", "Z"),
        "total_rows_collected": 0,
        "valid_entry_count": 2,
        "invalid_entry_count": 1,
        "highest_score": 9000,
        "lowest_score": 7000,
        "validation_issues": [{"code": "ocr mismatch", "count": 1}],
    }


def test_get_ranking_snapshot_summary_returns_null_scores_without_valid_entries(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    db_session.add(
        RankingEntry(
            ranking_snapshot_id=ranking_snapshot.id,
            rank=1,
            score=1000,
            player_name="Invalid",
            ocr_confidence=0.1,
            raw_text="1 Invalid 1000",
            image_path="/tmp/invalid.png",
            is_valid=False,
            validation_issue="ocr mismatch",
        )
    )
    db_session.commit()

    response = client.get(f"/ranking-snapshots/{ranking_snapshot.id}/summary")

    assert response.status_code == 200
    assert response.json()["valid_entry_count"] == 0
    assert response.json()["invalid_entry_count"] == 1
    assert response.json()["highest_score"] is None
    assert response.json()["lowest_score"] is None
    assert response.json()["validation_issues"] == [
        {"code": "ocr mismatch", "count": 1}
    ]


def test_get_ranking_snapshot_summary_groups_validation_issue_counts_from_api_entries(
    client,
    ranking_snapshot: RankingSnapshot,
) -> None:
    client.post(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        json={
            "rank": 1,
            "score": 9000,
            "player_name": "Low OCR",
            "ocr_confidence": 0.1,
            "raw_text": "1 Low OCR 9000",
            "image_path": "/tmp/low-ocr.png",
            "is_valid": True,
            "validation_issue": None,
        },
    )
    client.post(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        json={
            "rank": 2,
            "score": 8000,
            "player_name": "   ",
            "ocr_confidence": 0.9,
            "raw_text": "2 ??? 8000",
            "image_path": "/tmp/missing-name.png",
            "is_valid": True,
            "validation_issue": None,
        },
    )
    client.post(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        json={
            "rank": 3,
            "score": 7000,
            "player_name": "Another Low OCR",
            "ocr_confidence": 0.2,
            "raw_text": "3 Another Low OCR 7000",
            "image_path": "/tmp/low-ocr-2.png",
            "is_valid": True,
            "validation_issue": None,
        },
    )

    response = client.get(f"/ranking-snapshots/{ranking_snapshot.id}/summary")

    assert response.status_code == 200
    assert response.json()["validation_issues"] == [
        {"code": "low_ocr_confidence", "count": 2},
        {"code": "missing_player_name", "count": 1},
    ]


def test_get_ranking_snapshot_validation_report_returns_expected_values(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=100,
                score=7000,
                player_name="Rank 100",
                ocr_confidence=0.95,
                raw_text="100 Rank 100 7000",
                image_path="/tmp/rank-100.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=10,
                score=9000,
                player_name="Rank 10",
                ocr_confidence=0.95,
                raw_text="10 Rank 10 9000",
                image_path="/tmp/rank-10.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=20,
                score=8000,
                player_name="Invalid OCR",
                ocr_confidence=0.2,
                raw_text="20 Invalid OCR 8000",
                image_path="/tmp/invalid-ocr.png",
                is_valid=False,
                validation_issue="low_ocr_confidence",
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/ranking-snapshots/{ranking_snapshot.id}/validation-report"
    )

    assert response.status_code == 200
    assert response.json() == {
        "snapshot_id": ranking_snapshot.id,
        "status": "collecting",
        "total_entry_count": 3,
        "valid_entry_count": 2,
        "invalid_entry_count": 1,
        "excluded_from_statistics_count": 1,
        "invalid_ratio": 1 / 3,
        "duplicate_rank_count": 0,
        "has_rank_order_violation": True,
        "top_validation_issue": {
            "code": "low_ocr_confidence",
            "count": 1,
        },
        "validation_issues": [{"code": "low_ocr_confidence", "count": 1}],
        "collector_diagnostics": None,
    }


def test_get_ranking_snapshot_validation_report_returns_404_for_missing_snapshot(
    client,
) -> None:
    response = client.get("/ranking-snapshots/999999/validation-report")

    assert response.status_code == 404
    assert response.json()["detail"] == "Ranking snapshot not found"


def test_get_ranking_snapshot_validation_report_includes_collector_diagnostics(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    ranking_snapshot.note = (
        "capture import test fixture\n"
        "collector: pages=2/3; capture_stop=noisy_last_page; "
        "ignored=3(blank_line=1,non_entry_line=2); "
        "ocr_stop=noisy_last_page(hard)"
    )
    db_session.add(
        RankingEntry(
            ranking_snapshot_id=ranking_snapshot.id,
            rank=1,
            score=10000,
            player_name="Valid",
            ocr_confidence=0.99,
            raw_text="1 Valid 10000",
            image_path="/tmp/valid.png",
            is_valid=True,
            validation_issue=None,
        )
    )
    db_session.commit()

    response = client.get(
        f"/ranking-snapshots/{ranking_snapshot.id}/validation-report"
    )

    assert response.status_code == 200
    assert response.json()["collector_diagnostics"] == {
        "raw_summary": (
            "pages=2/3; capture_stop=noisy_last_page; "
            "ignored=3(blank_line=1,non_entry_line=2); "
            "ocr_stop=noisy_last_page(hard)"
        ),
        "captured_page_count": 2,
        "requested_page_count": 3,
        "capture_stop_reason": "noisy_last_page",
        "ignored_line_count": 3,
        "ignored_reasons": [
            {"reason": "blank_line", "count": 1},
            {"reason": "non_entry_line", "count": 2},
        ],
        "ocr_stop_reason": "noisy_last_page",
        "ocr_stop_level": "hard",
    }


def test_get_season_validation_overview_returns_expected_values(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    completed_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=datetime.now(UTC) - timedelta(hours=2),
        source_type="mock_json",
        status="completed",
        total_rows_collected=2,
        note="completed snapshot",
    )
    failed_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=datetime.now(UTC) - timedelta(hours=1),
        source_type="mock_json",
        status="failed",
        total_rows_collected=1,
        note="failed snapshot",
    )
    db_session.add_all([completed_snapshot, failed_snapshot])
    db_session.flush()
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=completed_snapshot.id,
                rank=1,
                score=10000,
                player_name="Valid",
                ocr_confidence=0.99,
                raw_text="1 Valid 10000",
                image_path="/tmp/valid.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=completed_snapshot.id,
                rank=2,
                score=9000,
                player_name="Invalid OCR",
                ocr_confidence=0.2,
                raw_text="2 Invalid OCR 9000",
                image_path="/tmp/invalid-ocr.png",
                is_valid=False,
                validation_issue="low_ocr_confidence",
            ),
            RankingEntry(
                ranking_snapshot_id=failed_snapshot.id,
                rank=3,
                score=8000,
                player_name="Missing",
                ocr_confidence=0.9,
                raw_text="3 Missing 8000",
                image_path="/tmp/missing.png",
                is_valid=False,
                validation_issue="missing_player_name",
            ),
        ]
    )
    db_session.commit()

    response = client.get(f"/seasons/{ranking_snapshot.season_id}/validation-overview")

    assert response.status_code == 200
    assert response.json() == {
        "season_id": ranking_snapshot.season_id,
        "snapshot_count": 3,
        "completed_snapshot_count": 1,
        "collecting_snapshot_count": 1,
        "failed_snapshot_count": 1,
        "total_entry_count": 3,
        "valid_entry_count": 1,
        "invalid_entry_count": 2,
        "excluded_from_statistics_count": 2,
        "invalid_ratio": 2 / 3,
        "top_validation_issue": {
            "code": "missing_player_name",
            "count": 1,
        },
        "validation_issues": [
            {"code": "low_ocr_confidence", "count": 1},
            {"code": "missing_player_name", "count": 1},
        ],
        "snapshots_with_collector_diagnostics_count": 0,
        "snapshots_with_capture_stop_count": 0,
        "snapshots_with_hard_ocr_stop_count": 0,
        "total_ignored_line_count": 0,
        "capture_stop_reasons": [],
        "ocr_stop_reasons": [],
        "ignored_reasons": [],
    }


def test_get_season_validation_overview_returns_404_for_missing_season(
    client,
) -> None:
    response = client.get("/seasons/999999/validation-overview")

    assert response.status_code == 404
    assert response.json()["detail"] == "Season not found"


def test_get_season_validation_overview_supports_status_and_source_filters(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    completed_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=datetime.now(UTC) - timedelta(hours=2),
        source_type="adb_capture",
        status="completed",
        total_rows_collected=2,
        note="completed snapshot",
    )
    failed_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=datetime.now(UTC) - timedelta(hours=1),
        source_type="mock_json",
        status="failed",
        total_rows_collected=1,
        note="failed snapshot",
    )
    db_session.add_all([completed_snapshot, failed_snapshot])
    db_session.flush()
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=completed_snapshot.id,
                rank=1,
                score=10000,
                player_name="Valid",
                ocr_confidence=0.99,
                raw_text="1 Valid 10000",
                image_path="/tmp/valid.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=completed_snapshot.id,
                rank=2,
                score=9000,
                player_name="Invalid OCR",
                ocr_confidence=0.2,
                raw_text="2 Invalid OCR 9000",
                image_path="/tmp/invalid-ocr.png",
                is_valid=False,
                validation_issue="low_ocr_confidence",
            ),
            RankingEntry(
                ranking_snapshot_id=failed_snapshot.id,
                rank=3,
                score=8000,
                player_name="Missing",
                ocr_confidence=0.9,
                raw_text="3 Missing 8000",
                image_path="/tmp/missing.png",
                is_valid=False,
                validation_issue="missing_player_name",
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/seasons/{ranking_snapshot.season_id}/validation-overview"
        "?status=completed&source_type=adb_capture"
    )

    assert response.status_code == 200
    assert response.json() == {
        "season_id": ranking_snapshot.season_id,
        "snapshot_count": 1,
        "completed_snapshot_count": 1,
        "collecting_snapshot_count": 0,
        "failed_snapshot_count": 0,
        "total_entry_count": 2,
        "valid_entry_count": 1,
        "invalid_entry_count": 1,
        "excluded_from_statistics_count": 1,
        "invalid_ratio": 0.5,
        "top_validation_issue": {
            "code": "low_ocr_confidence",
            "count": 1,
        },
        "validation_issues": [
            {"code": "low_ocr_confidence", "count": 1},
        ],
        "snapshots_with_collector_diagnostics_count": 0,
        "snapshots_with_capture_stop_count": 0,
        "snapshots_with_hard_ocr_stop_count": 0,
        "total_ignored_line_count": 0,
        "capture_stop_reasons": [],
        "ocr_stop_reasons": [],
        "ignored_reasons": [],
    }


def test_get_season_validation_series_returns_expected_values(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    completed_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=datetime.now(UTC) - timedelta(hours=2),
        source_type="mock_json",
        status="completed",
        total_rows_collected=2,
        note="completed snapshot",
    )
    failed_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=datetime.now(UTC) - timedelta(hours=1),
        source_type="mock_json",
        status="failed",
        total_rows_collected=1,
        note="failed snapshot",
    )
    db_session.add_all([completed_snapshot, failed_snapshot])
    db_session.flush()
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=completed_snapshot.id,
                rank=1,
                score=10000,
                player_name="Valid",
                ocr_confidence=0.99,
                raw_text="1 Valid 10000",
                image_path="/tmp/valid.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=completed_snapshot.id,
                rank=2,
                score=9000,
                player_name="Invalid OCR",
                ocr_confidence=0.2,
                raw_text="2 Invalid OCR 9000",
                image_path="/tmp/invalid-ocr.png",
                is_valid=False,
                validation_issue="low_ocr_confidence",
            ),
            RankingEntry(
                ranking_snapshot_id=failed_snapshot.id,
                rank=3,
                score=8000,
                player_name="Missing",
                ocr_confidence=0.9,
                raw_text="3 Missing 8000",
                image_path="/tmp/missing.png",
                is_valid=False,
                validation_issue="missing_player_name",
            ),
        ]
    )
    db_session.commit()

    response = client.get(f"/seasons/{ranking_snapshot.season_id}/validation-series")

    assert response.status_code == 200
    payload = response.json()
    assert payload["season_id"] == ranking_snapshot.season_id
    assert payload["points"] == [
        {
            "snapshot_id": completed_snapshot.id,
            "captured_at": completed_snapshot.captured_at.isoformat().replace(
                "+00:00", "Z"
            ),
            "status": "completed",
            "total_entry_count": 2,
            "valid_entry_count": 1,
            "invalid_entry_count": 1,
            "invalid_ratio": 0.5,
            "top_validation_issue": {
                "code": "low_ocr_confidence",
                "count": 1,
            },
            "collector_diagnostics": None,
        },
        {
            "snapshot_id": failed_snapshot.id,
            "captured_at": failed_snapshot.captured_at.isoformat().replace(
                "+00:00", "Z"
            ),
            "status": "failed",
            "total_entry_count": 1,
            "valid_entry_count": 0,
            "invalid_entry_count": 1,
            "invalid_ratio": 1.0,
            "top_validation_issue": {
                "code": "missing_player_name",
                "count": 1,
            },
            "collector_diagnostics": None,
        },
        {
            "snapshot_id": ranking_snapshot.id,
            "captured_at": ranking_snapshot.captured_at.isoformat().replace(
                "+00:00", "Z"
            ),
            "status": "collecting",
            "total_entry_count": 0,
            "valid_entry_count": 0,
            "invalid_entry_count": 0,
            "invalid_ratio": 0.0,
            "top_validation_issue": None,
            "collector_diagnostics": None,
        },
    ]


def test_get_season_validation_series_returns_404_for_missing_season(
    client,
) -> None:
    response = client.get("/seasons/999999/validation-series")

    assert response.status_code == 404
    assert response.json()["detail"] == "Season not found"


def test_get_season_validation_series_supports_status_and_source_filters(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    completed_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=datetime.now(UTC) - timedelta(hours=2),
        source_type="adb_capture",
        status="completed",
        total_rows_collected=2,
        note="completed snapshot",
    )
    failed_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=datetime.now(UTC) - timedelta(hours=1),
        source_type="mock_json",
        status="failed",
        total_rows_collected=1,
        note="failed snapshot",
    )
    db_session.add_all([completed_snapshot, failed_snapshot])
    db_session.flush()
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=completed_snapshot.id,
                rank=1,
                score=10000,
                player_name="Valid",
                ocr_confidence=0.99,
                raw_text="1 Valid 10000",
                image_path="/tmp/valid.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=completed_snapshot.id,
                rank=2,
                score=9000,
                player_name="Invalid OCR",
                ocr_confidence=0.2,
                raw_text="2 Invalid OCR 9000",
                image_path="/tmp/invalid-ocr.png",
                is_valid=False,
                validation_issue="low_ocr_confidence",
            ),
            RankingEntry(
                ranking_snapshot_id=failed_snapshot.id,
                rank=3,
                score=8000,
                player_name="Missing",
                ocr_confidence=0.9,
                raw_text="3 Missing 8000",
                image_path="/tmp/missing.png",
                is_valid=False,
                validation_issue="missing_player_name",
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/seasons/{ranking_snapshot.season_id}/validation-series"
        "?status=completed&source_type=adb_capture"
    )

    assert response.status_code == 200
    assert response.json() == {
        "season_id": ranking_snapshot.season_id,
        "points": [
            {
                "snapshot_id": completed_snapshot.id,
                "captured_at": completed_snapshot.captured_at.isoformat().replace(
                    "+00:00", "Z"
                ),
                "status": "completed",
                "total_entry_count": 2,
                "valid_entry_count": 1,
                "invalid_entry_count": 1,
                "invalid_ratio": 0.5,
                "top_validation_issue": {
                    "code": "low_ocr_confidence",
                    "count": 1,
                },
                "collector_diagnostics": None,
            },
        ],
    }


def test_get_season_validation_endpoints_include_collector_diagnostics_aggregates(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    ranking_snapshot.note = (
        "baseline note\n"
        "collector: pages=2/3; capture_stop=noisy_last_page; "
        "ignored=4(blank_line=1,non_entry_line=3); "
        "ocr_stop=noisy_last_page(hard)"
    )
    second_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=datetime.now(UTC) + timedelta(minutes=10),
        source_type="image_tesseract",
        status="completed",
        total_rows_collected=1,
        note=(
            "collector: pages=1/1; ignored=1(separator_line=1); "
            "ocr_stop=sparse_last_page(soft)"
        ),
    )
    db_session.add(second_snapshot)
    db_session.flush()
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=1,
                score=10000,
                player_name="Valid",
                ocr_confidence=0.99,
                raw_text="1 Valid 10000",
                image_path="/tmp/valid.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=second_snapshot.id,
                rank=2,
                score=9000,
                player_name="Invalid OCR",
                ocr_confidence=0.2,
                raw_text="2 Invalid OCR 9000",
                image_path="/tmp/invalid.png",
                is_valid=False,
                validation_issue="low_ocr_confidence",
            ),
        ]
    )
    db_session.commit()

    overview_response = client.get(
        f"/seasons/{ranking_snapshot.season_id}/validation-overview"
    )
    series_response = client.get(
        f"/seasons/{ranking_snapshot.season_id}/validation-series"
    )

    assert overview_response.status_code == 200
    assert overview_response.json()["snapshots_with_collector_diagnostics_count"] == 2
    assert overview_response.json()["snapshots_with_capture_stop_count"] == 1
    assert overview_response.json()["snapshots_with_hard_ocr_stop_count"] == 1
    assert overview_response.json()["total_ignored_line_count"] == 5
    assert overview_response.json()["capture_stop_reasons"] == [
        {"reason": "noisy_last_page", "count": 1}
    ]
    assert overview_response.json()["ocr_stop_reasons"] == [
        {"reason": "noisy_last_page", "count": 1},
        {"reason": "sparse_last_page", "count": 1},
    ]
    assert overview_response.json()["ignored_reasons"] == [
        {"reason": "blank_line", "count": 1},
        {"reason": "non_entry_line", "count": 3},
        {"reason": "separator_line", "count": 1},
    ]

    assert series_response.status_code == 200
    assert series_response.json()["points"] == [
        {
            "snapshot_id": ranking_snapshot.id,
            "captured_at": ranking_snapshot.captured_at.isoformat().replace(
                "+00:00", "Z"
            ),
            "status": "collecting",
            "total_entry_count": 1,
            "valid_entry_count": 1,
            "invalid_entry_count": 0,
            "invalid_ratio": 0.0,
            "top_validation_issue": None,
            "collector_diagnostics": {
                "raw_summary": (
                    "pages=2/3; capture_stop=noisy_last_page; "
                    "ignored=4(blank_line=1,non_entry_line=3); "
                    "ocr_stop=noisy_last_page(hard)"
                ),
                "captured_page_count": 2,
                "requested_page_count": 3,
                "capture_stop_reason": "noisy_last_page",
                "ignored_line_count": 4,
                "ignored_reasons": [
                    {"reason": "blank_line", "count": 1},
                    {"reason": "non_entry_line", "count": 3},
                ],
                "ocr_stop_reason": "noisy_last_page",
                "ocr_stop_level": "hard",
            },
        },
        {
            "snapshot_id": second_snapshot.id,
            "captured_at": second_snapshot.captured_at.isoformat().replace(
                "+00:00", "Z"
            ),
            "status": "completed",
            "total_entry_count": 1,
            "valid_entry_count": 0,
            "invalid_entry_count": 1,
            "invalid_ratio": 1.0,
            "top_validation_issue": {
                "code": "low_ocr_confidence",
                "count": 1,
            },
            "collector_diagnostics": {
                "raw_summary": (
                    "pages=1/1; ignored=1(separator_line=1); "
                    "ocr_stop=sparse_last_page(soft)"
                ),
                "captured_page_count": 1,
                "requested_page_count": 1,
                "capture_stop_reason": None,
                "ignored_line_count": 1,
                "ignored_reasons": [
                    {"reason": "separator_line", "count": 1},
                ],
                "ocr_stop_reason": "sparse_last_page",
                "ocr_stop_level": "soft",
            },
        },
    ]

    hard_overview_response = client.get(
        f"/seasons/{ranking_snapshot.season_id}/validation-overview"
        "?collector_filter=hard_ocr_stop"
    )
    capture_series_response = client.get(
        f"/seasons/{ranking_snapshot.season_id}/validation-series"
        "?collector_filter=capture_stop"
    )

    assert hard_overview_response.status_code == 200
    assert hard_overview_response.json()["snapshot_count"] == 1
    assert hard_overview_response.json()["snapshots_with_hard_ocr_stop_count"] == 1
    assert hard_overview_response.json()["snapshots_with_capture_stop_count"] == 1
    assert hard_overview_response.json()["total_ignored_line_count"] == 4
    assert hard_overview_response.json()["capture_stop_reasons"] == [
        {"reason": "noisy_last_page", "count": 1}
    ]
    assert hard_overview_response.json()["ocr_stop_reasons"] == [
        {"reason": "noisy_last_page", "count": 1}
    ]
    assert hard_overview_response.json()["ignored_reasons"] == [
        {"reason": "blank_line", "count": 1},
        {"reason": "non_entry_line", "count": 3},
    ]

    assert capture_series_response.status_code == 200
    assert [point["snapshot_id"] for point in capture_series_response.json()["points"]] == [
        ranking_snapshot.id
    ]


def test_get_season_validation_endpoints_support_collector_reason_filters(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    ranking_snapshot.note = (
        "baseline note\n"
        "collector: pages=2/3; capture_stop=noisy_last_page; "
        "ignored=4(blank_line=1,non_entry_line=3); "
        "ocr_stop=noisy_last_page(hard)"
    )
    second_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=datetime.now(UTC) + timedelta(minutes=10),
        source_type="image_tesseract",
        status="completed",
        total_rows_collected=1,
        note=(
            "collector: pages=1/1; ignored=1(separator_line=1); "
            "ocr_stop=sparse_last_page(soft)"
        ),
    )
    db_session.add(second_snapshot)
    db_session.flush()
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=1,
                score=10000,
                player_name="Valid",
                ocr_confidence=0.99,
                raw_text="1 Valid 10000",
                image_path="/tmp/valid.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=second_snapshot.id,
                rank=2,
                score=9000,
                player_name="Invalid OCR",
                ocr_confidence=0.2,
                raw_text="2 Invalid OCR 9000",
                image_path="/tmp/invalid.png",
                is_valid=False,
                validation_issue="low_ocr_confidence",
            ),
        ]
    )
    db_session.commit()

    capture_reason_response = client.get(
        f"/seasons/{ranking_snapshot.season_id}/validation-overview"
        "?capture_stop_reason=noisy_last_page"
    )
    ocr_reason_response = client.get(
        f"/seasons/{ranking_snapshot.season_id}/validation-series"
        "?ocr_stop_reason=sparse_last_page"
    )

    assert capture_reason_response.status_code == 200
    assert capture_reason_response.json()["snapshot_count"] == 1
    assert capture_reason_response.json()["capture_stop_reasons"] == [
        {"reason": "noisy_last_page", "count": 1}
    ]
    assert capture_reason_response.json()["ocr_stop_reasons"] == [
        {"reason": "noisy_last_page", "count": 1}
    ]

    assert ocr_reason_response.status_code == 200
    assert [point["snapshot_id"] for point in ocr_reason_response.json()["points"]] == [
        second_snapshot.id
    ]
    assert (
        ocr_reason_response.json()["points"][0]["collector_diagnostics"][
            "ocr_stop_reason"
        ]
        == "sparse_last_page"
    )


def test_get_ranking_snapshot_cutoffs_returns_scores_and_nulls(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=1,
                score=9000,
                player_name="Top",
                ocr_confidence=0.99,
                raw_text="1 Top 9000",
                image_path="/tmp/top.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=10,
                score=8000,
                player_name="Ten",
                ocr_confidence=0.95,
                raw_text="10 Ten 8000",
                image_path="/tmp/ten.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=100,
                score=7000,
                player_name="Hundred",
                ocr_confidence=0.9,
                raw_text="100 Hundred 7000",
                image_path="/tmp/hundred.png",
                is_valid=False,
                validation_issue="ocr mismatch",
            ),
        ]
    )
    db_session.commit()

    response = client.get(f"/ranking-snapshots/{ranking_snapshot.id}/cutoffs")

    assert response.status_code == 200
    assert response.json()["snapshot_id"] == ranking_snapshot.id
    assert response.json()["status"] == "collecting"
    assert response.json()["cutoffs"] == [
        {"rank": 1, "score": 9000},
        {"rank": 10, "score": 8000},
        {"rank": 100, "score": None},
        {"rank": 1000, "score": None},
        {"rank": 5000, "score": None},
        {"rank": 10000, "score": None},
    ]


def test_get_ranking_snapshot_distribution_uses_valid_entries_only(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=1,
                score=1000,
                player_name="A",
                ocr_confidence=0.99,
                raw_text="1 A 1000",
                image_path="/tmp/a.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=2,
                score=3000,
                player_name="B",
                ocr_confidence=0.95,
                raw_text="2 B 3000",
                image_path="/tmp/b.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=3,
                score=5000,
                player_name="C",
                ocr_confidence=0.9,
                raw_text="3 C 5000",
                image_path="/tmp/c.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=4,
                score=9999,
                player_name="Ignored",
                ocr_confidence=0.2,
                raw_text="4 Ignored 9999",
                image_path="/tmp/ignored.png",
                is_valid=False,
                validation_issue="ocr mismatch",
            ),
        ]
    )
    db_session.commit()

    response = client.get(f"/ranking-snapshots/{ranking_snapshot.id}/distribution")

    assert response.status_code == 200
    assert response.json() == {
        "snapshot_id": ranking_snapshot.id,
        "status": "collecting",
        "count": 3,
        "min_score": 1000,
        "max_score": 5000,
        "avg_score": 3000.0,
        "median_score": 3000.0,
    }


def test_get_ranking_snapshot_distribution_returns_nulls_without_valid_entries(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    db_session.add(
        RankingEntry(
            ranking_snapshot_id=ranking_snapshot.id,
            rank=1,
            score=1000,
            player_name="Invalid",
            ocr_confidence=0.2,
            raw_text="1 Invalid 1000",
            image_path="/tmp/invalid.png",
            is_valid=False,
            validation_issue="ocr mismatch",
        )
    )
    db_session.commit()

    response = client.get(f"/ranking-snapshots/{ranking_snapshot.id}/distribution")

    assert response.status_code == 200
    assert response.json() == {
        "snapshot_id": ranking_snapshot.id,
        "status": "collecting",
        "count": 0,
        "min_score": None,
        "max_score": None,
        "avg_score": None,
        "median_score": None,
    }


def test_statistics_exclude_invalid_entries_created_via_api(
    client,
    ranking_snapshot: RankingSnapshot,
) -> None:
    valid_response = client.post(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        json={
            "rank": 1,
            "score": 9000,
            "player_name": "Valid",
            "ocr_confidence": 0.95,
            "raw_text": "1 Valid 9000",
            "image_path": "/tmp/valid.png",
            "is_valid": True,
            "validation_issue": None,
        },
    )
    invalid_response = client.post(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        json={
            "rank": 2,
            "score": 8000,
            "player_name": "Low OCR",
            "ocr_confidence": 0.4,
            "raw_text": "2 Low OCR 8000",
            "image_path": "/tmp/low-ocr.png",
            "is_valid": True,
            "validation_issue": None,
        },
    )

    assert valid_response.status_code == 201
    assert invalid_response.status_code == 201
    assert invalid_response.json()["validation_issue"] == "low_ocr_confidence"

    summary_response = client.get(f"/ranking-snapshots/{ranking_snapshot.id}/summary")
    distribution_response = client.get(
        f"/ranking-snapshots/{ranking_snapshot.id}/distribution"
    )
    cutoffs_response = client.get(f"/ranking-snapshots/{ranking_snapshot.id}/cutoffs")

    assert summary_response.status_code == 200
    assert summary_response.json()["valid_entry_count"] == 1
    assert summary_response.json()["invalid_entry_count"] == 1
    assert summary_response.json()["highest_score"] == 9000
    assert summary_response.json()["lowest_score"] == 9000

    assert distribution_response.status_code == 200
    assert distribution_response.json()["count"] == 1
    assert distribution_response.json()["min_score"] == 9000
    assert distribution_response.json()["max_score"] == 9000

    assert cutoffs_response.status_code == 200
    assert cutoffs_response.json()["cutoffs"][0] == {"rank": 1, "score": 9000}


def test_get_season_cutoff_series_uses_completed_snapshots_only(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    ranking_snapshot.status = "completed"
    ranking_snapshot.captured_at = datetime.now(UTC)
    db_session.add(ranking_snapshot)

    second_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=ranking_snapshot.captured_at + timedelta(minutes=5),
        source_type="manual",
        status="completed",
        total_rows_collected=2,
        note="second completed snapshot",
    )
    third_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=ranking_snapshot.captured_at + timedelta(minutes=10),
        source_type="manual",
        status="collecting",
        total_rows_collected=1,
        note="collecting snapshot should be excluded",
    )
    db_session.add_all([second_snapshot, third_snapshot])
    db_session.commit()
    db_session.refresh(second_snapshot)
    db_session.refresh(third_snapshot)

    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=1000,
                score=9000,
                player_name="First",
                ocr_confidence=0.9,
                raw_text="1000 First 9000",
                image_path="/tmp/first.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=second_snapshot.id,
                rank=1000,
                score=8500,
                player_name="Second",
                ocr_confidence=0.8,
                raw_text="1000 Second 8500",
                image_path="/tmp/second.png",
                is_valid=False,
                validation_issue="ocr mismatch",
            ),
            RankingEntry(
                ranking_snapshot_id=third_snapshot.id,
                rank=1000,
                score=8000,
                player_name="Ignored",
                ocr_confidence=0.7,
                raw_text="1000 Ignored 8000",
                image_path="/tmp/ignored.png",
                is_valid=True,
                validation_issue=None,
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/seasons/{ranking_snapshot.season_id}/cutoff-series",
        params={"rank": 1000},
    )

    assert response.status_code == 200
    assert response.json()["season_id"] == ranking_snapshot.season_id
    assert response.json()["rank"] == 1000
    assert response.json()["points"] == [
        {
            "snapshot_id": ranking_snapshot.id,
            "captured_at": ranking_snapshot.captured_at.isoformat().replace("+00:00", "Z"),
            "score": 9000,
        },
        {
            "snapshot_id": second_snapshot.id,
            "captured_at": second_snapshot.captured_at.isoformat().replace("+00:00", "Z"),
            "score": None,
        },
    ]


def test_snapshot_statistics_return_404_for_missing_snapshot(client) -> None:
    for suffix in ("summary", "cutoffs", "distribution"):
        response = client.get(f"/ranking-snapshots/999999/{suffix}")

        assert response.status_code == 404
        assert response.json() == {"detail": "Ranking snapshot not found"}


def test_get_season_cutoff_series_returns_404_for_missing_season(client) -> None:
    response = client.get("/seasons/999999/cutoff-series", params={"rank": 1000})

    assert response.status_code == 404
    assert response.json() == {"detail": "Season not found"}


def test_get_season_cutoff_series_supports_source_type_filter(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    adb_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=datetime.now(UTC) - timedelta(hours=2),
        source_type="adb_capture",
        status="completed",
        total_rows_collected=1,
        note="adb snapshot",
    )
    mock_snapshot = RankingSnapshot(
        season_id=ranking_snapshot.season_id,
        captured_at=datetime.now(UTC) - timedelta(hours=1),
        source_type="mock_json",
        status="completed",
        total_rows_collected=1,
        note="mock snapshot",
    )
    db_session.add_all([adb_snapshot, mock_snapshot])
    db_session.flush()
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=adb_snapshot.id,
                rank=100,
                score=10000,
                player_name="ADB",
                ocr_confidence=0.99,
                raw_text="100 ADB 10000",
                image_path="/tmp/adb.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=mock_snapshot.id,
                rank=100,
                score=9000,
                player_name="Mock",
                ocr_confidence=0.99,
                raw_text="100 Mock 9000",
                image_path="/tmp/mock.png",
                is_valid=True,
                validation_issue=None,
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/seasons/{ranking_snapshot.season_id}/cutoff-series",
        params={"rank": 100, "source_type": "adb_capture"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "season_id": ranking_snapshot.season_id,
        "rank": 100,
        "points": [
            {
                "snapshot_id": adb_snapshot.id,
                "captured_at": adb_snapshot.captured_at.isoformat().replace(
                    "+00:00", "Z"
                ),
                "score": 10000,
            }
        ],
    }


def test_get_season_cutoff_series_requires_rank_query_param(
    client,
    ranking_snapshot: RankingSnapshot,
) -> None:
    response = client.get(f"/seasons/{ranking_snapshot.season_id}/cutoff-series")

    assert response.status_code == 422
    assert response.json()["detail"]
