import sqlite3

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ranking_entry import RankingEntry
from app.models.ranking_snapshot import RankingSnapshot


def test_create_ranking_entry(client, ranking_snapshot: RankingSnapshot) -> None:
    response = client.post(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        json={
            "rank": 2,
            "score": 987654,
            "player_name": "Test Player",
            "ocr_confidence": 0.95,
            "raw_text": "2 Test Player 987654",
            "image_path": "/tmp/test-player.png",
            "is_valid": True,
            "validation_issue": None,
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": response.json()["id"],
        "ranking_snapshot_id": ranking_snapshot.id,
        "rank": 2,
        "score": 987654,
        "player_name": "Test Player",
        "ocr_confidence": 0.95,
        "raw_text": "2 Test Player 987654",
        "image_path": "/tmp/test-player.png",
        "is_valid": True,
        "validation_issue": None,
    }


def test_list_ranking_entries_returns_rank_ascending(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=20,
                score=2000,
                player_name="Rank 20",
                ocr_confidence=0.7,
                raw_text="20 Rank 20 2000",
                image_path="/tmp/rank-20.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=10,
                score=1000,
                player_name="Rank 10",
                ocr_confidence=0.8,
                raw_text="10 Rank 10 1000",
                image_path="/tmp/rank-10.png",
                is_valid=True,
                validation_issue=None,
            ),
        ]
    )
    db_session.commit()

    response = client.get(f"/ranking-snapshots/{ranking_snapshot.id}/entries")

    assert response.status_code == 200
    assert [entry["rank"] for entry in response.json()] == [10, 20]


def test_list_ranking_entries_filters_by_is_valid(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=10,
                score=1000,
                player_name="Valid Entry",
                ocr_confidence=0.8,
                raw_text="10 Valid Entry 1000",
                image_path="/tmp/valid-entry.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=20,
                score=2000,
                player_name="Invalid Entry",
                ocr_confidence=0.6,
                raw_text="20 Invalid Entry 2000",
                image_path="/tmp/invalid-entry.png",
                is_valid=False,
                validation_issue="ocr mismatch",
            ),
        ]
    )
    db_session.commit()

    valid_response = client.get(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        params={"is_valid": "true"},
    )
    invalid_response = client.get(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        params={"is_valid": "false"},
    )

    assert valid_response.status_code == 200
    assert [entry["rank"] for entry in valid_response.json()] == [10]
    assert invalid_response.status_code == 200
    assert [entry["rank"] for entry in invalid_response.json()] == [20]


def test_list_ranking_entries_supports_limit_and_offset(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=10,
                score=1000,
                player_name="Rank 10",
                ocr_confidence=0.8,
                raw_text="10 Rank 10 1000",
                image_path="/tmp/rank-10.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=20,
                score=2000,
                player_name="Rank 20",
                ocr_confidence=0.7,
                raw_text="20 Rank 20 2000",
                image_path="/tmp/rank-20.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=30,
                score=3000,
                player_name="Rank 30",
                ocr_confidence=0.6,
                raw_text="30 Rank 30 3000",
                image_path="/tmp/rank-30.png",
                is_valid=True,
                validation_issue=None,
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        params={"limit": 2, "offset": 1},
    )

    assert response.status_code == 200
    assert [entry["rank"] for entry in response.json()] == [20, 30]


def test_list_ranking_entries_supports_sorting(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    db_session.add_all(
        [
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=30,
                score=1500,
                player_name="Third",
                ocr_confidence=0.6,
                raw_text="30 Third 1500",
                image_path="/tmp/third.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=10,
                score=3500,
                player_name="First",
                ocr_confidence=0.8,
                raw_text="10 First 3500",
                image_path="/tmp/first.png",
                is_valid=True,
                validation_issue=None,
            ),
            RankingEntry(
                ranking_snapshot_id=ranking_snapshot.id,
                rank=20,
                score=2500,
                player_name="Second",
                ocr_confidence=0.7,
                raw_text="20 Second 2500",
                image_path="/tmp/second.png",
                is_valid=True,
                validation_issue=None,
            ),
        ]
    )
    db_session.commit()

    rank_desc_response = client.get(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        params={"sort_by": "rank", "order": "desc"},
    )
    score_asc_response = client.get(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        params={"sort_by": "score", "order": "asc"},
    )
    score_desc_response = client.get(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        params={"sort_by": "score", "order": "desc"},
    )

    assert rank_desc_response.status_code == 200
    assert [entry["rank"] for entry in rank_desc_response.json()] == [30, 20, 10]
    assert score_asc_response.status_code == 200
    assert [entry["score"] for entry in score_asc_response.json()] == [1500, 2500, 3500]
    assert score_desc_response.status_code == 200
    assert [entry["score"] for entry in score_desc_response.json()] == [3500, 2500, 1500]


def test_list_ranking_entries_returns_422_for_invalid_sorting_params(
    client,
    ranking_snapshot: RankingSnapshot,
) -> None:
    invalid_sort_response = client.get(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        params={"sort_by": "captured_at"},
    )
    invalid_order_response = client.get(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        params={"order": "up"},
    )

    assert invalid_sort_response.status_code == 422
    assert invalid_sort_response.json()["detail"]
    assert invalid_order_response.status_code == 422
    assert invalid_order_response.json()["detail"]


def test_list_ranking_entries_returns_422_for_limit_above_maximum(
    client,
    ranking_snapshot: RankingSnapshot,
) -> None:
    response = client.get(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        params={"limit": 101},
    )

    assert response.status_code == 422
    assert response.json()["detail"]


def test_get_ranking_entry(client, ranking_entry: RankingEntry) -> None:
    response = client.get(f"/ranking-entries/{ranking_entry.id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": ranking_entry.id,
        "ranking_snapshot_id": ranking_entry.ranking_snapshot_id,
        "rank": 1,
        "score": 100000,
        "player_name": "Fixture Player",
        "ocr_confidence": 0.97,
        "raw_text": "1 Fixture Player 100000",
        "image_path": "/tmp/fixture-entry.png",
        "is_valid": True,
        "validation_issue": None,
    }


def test_get_ranking_entry_allows_oversized_stored_values(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    entry = RankingEntry(
        ranking_snapshot_id=ranking_snapshot.id,
        rank=40,
        score=4000,
        player_name="P" * 101,
        ocr_confidence=0.9,
        raw_text="R" * 256,
        image_path="I" * 256,
        is_valid=False,
        validation_issue="V" * 256,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)

    response = client.get(f"/ranking-entries/{entry.id}")

    assert response.status_code == 200
    assert response.json()["player_name"] == "P" * 101
    assert response.json()["raw_text"] == "R" * 256
    assert response.json()["image_path"] == "I" * 256
    assert response.json()["validation_issue"] == "V" * 256


def test_list_ranking_entries_allows_oversized_stored_values(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    entry = RankingEntry(
        ranking_snapshot_id=ranking_snapshot.id,
        rank=40,
        score=4000,
        player_name="P" * 101,
        ocr_confidence=0.9,
        raw_text="R" * 256,
        image_path="I" * 256,
        is_valid=False,
        validation_issue="V" * 256,
    )
    db_session.add(entry)
    db_session.commit()

    response = client.get(f"/ranking-snapshots/{ranking_snapshot.id}/entries")

    assert response.status_code == 200
    assert response.json()[0]["player_name"] == "P" * 101
    assert response.json()[0]["raw_text"] == "R" * 256
    assert response.json()[0]["image_path"] == "I" * 256
    assert response.json()[0]["validation_issue"] == "V" * 256


def test_create_ranking_entry_returns_404_for_missing_snapshot(client) -> None:
    response = client.post(
        "/ranking-snapshots/999999/entries",
        json={
            "rank": 1,
            "score": 1000,
            "player_name": "Ghost",
            "ocr_confidence": 0.5,
            "raw_text": "ghost",
            "image_path": "/tmp/ghost.png",
            "is_valid": False,
            "validation_issue": "missing snapshot",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Ranking snapshot not found"}


def test_list_ranking_entries_returns_404_for_missing_snapshot(client) -> None:
    response = client.get("/ranking-snapshots/999999/entries")

    assert response.status_code == 404
    assert response.json() == {"detail": "Ranking snapshot not found"}


def test_get_ranking_entry_returns_404_for_missing_entry(client) -> None:
    response = client.get("/ranking-entries/999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Ranking entry not found"}


def test_create_ranking_entry_returns_409_for_duplicate_rank(
    client,
    ranking_entry: RankingEntry,
) -> None:
    response = client.post(
        f"/ranking-snapshots/{ranking_entry.ranking_snapshot_id}/entries",
        json={
            "rank": ranking_entry.rank,
            "score": 999999,
            "player_name": "Duplicate",
            "ocr_confidence": 0.2,
            "raw_text": "duplicate",
            "image_path": "/tmp/duplicate.png",
            "is_valid": False,
            "validation_issue": "duplicate test",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Rank already exists for this ranking snapshot"
    }


def test_create_ranking_entry_returns_422_for_oversized_fields(
    client,
    ranking_snapshot: RankingSnapshot,
) -> None:
    response = client.post(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        json={
            "rank": 2,
            "score": 987654,
            "player_name": "P" * 101,
            "ocr_confidence": 0.95,
            "raw_text": "R" * 256,
            "image_path": "I" * 256,
            "is_valid": True,
            "validation_issue": "V" * 256,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]


def test_create_ranking_entry_returns_409_for_sqlite_integrity_conflict(
    client,
    monkeypatch,
    ranking_snapshot: RankingSnapshot,
) -> None:
    original_scalar = Session.scalar
    original_commit = Session.commit

    def scalar_without_preflight(
        self,
        statement,
        *args,
        **kwargs,
    ):
        text = str(statement)
        if "FROM ranking_entries" in text and "ranking_entries.rank" in text:
            return None
        return original_scalar(self, statement, *args, **kwargs)

    def commit_with_sqlite_conflict(self, *args, **kwargs):
        raise IntegrityError(
            statement=None,
            params=None,
            orig=sqlite3.IntegrityError(
                "UNIQUE constraint failed: "
                "ranking_entries.ranking_snapshot_id, ranking_entries.rank"
            ),
        )

    monkeypatch.setattr(Session, "scalar", scalar_without_preflight)
    monkeypatch.setattr(Session, "commit", commit_with_sqlite_conflict)

    response = client.post(
        f"/ranking-snapshots/{ranking_snapshot.id}/entries",
        json={
            "rank": 2,
            "score": 987654,
            "player_name": "Test Player",
            "ocr_confidence": 0.95,
            "raw_text": "2 Test Player 987654",
            "image_path": "/tmp/test-player.png",
            "is_valid": True,
            "validation_issue": None,
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Rank already exists for this ranking snapshot"
    }
