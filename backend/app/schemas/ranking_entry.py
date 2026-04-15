from pydantic import BaseModel, ConfigDict


class RankingEntryBase(BaseModel):
    rank: int
    score: int
    player_name: str | None = None
    ocr_confidence: float | None = None
    raw_text: str | None = None
    image_path: str | None = None
    is_valid: bool = True
    validation_issue: str | None = None


class RankingEntryCreate(RankingEntryBase):
    pass


class RankingEntryRead(RankingEntryBase):
    id: int
    ranking_snapshot_id: int

    model_config = ConfigDict(from_attributes=True)
