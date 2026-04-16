from app.core.ranking_entry_validation import (
    ValidationIssueCode,
    summarize_snapshot_entries,
    validate_ranking_entry,
)


def test_validate_ranking_entry_returns_valid_for_normal_input() -> None:
    result = validate_ranking_entry(
        rank=1,
        score=1000,
        player_name="Plana",
        ocr_confidence=0.95,
    )

    assert result.is_valid is True
    assert result.validation_issue is None


def test_validate_ranking_entry_uses_rule_priority() -> None:
    result = validate_ranking_entry(
        rank=0,
        score=0,
        player_name="   ",
        ocr_confidence=0.1,
    )

    assert result.is_valid is False
    assert result.validation_issue == ValidationIssueCode.INVALID_RANK.value


def test_summarize_snapshot_entries_reports_duplicate_rank() -> None:
    summary = summarize_snapshot_entries(
        [
            {"rank": 1, "score": 1000},
            {"rank": 1, "score": 900},
            {"rank": 2, "score": 800},
        ]
    )

    assert summary.duplicate_ranks == (1,)
    assert summary.has_rank_order_violation is False


def test_summarize_snapshot_entries_reports_rank_order_violation() -> None:
    summary = summarize_snapshot_entries(
        [
            {"rank": 1, "score": 1000},
            {"rank": 3, "score": 900},
            {"rank": 2, "score": 800},
        ]
    )

    assert summary.duplicate_ranks == ()
    assert summary.has_rank_order_violation is True


def test_summarize_snapshot_entries_normalizes_integer_like_ranks() -> None:
    summary = summarize_snapshot_entries(
        [
            {"rank": "1", "score": 1000},
            {"rank": 1.0, "score": 900},
            {"rank": "2", "score": 800},
        ]
    )

    assert summary.duplicate_ranks == (1,)
    assert summary.has_rank_order_violation is False
