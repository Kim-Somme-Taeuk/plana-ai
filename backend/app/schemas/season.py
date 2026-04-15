from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SeasonBase(BaseModel):
    event_type: str
    server: str
    boss_name: str
    armor_type: str | None = None
    terrain: str
    season_label: str
    started_at: datetime | None = None
    ended_at: datetime | None = None


class SeasonCreate(SeasonBase):
    pass


class SeasonRead(SeasonBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
