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
