from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.season import Season
from app.schemas.season import SeasonCreate, SeasonRead

router = APIRouter(prefix="/seasons", tags=["seasons"])


@router.post("", response_model=SeasonRead, status_code=201)
def create_season(payload: SeasonCreate, db: Session = Depends(get_db)) -> Season:
    existing = db.scalar(
        select(Season).where(Season.season_label == payload.season_label)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Season label already exists")

    season = Season(**payload.model_dump())
    db.add(season)
    db.commit()
    db.refresh(season)
    return season


@router.get("", response_model=list[SeasonRead])
def list_seasons(db: Session = Depends(get_db)) -> list[Season]:
    seasons = db.scalars(
        select(Season).order_by(Season.id.desc())
    ).all()
    return list(seasons)


@router.get("/{season_id}", response_model=SeasonRead)
def get_season(season_id: int, db: Session = Depends(get_db)) -> Season:
    season = db.get(Season, season_id)

    if season is None:
        raise HTTPException(status_code=404, detail="Season not found")

    return season
