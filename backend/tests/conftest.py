from datetime import UTC, datetime
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.ranking_entry import RankingEntry
from app.models.ranking_snapshot import RankingSnapshot
from app.models.season import Season


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> TestClient:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Session:
    session = session_factory()
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
def ranking_entry(
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> RankingEntry:
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
