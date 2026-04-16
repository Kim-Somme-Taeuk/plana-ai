from statistics import median
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.collector_diagnostics import parse_collector_diagnostics_summary
from app.core.ranking_entry_validation import summarize_snapshot_entries
from app.models.ranking_entry import RankingEntry
from app.models.ranking_snapshot import RankingSnapshot
from app.models.season import Season
from app.schemas.ranking_statistics import (
    CollectorDiagnosticsRead,
    CollectorIgnoredReasonCountRead,
    CollectorPageSummaryRead,
    CollectorPipelineStopRecommendationRead,
    CollectorReasonCountRead,
    CollectorStopPolicyRead,
    CollectorStopHintRead,
    CollectorStopRecommendationRead,
    RankingSnapshotCutoffRead,
    RankingSnapshotCutoffsRead,
    RankingSnapshotDistributionRead,
    RankingSnapshotSummaryRead,
    RankingSnapshotValidationReportRead,
    RankingSnapshotValidationIssueCountRead,
    SeasonValidationSeriesPointRead,
    SeasonValidationSeriesRead,
    SeasonValidationOverviewRead,
    ValidationTopIssueRead,
    SeasonCutoffSeriesPointRead,
    SeasonCutoffSeriesRead,
)
from app.schemas.ranking_snapshot import (
    RankingSnapshotCreate,
    RankingSnapshotRead,
    RankingSnapshotStatusUpdate,
)

router = APIRouter(tags=["ranking_snapshots"])

COLLECTING_STATUS = "collecting"
COMPLETED_STATUS = "completed"
FAILED_STATUS = "failed"
ALLOWED_STATUS_TRANSITIONS = {
    (COLLECTING_STATUS, COMPLETED_STATUS),
    (COLLECTING_STATUS, FAILED_STATUS),
}
DEFAULT_CUTOFF_RANKS = (1, 10, 100, 1000, 5000, 10000)
OVERLAY_IGNORED_REASONS = ("reward_line", "ui_control_line", "status_line")
HEADER_IGNORED_REASONS = ("header_line", "pagination_line")
SPARSE_PAGE_ENTRY_THRESHOLD = 3
OVERLAPPING_PAGE_RATIO_THRESHOLD = 0.5
STALE_PAGE_MIN_ENTRY_COUNT = 4
STALE_PAGE_NEW_RANK_RATIO_THRESHOLD = 0.25


def _get_ranking_snapshot_or_404(db: Session, snapshot_id: int) -> RankingSnapshot:
    snapshot = db.get(RankingSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Ranking snapshot not found")
    return snapshot


def _get_season_or_404(db: Session, season_id: int) -> Season:
    season = db.get(Season, season_id)
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found")
    return season


def _ensure_valid_status_transition(current_status: str, next_status: str) -> None:
    if current_status == next_status:
        return

    if (current_status, next_status) not in ALLOWED_STATUS_TRANSITIONS:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid status transition from {current_status} to {next_status}",
        )


def _count_ranking_entries(db: Session, snapshot_id: int) -> int:
    count = db.scalar(
        select(func.count(RankingEntry.id)).where(
            RankingEntry.ranking_snapshot_id == snapshot_id
        )
    )
    return count or 0


def _count_snapshot_entries_by_validity(
    db: Session,
    snapshot_id: int,
    is_valid: bool,
) -> int:
    count = db.scalar(
        select(func.count(RankingEntry.id)).where(
            RankingEntry.ranking_snapshot_id == snapshot_id,
            RankingEntry.is_valid.is_(is_valid),
        )
    )
    return count or 0


def _get_valid_score_bounds(
    db: Session,
    snapshot_id: int,
) -> tuple[int | None, int | None]:
    row = db.execute(
        select(
            func.max(RankingEntry.score),
            func.min(RankingEntry.score),
        ).where(
            RankingEntry.ranking_snapshot_id == snapshot_id,
            RankingEntry.is_valid.is_(True),
        )
    ).one()
    return row[0], row[1]


def _get_validation_issue_counts(
    db: Session,
    snapshot_id: int,
) -> list[RankingSnapshotValidationIssueCountRead]:
    rows = db.execute(
        select(
            RankingEntry.validation_issue,
            func.count(RankingEntry.id),
        )
        .where(
            RankingEntry.ranking_snapshot_id == snapshot_id,
            RankingEntry.is_valid.is_(False),
            RankingEntry.validation_issue.is_not(None),
        )
        .group_by(RankingEntry.validation_issue)
        .order_by(RankingEntry.validation_issue.asc())
    ).all()

    return [
        RankingSnapshotValidationIssueCountRead(code=code, count=count)
        for code, count in rows
    ]


def _get_top_validation_issue(
    issues: list[RankingSnapshotValidationIssueCountRead],
) -> ValidationTopIssueRead | None:
    if not issues:
        return None

    top_issue = max(issues, key=lambda issue: (issue.count, issue.code))
    return ValidationTopIssueRead(code=top_issue.code, count=top_issue.count)


def _calculate_invalid_ratio(valid_entry_count: int, invalid_entry_count: int) -> float:
    total_entry_count = valid_entry_count + invalid_entry_count
    if total_entry_count == 0:
        return 0.0

    return invalid_entry_count / total_entry_count


def _build_page_quality_counts(
    page_summaries: list[CollectorPageSummaryRead],
) -> dict[str, int]:
    counts = {
        "empty_page_count": 0,
        "sparse_page_count": 0,
        "overlapping_page_count": 0,
        "stale_page_count": 0,
        "noisy_page_count": 0,
    }

    for summary in page_summaries:
        if summary.entry_count == 0:
            counts["empty_page_count"] += 1
        if summary.entry_count <= SPARSE_PAGE_ENTRY_THRESHOLD:
            counts["sparse_page_count"] += 1
        if (
            summary.entry_count > 0
            and summary.overlap_with_previous_ratio >= OVERLAPPING_PAGE_RATIO_THRESHOLD
        ):
            counts["overlapping_page_count"] += 1
        if (
            summary.entry_count >= STALE_PAGE_MIN_ENTRY_COUNT
            and 0 < summary.new_rank_ratio <= STALE_PAGE_NEW_RANK_RATIO_THRESHOLD
        ):
            counts["stale_page_count"] += 1
        if summary.ignored_line_count > 0 and summary.ignored_line_count >= max(
            1, summary.entry_count
        ):
            counts["noisy_page_count"] += 1

    return counts


def _build_collector_diagnostics_read(
    snapshot: RankingSnapshot,
) -> CollectorDiagnosticsRead | None:
    summary = parse_collector_diagnostics_summary(snapshot.note)
    if summary is None:
        return None

    page_summaries = [
        CollectorPageSummaryRead(**page_summary)
        for page_summary in summary.page_summaries
    ]
    page_quality_counts = _build_page_quality_counts(page_summaries)

    return CollectorDiagnosticsRead(
        raw_summary=summary.raw_summary,
        captured_page_count=summary.captured_page_count,
        requested_page_count=summary.requested_page_count,
        capture_stop_reason=summary.capture_stop_reason,
        ignored_line_count=summary.ignored_line_count,
        empty_page_count=page_quality_counts["empty_page_count"],
        sparse_page_count=page_quality_counts["sparse_page_count"],
        overlapping_page_count=page_quality_counts["overlapping_page_count"],
        stale_page_count=page_quality_counts["stale_page_count"],
        noisy_page_count=page_quality_counts["noisy_page_count"],
        overlay_ignored_line_count=_sum_ignored_reasons(
            summary.ignored_reasons,
            OVERLAY_IGNORED_REASONS,
        ),
        header_ignored_line_count=_sum_ignored_reasons(
            summary.ignored_reasons,
            HEADER_IGNORED_REASONS,
        ),
        malformed_entry_line_count=_sum_ignored_reasons(
            summary.ignored_reasons,
            ("malformed_entry_line",),
        ),
        ignored_reasons=[
            CollectorIgnoredReasonCountRead(reason=row.reason, count=row.count)
            for row in summary.ignored_reasons
        ],
        ocr_stop_reason=summary.ocr_stop_reason,
        ocr_stop_level=summary.ocr_stop_level,
        page_summaries=page_summaries,
        ocr_stop_hints=[
            CollectorStopHintRead(**hint)
            for hint in summary.ocr_stop_hints
        ],
        ocr_stop_recommendation=(
            CollectorStopRecommendationRead(**summary.ocr_stop_recommendation)
            if summary.ocr_stop_recommendation is not None
            else None
        ),
        pipeline_stop_recommendation=(
            CollectorPipelineStopRecommendationRead(**summary.pipeline_stop_recommendation)
            if summary.pipeline_stop_recommendation is not None
            else None
        ),
        stop_policy=(
            CollectorStopPolicyRead(**summary.stop_policy)
            if summary.stop_policy is not None
            else None
        ),
    )


def _matches_collector_filter(
    diagnostics: CollectorDiagnosticsRead | None,
    collector_filter: str | None,
    capture_stop_reason: str | None,
    ocr_stop_reason: str | None,
    ignored_reason: str | None,
    ignored_group: str | None,
    page_signal: str | None,
    ocr_stop_level: str | None,
) -> bool:
    if collector_filter is None:
        filter_matches = True
    elif collector_filter == "with_diagnostics":
        filter_matches = diagnostics is not None
    elif diagnostics is None:
        filter_matches = False
    elif collector_filter == "capture_stop":
        filter_matches = diagnostics.capture_stop_reason is not None
    elif collector_filter == "hard_ocr_stop":
        filter_matches = diagnostics.ocr_stop_level == "hard"
    else:
        filter_matches = True

    if not filter_matches:
        return False

    if (
        capture_stop_reason is None
        and ocr_stop_reason is None
        and ignored_reason is None
        and ignored_group is None
        and page_signal is None
        and ocr_stop_level is None
    ):
        return True

    if diagnostics is None:
        return False

    if (
        capture_stop_reason is not None
        and diagnostics.capture_stop_reason != capture_stop_reason
    ):
        return False
    if ocr_stop_reason is not None and diagnostics.ocr_stop_reason != ocr_stop_reason:
        return False
    if ocr_stop_level is not None and diagnostics.ocr_stop_level != ocr_stop_level:
        return False
    if ignored_reason is not None and not any(
        row.reason == ignored_reason for row in diagnostics.ignored_reasons
    ):
        return False
    if ignored_group == "overlay" and diagnostics.overlay_ignored_line_count == 0:
        return False
    if ignored_group == "header" and diagnostics.header_ignored_line_count == 0:
        return False
    if ignored_group == "malformed" and diagnostics.malformed_entry_line_count == 0:
        return False
    if page_signal == "empty" and diagnostics.empty_page_count == 0:
        return False
    if page_signal == "sparse" and diagnostics.sparse_page_count == 0:
        return False
    if page_signal == "overlapping" and diagnostics.overlapping_page_count == 0:
        return False
    if page_signal == "stale" and diagnostics.stale_page_count == 0:
        return False
    if page_signal == "noisy" and diagnostics.noisy_page_count == 0:
        return False
    return True


def _sum_ignored_reasons(
    ignored_reasons,
    target_reasons: tuple[str, ...],
) -> int:
    return sum(
        row.count
        for row in ignored_reasons
        if row.reason in target_reasons
    )


def _get_filtered_season_snapshots(
    db: Session,
    *,
    season_id: int,
    status: str | None,
    source_type: str | None,
    collector_filter: str | None,
    capture_stop_reason: str | None,
    ocr_stop_reason: str | None,
    ignored_reason: str | None,
    ignored_group: str | None,
    page_signal: str | None,
    ocr_stop_level: str | None,
) -> list[tuple[RankingSnapshot, CollectorDiagnosticsRead | None]]:
    snapshots = list(
        db.scalars(
            select(RankingSnapshot)
            .where(
                *_build_season_snapshot_filters(
                    season_id=season_id,
                    status=status,
                    source_type=source_type,
                )
            )
            .order_by(RankingSnapshot.captured_at.asc(), RankingSnapshot.id.asc())
        ).all()
    )

    rows: list[tuple[RankingSnapshot, CollectorDiagnosticsRead | None]] = []
    for snapshot in snapshots:
        diagnostics = _build_collector_diagnostics_read(snapshot)
        if _matches_collector_filter(
            diagnostics,
            collector_filter,
            capture_stop_reason,
            ocr_stop_reason,
            ignored_reason,
            ignored_group,
            page_signal,
            ocr_stop_level,
        ):
            rows.append((snapshot, diagnostics))
    return rows


def _get_valid_scores(db: Session, snapshot_id: int) -> list[int]:
    return list(
        db.scalars(
            select(RankingEntry.score)
            .where(
                RankingEntry.ranking_snapshot_id == snapshot_id,
                RankingEntry.is_valid.is_(True),
            )
            .order_by(RankingEntry.score.asc(), RankingEntry.rank.asc())
        ).all()
    )


def _build_snapshot_summary(
    db: Session,
    snapshot: RankingSnapshot,
) -> RankingSnapshotSummaryRead:
    valid_entry_count = _count_snapshot_entries_by_validity(db, snapshot.id, True)
    invalid_entry_count = _count_snapshot_entries_by_validity(db, snapshot.id, False)
    highest_score, lowest_score = _get_valid_score_bounds(db, snapshot.id)

    return RankingSnapshotSummaryRead(
        snapshot_id=snapshot.id,
        season_id=snapshot.season_id,
        status=snapshot.status,
        captured_at=snapshot.captured_at,
        total_rows_collected=snapshot.total_rows_collected,
        valid_entry_count=valid_entry_count,
        invalid_entry_count=invalid_entry_count,
        highest_score=highest_score,
        lowest_score=lowest_score,
        validation_issues=_get_validation_issue_counts(db, snapshot.id),
    )


def _build_snapshot_validation_report(
    db: Session,
    snapshot: RankingSnapshot,
) -> RankingSnapshotValidationReportRead:
    valid_entry_count = _count_snapshot_entries_by_validity(db, snapshot.id, True)
    invalid_entry_count = _count_snapshot_entries_by_validity(db, snapshot.id, False)
    validation_issues = _get_validation_issue_counts(db, snapshot.id)
    entry_rows = db.execute(
        select(RankingEntry.rank).where(
            RankingEntry.ranking_snapshot_id == snapshot.id,
        ).order_by(RankingEntry.id.asc())
    ).all()
    validation_summary = summarize_snapshot_entries(
        [{"rank": rank} for rank, in entry_rows]
    )

    return RankingSnapshotValidationReportRead(
        snapshot_id=snapshot.id,
        status=snapshot.status,
        total_entry_count=valid_entry_count + invalid_entry_count,
        valid_entry_count=valid_entry_count,
        invalid_entry_count=invalid_entry_count,
        excluded_from_statistics_count=invalid_entry_count,
        invalid_ratio=_calculate_invalid_ratio(valid_entry_count, invalid_entry_count),
        duplicate_rank_count=len(validation_summary.duplicate_ranks),
        has_rank_order_violation=validation_summary.has_rank_order_violation,
        top_validation_issue=_get_top_validation_issue(validation_issues),
        validation_issues=validation_issues,
        collector_diagnostics=_build_collector_diagnostics_read(snapshot),
    )


def _build_snapshot_cutoffs(
    db: Session,
    snapshot: RankingSnapshot,
) -> RankingSnapshotCutoffsRead:
    rows = db.execute(
        select(RankingEntry.rank, RankingEntry.score).where(
            RankingEntry.ranking_snapshot_id == snapshot.id,
            RankingEntry.is_valid.is_(True),
            RankingEntry.rank.in_(DEFAULT_CUTOFF_RANKS),
        )
    ).all()
    score_by_rank = {rank: score for rank, score in rows}

    return RankingSnapshotCutoffsRead(
        snapshot_id=snapshot.id,
        status=snapshot.status,
        cutoffs=[
            RankingSnapshotCutoffRead(rank=rank, score=score_by_rank.get(rank))
            for rank in DEFAULT_CUTOFF_RANKS
        ],
    )


def _build_snapshot_distribution(
    db: Session,
    snapshot: RankingSnapshot,
) -> RankingSnapshotDistributionRead:
    scores = _get_valid_scores(db, snapshot.id)
    if not scores:
        return RankingSnapshotDistributionRead(
            snapshot_id=snapshot.id,
            status=snapshot.status,
            count=0,
            min_score=None,
            max_score=None,
            avg_score=None,
            median_score=None,
        )

    return RankingSnapshotDistributionRead(
        snapshot_id=snapshot.id,
        status=snapshot.status,
        count=len(scores),
        min_score=min(scores),
        max_score=max(scores),
        avg_score=sum(scores) / len(scores),
        median_score=float(median(scores)),
    )


def _build_season_cutoff_series(
    db: Session,
    season: Season,
    rank: int,
    *,
    source_type: str | None = None,
) -> SeasonCutoffSeriesRead:
    snapshot_filters = _build_season_snapshot_filters(
        season_id=season.id,
        status=COMPLETED_STATUS,
        source_type=source_type,
    )
    snapshots = list(
        db.scalars(
            select(RankingSnapshot)
            .where(*snapshot_filters)
            .order_by(RankingSnapshot.captured_at.asc(), RankingSnapshot.id.asc())
        ).all()
    )

    snapshot_ids = [snapshot.id for snapshot in snapshots]
    if snapshot_ids:
        rows = db.execute(
            select(RankingEntry.ranking_snapshot_id, RankingEntry.score).where(
                RankingEntry.ranking_snapshot_id.in_(snapshot_ids),
                RankingEntry.rank == rank,
                RankingEntry.is_valid.is_(True),
            )
        ).all()
        score_by_snapshot_id = {snapshot_id: score for snapshot_id, score in rows}
    else:
        score_by_snapshot_id = {}

    return SeasonCutoffSeriesRead(
        season_id=season.id,
        rank=rank,
        points=[
            SeasonCutoffSeriesPointRead(
                snapshot_id=snapshot.id,
                captured_at=snapshot.captured_at,
                score=score_by_snapshot_id.get(snapshot.id),
            )
            for snapshot in snapshots
        ],
    )


def _build_season_validation_overview(
    db: Session,
    season: Season,
    *,
    status: str | None = None,
    source_type: str | None = None,
    collector_filter: str | None = None,
    capture_stop_reason: str | None = None,
    ocr_stop_reason: str | None = None,
    ignored_reason: str | None = None,
    ignored_group: str | None = None,
    page_signal: str | None = None,
    ocr_stop_level: str | None = None,
) -> SeasonValidationOverviewRead:
    snapshot_rows = _get_filtered_season_snapshots(
        db,
        season_id=season.id,
        status=status,
        source_type=source_type,
        collector_filter=collector_filter,
        capture_stop_reason=capture_stop_reason,
        ocr_stop_reason=ocr_stop_reason,
        ignored_reason=ignored_reason,
        ignored_group=ignored_group,
        page_signal=page_signal,
        ocr_stop_level=ocr_stop_level,
    )
    snapshots = [snapshot for snapshot, _ in snapshot_rows]
    snapshot_counts: dict[str, int] = {}
    collector_diagnostics = []
    for snapshot, diagnostics in snapshot_rows:
        snapshot_counts[snapshot.status] = snapshot_counts.get(snapshot.status, 0) + 1
        if diagnostics is not None:
            collector_diagnostics.append(diagnostics)

    snapshot_ids = [snapshot.id for snapshot in snapshots]

    if snapshot_ids:
        valid_entry_count = db.scalar(
            select(func.count(RankingEntry.id)).where(
                RankingEntry.ranking_snapshot_id.in_(snapshot_ids),
                RankingEntry.is_valid.is_(True),
            )
        ) or 0
        invalid_entry_count = db.scalar(
            select(func.count(RankingEntry.id)).where(
                RankingEntry.ranking_snapshot_id.in_(snapshot_ids),
                RankingEntry.is_valid.is_(False),
            )
        ) or 0
        issue_rows = db.execute(
            select(
                RankingEntry.validation_issue,
                func.count(RankingEntry.id),
            )
            .where(
                RankingEntry.ranking_snapshot_id.in_(snapshot_ids),
                RankingEntry.is_valid.is_(False),
                RankingEntry.validation_issue.is_not(None),
            )
            .group_by(RankingEntry.validation_issue)
            .order_by(RankingEntry.validation_issue.asc())
        ).all()
    else:
        valid_entry_count = 0
        invalid_entry_count = 0
        issue_rows = []

    snapshot_count = len(snapshots)

    validation_issues = [
        RankingSnapshotValidationIssueCountRead(code=code, count=count)
        for code, count in issue_rows
    ]
    capture_stop_reason_counts: dict[str, int] = {}
    ocr_stop_reason_counts: dict[str, int] = {}
    ignored_reason_counts: dict[str, int] = {}
    empty_page_count = 0
    sparse_page_count = 0
    overlapping_page_count = 0
    stale_page_count = 0
    noisy_page_count = 0
    overlay_ignored_line_count = 0
    header_ignored_line_count = 0
    malformed_entry_line_count = 0
    for row in collector_diagnostics:
        if row.capture_stop_reason is not None:
            capture_stop_reason_counts[row.capture_stop_reason] = (
                capture_stop_reason_counts.get(row.capture_stop_reason, 0) + 1
            )
        if row.ocr_stop_reason is not None:
            ocr_stop_reason_counts[row.ocr_stop_reason] = (
                ocr_stop_reason_counts.get(row.ocr_stop_reason, 0) + 1
            )
        for ignored_reason in row.ignored_reasons:
            ignored_reason_counts[ignored_reason.reason] = (
                ignored_reason_counts.get(ignored_reason.reason, 0)
                + ignored_reason.count
            )
        empty_page_count += row.empty_page_count
        sparse_page_count += row.sparse_page_count
        overlapping_page_count += row.overlapping_page_count
        stale_page_count += row.stale_page_count
        noisy_page_count += row.noisy_page_count
        overlay_ignored_line_count += row.overlay_ignored_line_count
        header_ignored_line_count += row.header_ignored_line_count
        malformed_entry_line_count += row.malformed_entry_line_count

    return SeasonValidationOverviewRead(
        season_id=season.id,
        snapshot_count=snapshot_count,
        completed_snapshot_count=snapshot_counts.get(COMPLETED_STATUS, 0),
        collecting_snapshot_count=snapshot_counts.get(COLLECTING_STATUS, 0),
        failed_snapshot_count=snapshot_counts.get(FAILED_STATUS, 0),
        total_entry_count=valid_entry_count + invalid_entry_count,
        valid_entry_count=valid_entry_count,
        invalid_entry_count=invalid_entry_count,
        excluded_from_statistics_count=invalid_entry_count,
        invalid_ratio=_calculate_invalid_ratio(valid_entry_count, invalid_entry_count),
        top_validation_issue=_get_top_validation_issue(validation_issues),
        validation_issues=validation_issues,
        snapshots_with_collector_diagnostics_count=len(collector_diagnostics),
        snapshots_with_capture_stop_count=sum(
            1 for row in collector_diagnostics if row.capture_stop_reason is not None
        ),
        snapshots_with_hard_ocr_stop_count=sum(
            1 for row in collector_diagnostics if row.ocr_stop_level == "hard"
        ),
        total_ignored_line_count=sum(row.ignored_line_count for row in collector_diagnostics),
        empty_page_count=empty_page_count,
        sparse_page_count=sparse_page_count,
        overlapping_page_count=overlapping_page_count,
        stale_page_count=stale_page_count,
        noisy_page_count=noisy_page_count,
        overlay_ignored_line_count=overlay_ignored_line_count,
        header_ignored_line_count=header_ignored_line_count,
        malformed_entry_line_count=malformed_entry_line_count,
        capture_stop_reasons=[
            CollectorReasonCountRead(reason=reason, count=count)
            for reason, count in sorted(capture_stop_reason_counts.items())
        ],
        ocr_stop_reasons=[
            CollectorReasonCountRead(reason=reason, count=count)
            for reason, count in sorted(ocr_stop_reason_counts.items())
        ],
        ignored_reasons=[
            CollectorIgnoredReasonCountRead(reason=reason, count=count)
            for reason, count in sorted(ignored_reason_counts.items())
        ],
    )


def _build_season_validation_series(
    db: Session,
    season: Season,
    *,
    status: str | None = None,
    source_type: str | None = None,
    collector_filter: str | None = None,
    capture_stop_reason: str | None = None,
    ocr_stop_reason: str | None = None,
    ignored_reason: str | None = None,
    ignored_group: str | None = None,
    page_signal: str | None = None,
    ocr_stop_level: str | None = None,
) -> SeasonValidationSeriesRead:
    points: list[SeasonValidationSeriesPointRead] = []
    for snapshot, diagnostics in _get_filtered_season_snapshots(
        db,
        season_id=season.id,
        status=status,
        source_type=source_type,
        collector_filter=collector_filter,
        capture_stop_reason=capture_stop_reason,
        ocr_stop_reason=ocr_stop_reason,
        ignored_reason=ignored_reason,
        ignored_group=ignored_group,
        page_signal=page_signal,
        ocr_stop_level=ocr_stop_level,
    ):
        valid_entry_count = _count_snapshot_entries_by_validity(db, snapshot.id, True)
        invalid_entry_count = _count_snapshot_entries_by_validity(db, snapshot.id, False)
        validation_issues = _get_validation_issue_counts(db, snapshot.id)
        points.append(
            SeasonValidationSeriesPointRead(
                snapshot_id=snapshot.id,
                captured_at=snapshot.captured_at,
                status=snapshot.status,
                total_entry_count=valid_entry_count + invalid_entry_count,
                valid_entry_count=valid_entry_count,
                invalid_entry_count=invalid_entry_count,
                invalid_ratio=_calculate_invalid_ratio(valid_entry_count, invalid_entry_count),
                top_validation_issue=_get_top_validation_issue(validation_issues),
                collector_diagnostics=diagnostics,
            )
        )

    return SeasonValidationSeriesRead(
        season_id=season.id,
        points=points,
    )


def _build_season_snapshot_filters(
    *,
    season_id: int,
    status: str | None,
    source_type: str | None,
):
    filters = [RankingSnapshot.season_id == season_id]
    if status is not None:
        filters.append(RankingSnapshot.status == status)
    if source_type is not None:
        filters.append(RankingSnapshot.source_type == source_type)
    return filters


@router.post("/seasons/{season_id}/ranking-snapshots", response_model=RankingSnapshotRead, status_code=201)
def create_ranking_snapshot(
    season_id: int,
    payload: RankingSnapshotCreate,
    db: Session = Depends(get_db),
) -> RankingSnapshot:
    season = db.get(Season, season_id)
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found")

    snapshot = RankingSnapshot(
        season_id=season_id,
        **payload.model_dump(),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.get("/seasons/{season_id}/ranking-snapshots", response_model=list[RankingSnapshotRead])
def list_ranking_snapshots(
    season_id: int,
    db: Session = Depends(get_db),
) -> list[RankingSnapshot]:
    season = db.get(Season, season_id)
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found")

    snapshots = db.scalars(
        select(RankingSnapshot)
        .where(RankingSnapshot.season_id == season_id)
        .order_by(RankingSnapshot.captured_at.desc(), RankingSnapshot.id.desc())
    ).all()

    return list(snapshots)


@router.get("/ranking-snapshots/{snapshot_id}", response_model=RankingSnapshotRead)
def get_ranking_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db),
) -> RankingSnapshot:
    return _get_ranking_snapshot_or_404(db, snapshot_id)


@router.patch(
    "/ranking-snapshots/{snapshot_id}/status",
    response_model=RankingSnapshotRead,
)
def update_ranking_snapshot_status(
    snapshot_id: int,
    payload: RankingSnapshotStatusUpdate,
    db: Session = Depends(get_db),
) -> RankingSnapshot:
    snapshot = _get_ranking_snapshot_or_404(db, snapshot_id)
    _ensure_valid_status_transition(snapshot.status, payload.status)

    snapshot.status = payload.status
    if payload.status == COMPLETED_STATUS:
        snapshot.total_rows_collected = _count_ranking_entries(db, snapshot_id)

    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.get(
    "/ranking-snapshots/{snapshot_id}/summary",
    response_model=RankingSnapshotSummaryRead,
)
def get_ranking_snapshot_summary(
    snapshot_id: int,
    db: Session = Depends(get_db),
) -> RankingSnapshotSummaryRead:
    snapshot = _get_ranking_snapshot_or_404(db, snapshot_id)
    return _build_snapshot_summary(db, snapshot)


@router.get(
    "/ranking-snapshots/{snapshot_id}/validation-report",
    response_model=RankingSnapshotValidationReportRead,
)
def get_ranking_snapshot_validation_report(
    snapshot_id: int,
    db: Session = Depends(get_db),
) -> RankingSnapshotValidationReportRead:
    snapshot = _get_ranking_snapshot_or_404(db, snapshot_id)
    return _build_snapshot_validation_report(db, snapshot)


@router.get(
    "/ranking-snapshots/{snapshot_id}/cutoffs",
    response_model=RankingSnapshotCutoffsRead,
)
def get_ranking_snapshot_cutoffs(
    snapshot_id: int,
    db: Session = Depends(get_db),
) -> RankingSnapshotCutoffsRead:
    snapshot = _get_ranking_snapshot_or_404(db, snapshot_id)
    return _build_snapshot_cutoffs(db, snapshot)


@router.get(
    "/ranking-snapshots/{snapshot_id}/distribution",
    response_model=RankingSnapshotDistributionRead,
)
def get_ranking_snapshot_distribution(
    snapshot_id: int,
    db: Session = Depends(get_db),
) -> RankingSnapshotDistributionRead:
    snapshot = _get_ranking_snapshot_or_404(db, snapshot_id)
    return _build_snapshot_distribution(db, snapshot)


@router.get(
    "/seasons/{season_id}/cutoff-series",
    response_model=SeasonCutoffSeriesRead,
)
def get_season_cutoff_series(
    season_id: int,
    rank: int = Query(..., ge=1),
    source_type: str | None = Query(None, min_length=1),
    db: Session = Depends(get_db),
) -> SeasonCutoffSeriesRead:
    season = _get_season_or_404(db, season_id)
    return _build_season_cutoff_series(
        db,
        season,
        rank,
        source_type=source_type,
    )


@router.get(
    "/seasons/{season_id}/validation-overview",
    response_model=SeasonValidationOverviewRead,
)
def get_season_validation_overview(
    season_id: int,
    status: Literal["collecting", "completed", "failed"] | None = Query(None),
    source_type: str | None = Query(None, min_length=1),
    collector_filter: Literal["with_diagnostics", "capture_stop", "hard_ocr_stop"] | None = Query(None),
    capture_stop_reason: str | None = Query(None, min_length=1),
    ocr_stop_reason: str | None = Query(None, min_length=1),
    ignored_reason: str | None = Query(None, min_length=1),
    ignored_group: Literal["overlay", "header", "malformed"] | None = Query(None),
    page_signal: Literal["empty", "sparse", "overlapping", "stale", "noisy"] | None = Query(None),
    ocr_stop_level: Literal["soft", "hard"] | None = Query(None),
    db: Session = Depends(get_db),
) -> SeasonValidationOverviewRead:
    season = _get_season_or_404(db, season_id)
    return _build_season_validation_overview(
        db,
        season,
        status=status,
        source_type=source_type,
        collector_filter=collector_filter,
        capture_stop_reason=capture_stop_reason,
        ocr_stop_reason=ocr_stop_reason,
        ignored_reason=ignored_reason,
        ignored_group=ignored_group,
        page_signal=page_signal,
        ocr_stop_level=ocr_stop_level,
    )


@router.get(
    "/seasons/{season_id}/validation-series",
    response_model=SeasonValidationSeriesRead,
)
def get_season_validation_series(
    season_id: int,
    status: Literal["collecting", "completed", "failed"] | None = Query(None),
    source_type: str | None = Query(None, min_length=1),
    collector_filter: Literal["with_diagnostics", "capture_stop", "hard_ocr_stop"] | None = Query(None),
    capture_stop_reason: str | None = Query(None, min_length=1),
    ocr_stop_reason: str | None = Query(None, min_length=1),
    ignored_reason: str | None = Query(None, min_length=1),
    ignored_group: Literal["overlay", "header", "malformed"] | None = Query(None),
    page_signal: Literal["empty", "sparse", "overlapping", "stale", "noisy"] | None = Query(None),
    ocr_stop_level: Literal["soft", "hard"] | None = Query(None),
    db: Session = Depends(get_db),
) -> SeasonValidationSeriesRead:
    season = _get_season_or_404(db, season_id)
    return _build_season_validation_series(
        db,
        season,
        status=status,
        source_type=source_type,
        collector_filter=collector_filter,
        capture_stop_reason=capture_stop_reason,
        ocr_stop_reason=ocr_stop_reason,
        ignored_reason=ignored_reason,
        ignored_group=ignored_group,
        page_signal=page_signal,
        ocr_stop_level=ocr_stop_level,
    )
