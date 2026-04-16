from statistics import median

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.ranking_entry import RankingEntry
from app.models.ranking_snapshot import RankingSnapshot
from app.models.season import Season
from app.schemas.ranking_statistics import (
    RankingSnapshotCutoffRead,
    RankingSnapshotCutoffsRead,
    RankingSnapshotDistributionRead,
    RankingSnapshotSummaryRead,
    SeasonCutoffSeriesPointRead,
    SeasonCutoffSeriesRead,
)
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
DEFAULT_CUTOFF_RANKS = (1, 10, 100, 1000, 5000, 10000)


def _get_ranking_snapshot_or_404(db: Session, snapshot_id: int) -> RankingSnapshot:
    snapshot = db.get(RankingSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Ranking snapshot not found")
    return snapshot


def _get_season_or_404(db: Session, season_id: int) -> Season:
    season = db.get(Season, season_id)
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found")
    return season


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


def _count_snapshot_entries_by_validity(
    db: Session,
    snapshot_id: int,
    is_valid: bool,
) -> int:
    count = db.scalar(
        select(func.count(RankingEntry.id)).where(
            RankingEntry.ranking_snapshot_id == snapshot_id,
            RankingEntry.is_valid.is_(is_valid),
        )
    )
    return count or 0


def _get_valid_score_bounds(
    db: Session,
    snapshot_id: int,
) -> tuple[int | None, int | None]:
    row = db.execute(
        select(
            func.max(RankingEntry.score),
            func.min(RankingEntry.score),
        ).where(
            RankingEntry.ranking_snapshot_id == snapshot_id,
            RankingEntry.is_valid.is_(True),
        )
    ).one()
    return row[0], row[1]


def _get_valid_scores(db: Session, snapshot_id: int) -> list[int]:
    return list(
        db.scalars(
            select(RankingEntry.score)
            .where(
                RankingEntry.ranking_snapshot_id == snapshot_id,
                RankingEntry.is_valid.is_(True),
            )
            .order_by(RankingEntry.score.asc(), RankingEntry.rank.asc())
        ).all()
    )


def _build_snapshot_summary(
    db: Session,
    snapshot: RankingSnapshot,
) -> RankingSnapshotSummaryRead:
    valid_entry_count = _count_snapshot_entries_by_validity(db, snapshot.id, True)
    invalid_entry_count = _count_snapshot_entries_by_validity(db, snapshot.id, False)
    highest_score, lowest_score = _get_valid_score_bounds(db, snapshot.id)

    return RankingSnapshotSummaryRead(
        snapshot_id=snapshot.id,
        season_id=snapshot.season_id,
        status=snapshot.status,
        captured_at=snapshot.captured_at,
        total_rows_collected=snapshot.total_rows_collected,
        valid_entry_count=valid_entry_count,
        invalid_entry_count=invalid_entry_count,
        highest_score=highest_score,
        lowest_score=lowest_score,
    )


def _build_snapshot_cutoffs(
    db: Session,
    snapshot: RankingSnapshot,
) -> RankingSnapshotCutoffsRead:
    rows = db.execute(
        select(RankingEntry.rank, RankingEntry.score).where(
            RankingEntry.ranking_snapshot_id == snapshot.id,
            RankingEntry.is_valid.is_(True),
            RankingEntry.rank.in_(DEFAULT_CUTOFF_RANKS),
        )
    ).all()
    score_by_rank = {rank: score for rank, score in rows}

    return RankingSnapshotCutoffsRead(
        snapshot_id=snapshot.id,
        status=snapshot.status,
        cutoffs=[
            RankingSnapshotCutoffRead(rank=rank, score=score_by_rank.get(rank))
            for rank in DEFAULT_CUTOFF_RANKS
        ],
    )


def _build_snapshot_distribution(
    db: Session,
    snapshot: RankingSnapshot,
) -> RankingSnapshotDistributionRead:
    scores = _get_valid_scores(db, snapshot.id)
    if not scores:
        return RankingSnapshotDistributionRead(
            snapshot_id=snapshot.id,
            status=snapshot.status,
            count=0,
            min_score=None,
            max_score=None,
            avg_score=None,
            median_score=None,
        )

    return RankingSnapshotDistributionRead(
        snapshot_id=snapshot.id,
        status=snapshot.status,
        count=len(scores),
        min_score=min(scores),
        max_score=max(scores),
        avg_score=sum(scores) / len(scores),
        median_score=float(median(scores)),
    )


def _build_season_cutoff_series(
    db: Session,
    season: Season,
    rank: int,
) -> SeasonCutoffSeriesRead:
    snapshots = list(
        db.scalars(
            select(RankingSnapshot)
            .where(
                RankingSnapshot.season_id == season.id,
                RankingSnapshot.status == COMPLETED_STATUS,
            )
            .order_by(RankingSnapshot.captured_at.asc(), RankingSnapshot.id.asc())
        ).all()
    )

    snapshot_ids = [snapshot.id for snapshot in snapshots]
    if snapshot_ids:
        rows = db.execute(
            select(RankingEntry.ranking_snapshot_id, RankingEntry.score).where(
                RankingEntry.ranking_snapshot_id.in_(snapshot_ids),
                RankingEntry.rank == rank,
                RankingEntry.is_valid.is_(True),
            )
        ).all()
        score_by_snapshot_id = {snapshot_id: score for snapshot_id, score in rows}
    else:
        score_by_snapshot_id = {}

    return SeasonCutoffSeriesRead(
        season_id=season.id,
        rank=rank,
        points=[
            SeasonCutoffSeriesPointRead(
                snapshot_id=snapshot.id,
                captured_at=snapshot.captured_at,
                score=score_by_snapshot_id.get(snapshot.id),
            )
            for snapshot in snapshots
        ],
    )


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


@router.get(
    "/ranking-snapshots/{snapshot_id}/summary",
    response_model=RankingSnapshotSummaryRead,
)
def get_ranking_snapshot_summary(
    snapshot_id: int,
    db: Session = Depends(get_db),
) -> RankingSnapshotSummaryRead:
    snapshot = _get_ranking_snapshot_or_404(db, snapshot_id)
    return _build_snapshot_summary(db, snapshot)


@router.get(
    "/ranking-snapshots/{snapshot_id}/cutoffs",
    response_model=RankingSnapshotCutoffsRead,
)
def get_ranking_snapshot_cutoffs(
    snapshot_id: int,
    db: Session = Depends(get_db),
) -> RankingSnapshotCutoffsRead:
    snapshot = _get_ranking_snapshot_or_404(db, snapshot_id)
    return _build_snapshot_cutoffs(db, snapshot)


@router.get(
    "/ranking-snapshots/{snapshot_id}/distribution",
    response_model=RankingSnapshotDistributionRead,
)
def get_ranking_snapshot_distribution(
    snapshot_id: int,
    db: Session = Depends(get_db),
) -> RankingSnapshotDistributionRead:
    snapshot = _get_ranking_snapshot_or_404(db, snapshot_id)
    return _build_snapshot_distribution(db, snapshot)


@router.get(
    "/seasons/{season_id}/cutoff-series",
    response_model=SeasonCutoffSeriesRead,
)
def get_season_cutoff_series(
    season_id: int,
    rank: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> SeasonCutoffSeriesRead:
    season = _get_season_or_404(db, season_id)
    return _build_season_cutoff_series(db, season, rank)
