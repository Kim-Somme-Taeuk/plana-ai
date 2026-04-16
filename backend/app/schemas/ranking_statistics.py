from datetime import datetime

from pydantic import BaseModel


class RankingSnapshotValidationIssueCountRead(BaseModel):
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
    duplicate_rank_count: int
    has_rank_order_violation: bool
    validation_issues: list[RankingSnapshotValidationIssueCountRead]


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
    validation_issues: list[RankingSnapshotValidationIssueCountRead]


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
