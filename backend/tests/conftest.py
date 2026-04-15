from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.main import app
from app.models.ranking_entry import RankingEntry
from app.models.ranking_snapshot import RankingSnapshot
from app.models.season import Season


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def ranking_snapshot(db_session: Session) -> RankingSnapshot:
    season = Season(
        event_type="raid",
        server="global",
        boss_name="Binah",
        armor_type="heavy",
        terrain="urban",
        season_label=f"test-ranking-entry-{uuid4()}",
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
    )
    db_session.add(season)
    db_session.commit()
    db_session.refresh(season)

    snapshot = RankingSnapshot(
        season_id=season.id,
        captured_at=datetime.now(UTC),
        source_type="manual",
        status="collecting",
        total_rows_collected=0,
        note="ranking entry api test fixture",
    )
    db_session.add(snapshot)
    db_session.commit()
    db_session.refresh(snapshot)
    return snapshot


@pytest.fixture
def ranking_entry(db_session: Session, ranking_snapshot: RankingSnapshot) -> RankingEntry:
    entry = RankingEntry(
        ranking_snapshot_id=ranking_snapshot.id,
        rank=1,
        score=100000,
        player_name="Fixture Player",
        ocr_confidence=0.97,
        raw_text="1 Fixture Player 100000",
        image_path="/tmp/fixture-entry.png",
        is_valid=True,
        validation_issue=None,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry
