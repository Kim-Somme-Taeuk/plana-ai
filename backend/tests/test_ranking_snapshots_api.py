from sqlalchemy.orm import Session

from app.models.ranking_entry import RankingEntry
from app.models.ranking_snapshot import RankingSnapshot


def test_create_ranking_snapshot(client, ranking_snapshot: RankingSnapshot) -> None:
    response = client.get(f"/ranking-snapshots/{ranking_snapshot.id}")

    assert response.status_code == 200
    assert response.json()["id"] == ranking_snapshot.id
    assert response.json()["status"] == "collecting"


def test_update_ranking_snapshot_status_to_completed_counts_entries(
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
        ]
    )
    db_session.commit()

    response = client.patch(
        f"/ranking-snapshots/{ranking_snapshot.id}/status",
        json={"status": "completed"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["total_rows_collected"] == 2


def test_update_ranking_snapshot_status_to_failed_keeps_total_rows_collected(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    ranking_snapshot.total_rows_collected = 9
    db_session.add(ranking_snapshot)
    db_session.commit()

    response = client.patch(
        f"/ranking-snapshots/{ranking_snapshot.id}/status",
        json={"status": "failed"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["total_rows_collected"] == 9


def test_update_ranking_snapshot_status_rejects_completed_to_collecting(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    ranking_snapshot.status = "completed"
    db_session.add(ranking_snapshot)
    db_session.commit()

    response = client.patch(
        f"/ranking-snapshots/{ranking_snapshot.id}/status",
        json={"status": "collecting"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Invalid status transition from completed to collecting"
    }


def test_update_ranking_snapshot_status_rejects_failed_to_collecting(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    ranking_snapshot.status = "failed"
    db_session.add(ranking_snapshot)
    db_session.commit()

    response = client.patch(
        f"/ranking-snapshots/{ranking_snapshot.id}/status",
        json={"status": "collecting"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Invalid status transition from failed to collecting"
    }


def test_update_ranking_snapshot_status_rejects_completed_to_failed(
    client,
    db_session: Session,
    ranking_snapshot: RankingSnapshot,
) -> None:
    ranking_snapshot.status = "completed"
    db_session.add(ranking_snapshot)
    db_session.commit()

    response = client.patch(
        f"/ranking-snapshots/{ranking_snapshot.id}/status",
        json={"status": "failed"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Invalid status transition from completed to failed"
    }


def test_update_ranking_snapshot_status_returns_404_for_missing_snapshot(
    client,
) -> None:
    response = client.patch(
        "/ranking-snapshots/999999/status",
        json={"status": "completed"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Ranking snapshot not found"}


def test_create_and_list_ranking_snapshots_still_work(
    client,
    ranking_snapshot: RankingSnapshot,
) -> None:
    get_response = client.get(f"/ranking-snapshots/{ranking_snapshot.id}")
    list_response = client.get(
        f"/seasons/{ranking_snapshot.season_id}/ranking-snapshots"
    )

    assert get_response.status_code == 200
    assert get_response.json()["id"] == ranking_snapshot.id
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == ranking_snapshot.id
