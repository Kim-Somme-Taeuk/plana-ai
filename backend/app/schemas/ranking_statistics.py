from datetime import datetime

from pydantic import BaseModel


class RankingSnapshotValidationIssueCountRead(BaseModel):
    code: str
    count: int


class CollectorIgnoredReasonCountRead(BaseModel):
    reason: str
    count: int


class CollectorReasonCountRead(BaseModel):
    reason: str
    count: int


class CollectorDiagnosticsRead(BaseModel):
    raw_summary: str
    captured_page_count: int | None = None
    requested_page_count: int | None = None
    capture_stop_reason: str | None = None
    ignored_line_count: int
    ignored_reasons: list[CollectorIgnoredReasonCountRead]
    ocr_stop_reason: str | None = None
    ocr_stop_level: str | None = None


class ValidationTopIssueRead(BaseModel):
    code: str
    count: int


class RankingSnapshotSummaryRead(BaseModel):
    snapshot_id: int
    season_id: int
    status: str
    captured_at: datetime
    total_rows_collected: int | None = None
    valid_entry_count: int
    invalid_entry_count: int
    highest_score: int | None = None
    lowest_score: int | None = None
    validation_issues: list[RankingSnapshotValidationIssueCountRead]


class RankingSnapshotValidationReportRead(BaseModel):
    snapshot_id: int
    status: str
    total_entry_count: int
    valid_entry_count: int
    invalid_entry_count: int
    excluded_from_statistics_count: int
    invalid_ratio: float
    duplicate_rank_count: int
    has_rank_order_violation: bool
    top_validation_issue: ValidationTopIssueRead | None = None
    validation_issues: list[RankingSnapshotValidationIssueCountRead]
    collector_diagnostics: CollectorDiagnosticsRead | None = None


class SeasonValidationOverviewRead(BaseModel):
    season_id: int
    snapshot_count: int
    completed_snapshot_count: int
    collecting_snapshot_count: int
    failed_snapshot_count: int
    total_entry_count: int
    valid_entry_count: int
    invalid_entry_count: int
    excluded_from_statistics_count: int
    invalid_ratio: float
    top_validation_issue: ValidationTopIssueRead | None = None
    validation_issues: list[RankingSnapshotValidationIssueCountRead]
    snapshots_with_collector_diagnostics_count: int
    snapshots_with_capture_stop_count: int
    snapshots_with_hard_ocr_stop_count: int
    total_ignored_line_count: int
    capture_stop_reasons: list[CollectorReasonCountRead]
    ocr_stop_reasons: list[CollectorReasonCountRead]
    ignored_reasons: list[CollectorIgnoredReasonCountRead]


class SeasonValidationSeriesPointRead(BaseModel):
    snapshot_id: int
    captured_at: datetime
    status: str
    total_entry_count: int
    valid_entry_count: int
    invalid_entry_count: int
    invalid_ratio: float
    top_validation_issue: ValidationTopIssueRead | None = None
    collector_diagnostics: CollectorDiagnosticsRead | None = None


class SeasonValidationSeriesRead(BaseModel):
    season_id: int
    points: list[SeasonValidationSeriesPointRead]


class RankingSnapshotCutoffRead(BaseModel):
    rank: int
    score: int | None = None


class RankingSnapshotCutoffsRead(BaseModel):
    snapshot_id: int
    status: str
    cutoffs: list[RankingSnapshotCutoffRead]


class RankingSnapshotDistributionRead(BaseModel):
    snapshot_id: int
    status: str
    count: int
    min_score: int | None = None
    max_score: int | None = None
    avg_score: float | None = None
    median_score: float | None = None


class SeasonCutoffSeriesPointRead(BaseModel):
    snapshot_id: int
    captured_at: datetime
    score: int | None = None


class SeasonCutoffSeriesRead(BaseModel):
    season_id: int
    rank: int
    points: list[SeasonCutoffSeriesPointRead]
