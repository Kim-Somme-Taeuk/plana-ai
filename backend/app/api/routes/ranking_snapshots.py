from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.ranking_snapshot import RankingSnapshot
from app.models.season import Season
from app.schemas.ranking_snapshot import RankingSnapshotCreate, RankingSnapshotRead

router = APIRouter(tags=["ranking_snapshots"])


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
    snapshot = db.get(RankingSnapshot, snapshot_id)

    if snapshot is None:
        raise HTTPException(status_code=404, detail="Ranking snapshot not found")

    return snapshot
