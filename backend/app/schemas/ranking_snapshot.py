from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RankingSnapshotBase(BaseModel):
    captured_at: datetime
    source_type: str = "manual"
    status: str = "collecting"
    total_rows_collected: int | None = None
    note: str | None = None


class RankingSnapshotCreate(RankingSnapshotBase):
    pass


class RankingSnapshotRead(RankingSnapshotBase):
    id: int
    season_id: int

    model_config = ConfigDict(from_attributes=True)
