from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class RankingSnapshotBase(BaseModel):
    captured_at: datetime
    source_type: str = "manual"
    status: str = "collecting"
    total_rows_collected: int | None = None
    note: str | None = None


class RankingSnapshotCreate(RankingSnapshotBase):
    pass


class RankingSnapshotStatusUpdate(BaseModel):
    status: Literal["collecting", "completed", "failed"]


class RankingSnapshotRead(RankingSnapshotBase):
    id: int
    season_id: int

    model_config = ConfigDict(from_attributes=True)
