from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.ranking_entry_validation import ValidationIssueCode


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
    player_name: str | None = Field(default=None, max_length=100)
    raw_text: str | None = Field(default=None, max_length=255)
    image_path: str | None = Field(default=None, max_length=255)
    validation_issue: str | None = Field(default=None, max_length=255)


class RankingEntryListParams(BaseModel):
    is_valid: bool | None = None
    validation_issue: ValidationIssueCode | None = None
    limit: int | None = Field(default=None, ge=1, le=100)
    offset: int | None = Field(default=None, ge=0)
    sort_by: Literal["rank", "score"] | None = None
    order: Literal["asc", "desc"] | None = None


class RankingEntryRead(RankingEntryBase):
    id: int
    ranking_snapshot_id: int

    model_config = ConfigDict(from_attributes=True)
