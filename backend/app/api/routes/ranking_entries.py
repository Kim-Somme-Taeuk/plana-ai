from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.ranking_entry_validation import (
    ValidationIssueCode,
    validate_ranking_entry,
)
from app.db.session import get_db
from app.models.ranking_entry import RankingEntry
from app.models.ranking_snapshot import RankingSnapshot
from app.schemas.ranking_entry import (
    RankingEntryCreate,
    RankingEntryListParams,
    RankingEntryRead,
)

router = APIRouter(tags=["ranking_entries"])

RANKING_ENTRY_SNAPSHOT_RANK_CONSTRAINT = "uq_ranking_entries_snapshot_rank"
COLLECTING_STATUS = "collecting"
SQLITE_SNAPSHOT_RANK_CONFLICT = (
    "UNIQUE constraint failed: "
    "ranking_entries.ranking_snapshot_id, ranking_entries.rank"
)
SORTABLE_RANKING_ENTRY_FIELDS = {
    "rank": RankingEntry.rank,
    "score": RankingEntry.score,
}


def _is_snapshot_rank_conflict(exc: IntegrityError) -> bool:
    constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint_name == RANKING_ENTRY_SNAPSHOT_RANK_CONSTRAINT:
        return True

    error_message = str(exc.orig)
    return (
        RANKING_ENTRY_SNAPSHOT_RANK_CONSTRAINT in error_message
        or SQLITE_SNAPSHOT_RANK_CONFLICT in error_message
    )


def _get_ranking_snapshot_or_404(db: Session, snapshot_id: int) -> RankingSnapshot:
    snapshot = db.get(RankingSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Ranking snapshot not found")
    return snapshot


def _get_ranking_entry_list_params(
    is_valid: Annotated[
        bool | None,
        Query(
            description="Filter entries by validation status",
        ),
    ] = None,
    validation_issue: Annotated[
        ValidationIssueCode | None,
        Query(
            description="Filter entries by validation issue code",
        ),
    ] = None,
    limit: Annotated[
        int | None,
        Query(
            ge=1,
            le=100,
            description="Maximum number of entries to return",
        ),
    ] = None,
    offset: Annotated[
        int | None,
        Query(
            ge=0,
            description="Number of entries to skip",
        ),
    ] = None,
    sort_by: Annotated[
        str | None,
        Query(
            pattern="^(rank|score)$",
            description="Sort field. Allowed values: rank, score",
        ),
    ] = None,
    order: Annotated[
        str | None,
        Query(
            pattern="^(asc|desc)$",
            description="Sort order. Allowed values: asc, desc",
        ),
    ] = None,
) -> RankingEntryListParams:
    return RankingEntryListParams(
        is_valid=is_valid,
        validation_issue=validation_issue,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        order=order,
    )


def _build_ranking_entries_query(
    snapshot_id: int,
    params: RankingEntryListParams,
):
    statement = select(RankingEntry).where(
        RankingEntry.ranking_snapshot_id == snapshot_id
    )

    if params.is_valid is not None:
        statement = statement.where(RankingEntry.is_valid == params.is_valid)

    if params.validation_issue is not None:
        statement = statement.where(
            RankingEntry.validation_issue == params.validation_issue.value
        )

    sort_by = params.sort_by or "rank"
    order = params.order or "asc"
    sort_column = SORTABLE_RANKING_ENTRY_FIELDS[sort_by]
    sort_expression = sort_column.asc() if order == "asc" else sort_column.desc()
    statement = statement.order_by(sort_expression, RankingEntry.id.asc())

    if params.limit is not None:
        statement = statement.limit(params.limit)

    if params.offset is not None:
        statement = statement.offset(params.offset)

    return statement


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
    snapshot = _get_ranking_snapshot_or_404(db, snapshot_id)
    if snapshot.status != COLLECTING_STATUS:
        raise HTTPException(
            status_code=409,
            detail="Ranking snapshot is not accepting new entries",
        )

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

    validation = validate_ranking_entry(
        rank=payload.rank,
        score=payload.score,
        player_name=payload.player_name,
        ocr_confidence=payload.ocr_confidence,
    )

    entry_payload = payload.model_dump()
    entry_payload["is_valid"] = validation.is_valid
    entry_payload["validation_issue"] = validation.validation_issue

    entry = RankingEntry(
        ranking_snapshot_id=snapshot_id,
        **entry_payload,
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
    params: RankingEntryListParams = Depends(_get_ranking_entry_list_params),
    db: Session = Depends(get_db),
) -> list[RankingEntry]:
    _get_ranking_snapshot_or_404(db, snapshot_id)

    entries = db.scalars(_build_ranking_entries_query(snapshot_id, params)).all()

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
