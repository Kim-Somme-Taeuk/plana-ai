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
