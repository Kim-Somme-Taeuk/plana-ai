from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.ranking_entry import RankingEntry
from app.models.ranking_snapshot import RankingSnapshot
from app.schemas.ranking_entry import RankingEntryCreate, RankingEntryRead

router = APIRouter(tags=["ranking_entries"])

RANKING_ENTRY_SNAPSHOT_RANK_CONSTRAINT = "uq_ranking_entries_snapshot_rank"


def _is_snapshot_rank_conflict(exc: IntegrityError) -> bool:
    constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint_name == RANKING_ENTRY_SNAPSHOT_RANK_CONSTRAINT:
        return True

    return RANKING_ENTRY_SNAPSHOT_RANK_CONSTRAINT in str(exc.orig)


@router.post(
    "/ranking-snapshots/{snapshot_id}/entries",
    response_model=RankingEntryRead,
    status_code=201,
)
def create_ranking_entry(
    snapshot_id: int,
    payload: RankingEntryCreate,
    db: Session = Depends(get_db),
) -> RankingEntry:
    snapshot = db.get(RankingSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Ranking snapshot not found")

    existing = db.scalar(
        select(RankingEntry).where(
            RankingEntry.ranking_snapshot_id == snapshot_id,
            RankingEntry.rank == payload.rank,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Rank already exists for this ranking snapshot",
        )

    entry = RankingEntry(
        ranking_snapshot_id=snapshot_id,
        **payload.model_dump(),
    )
    db.add(entry)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_snapshot_rank_conflict(exc):
            raise HTTPException(
                status_code=409,
                detail="Rank already exists for this ranking snapshot",
            ) from exc
        raise

    db.refresh(entry)
    return entry


@router.get(
    "/ranking-snapshots/{snapshot_id}/entries",
    response_model=list[RankingEntryRead],
)
def list_ranking_entries(
    snapshot_id: int,
    db: Session = Depends(get_db),
) -> list[RankingEntry]:
    snapshot = db.get(RankingSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Ranking snapshot not found")

    entries = db.scalars(
        select(RankingEntry)
        .where(RankingEntry.ranking_snapshot_id == snapshot_id)
        .order_by(RankingEntry.rank.asc())
    ).all()

    return list(entries)


@router.get("/ranking-entries/{entry_id}", response_model=RankingEntryRead)
def get_ranking_entry(
    entry_id: int,
    db: Session = Depends(get_db),
) -> RankingEntry:
    entry = db.get(RankingEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Ranking entry not found")

    return entry
