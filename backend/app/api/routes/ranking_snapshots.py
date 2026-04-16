from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.ranking_entry import RankingEntry
from app.models.ranking_snapshot import RankingSnapshot
from app.models.season import Season
from app.schemas.ranking_snapshot import (
    RankingSnapshotCreate,
    RankingSnapshotRead,
    RankingSnapshotStatusUpdate,
)

router = APIRouter(tags=["ranking_snapshots"])

COLLECTING_STATUS = "collecting"
COMPLETED_STATUS = "completed"
FAILED_STATUS = "failed"
ALLOWED_STATUS_TRANSITIONS = {
    (COLLECTING_STATUS, COMPLETED_STATUS),
    (COLLECTING_STATUS, FAILED_STATUS),
}


def _get_ranking_snapshot_or_404(db: Session, snapshot_id: int) -> RankingSnapshot:
    snapshot = db.get(RankingSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Ranking snapshot not found")
    return snapshot


def _ensure_valid_status_transition(current_status: str, next_status: str) -> None:
    if current_status == next_status:
        return

    if (current_status, next_status) not in ALLOWED_STATUS_TRANSITIONS:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid status transition from {current_status} to {next_status}",
        )


def _count_ranking_entries(db: Session, snapshot_id: int) -> int:
    count = db.scalar(
        select(func.count(RankingEntry.id)).where(
            RankingEntry.ranking_snapshot_id == snapshot_id
        )
    )
    return count or 0


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
    return _get_ranking_snapshot_or_404(db, snapshot_id)


@router.patch(
    "/ranking-snapshots/{snapshot_id}/status",
    response_model=RankingSnapshotRead,
)
def update_ranking_snapshot_status(
    snapshot_id: int,
    payload: RankingSnapshotStatusUpdate,
    db: Session = Depends(get_db),
) -> RankingSnapshot:
    snapshot = _get_ranking_snapshot_or_404(db, snapshot_id)
    _ensure_valid_status_transition(snapshot.status, payload.status)

    snapshot.status = payload.status
    if payload.status == COMPLETED_STATUS:
        snapshot.total_rows_collected = _count_ranking_entries(db, snapshot_id)

    db.commit()
    db.refresh(snapshot)
    return snapshot
