from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from pydantic import TypeAdapter, ValidationError


LOW_OCR_CONFIDENCE_THRESHOLD = 0.5
INT_VALUE_ADAPTER = TypeAdapter(int)


class ValidationIssueCode(str, Enum):
    INVALID_RANK = "invalid_rank"
    INVALID_SCORE = "invalid_score"
    MISSING_PLAYER_NAME = "missing_player_name"
    LOW_OCR_CONFIDENCE = "low_ocr_confidence"
    DUPLICATE_RANK = "duplicate_rank"
    RANK_ORDER_VIOLATION = "rank_order_violation"


@dataclass(frozen=True)
class RankingEntryValidationResult:
    is_valid: bool
    validation_issue: str | None


@dataclass(frozen=True)
class SnapshotValidationSummary:
    duplicate_ranks: tuple[int, ...]
    has_rank_order_violation: bool


def validate_ranking_entry(
    *,
    rank: int,
    score: int,
    player_name: str | None,
    ocr_confidence: float | None,
) -> RankingEntryValidationResult:
    issue = _get_entry_validation_issue(
        rank=rank,
        score=score,
        player_name=player_name,
        ocr_confidence=ocr_confidence,
    )

    return RankingEntryValidationResult(
        is_valid=issue is None,
        validation_issue=issue,
    )


def summarize_snapshot_entries(
    entries: Iterable[Mapping[str, object]],
) -> SnapshotValidationSummary:
    seen_ranks: set[int] = set()
    duplicate_ranks: set[int] = set()
    previous_rank: int | None = None
    has_rank_order_violation = False

    for entry in entries:
        rank = _normalize_rank_for_snapshot_validation(entry.get("rank"))
        if rank is None:
            continue

        if rank in seen_ranks:
            duplicate_ranks.add(rank)
        else:
            seen_ranks.add(rank)

        if previous_rank is not None and rank < previous_rank:
            has_rank_order_violation = True

        previous_rank = rank

    return SnapshotValidationSummary(
        duplicate_ranks=tuple(sorted(duplicate_ranks)),
        has_rank_order_violation=has_rank_order_violation,
    )


def _get_entry_validation_issue(
    *,
    rank: int,
    score: int,
    player_name: str | None,
    ocr_confidence: float | None,
) -> str | None:
    if rank <= 0:
        return ValidationIssueCode.INVALID_RANK.value

    if score <= 0:
        return ValidationIssueCode.INVALID_SCORE.value

    if player_name is None or not player_name.strip():
        return ValidationIssueCode.MISSING_PLAYER_NAME.value

    if (
        ocr_confidence is not None
        and ocr_confidence < LOW_OCR_CONFIDENCE_THRESHOLD
    ):
        return ValidationIssueCode.LOW_OCR_CONFIDENCE.value

    return None


def _normalize_rank_for_snapshot_validation(value: object) -> int | None:
    try:
        return INT_VALUE_ADAPTER.validate_python(value)
    except ValidationError:
        return None
