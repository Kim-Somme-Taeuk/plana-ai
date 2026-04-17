from __future__ import annotations

import json

import pytest

from collector.mock_import import (
    ApiError,
    MockImportError,
    load_mock_payload,
    import_mock_payload,
)


class SnapshotAwareApiClientMixin:
    def list_seasons(self):
        return []

    def list_snapshots(self, season_id):
        return []

    def list_entries(self, snapshot_id):
        return []


def test_load_mock_payload_reads_expected_sections(tmp_path):
    mock_file = tmp_path / "sample.json"
    mock_file.write_text(
        json.dumps(
            {
                "season": {
                    "event_type": "raid",
                    "server": "kr",
                    "boss_name": "Binah",
                    "terrain": "outdoor",
                    "season_label": "collector-test-season",
                },
                "snapshot": {
                    "captured_at": "2026-04-16T10:00:00Z",
                },
                "entries": [
                    {
                        "rank": 1,
                        "score": 1000,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = load_mock_payload(mock_file)

    assert payload.season["season_label"] == "collector-test-season"
    assert payload.snapshot["captured_at"] == "2026-04-16T10:00:00Z"
    assert payload.entries[0]["rank"] == 1


def test_import_mock_payload_calls_api_in_order():
    class FakeApiClient(SnapshotAwareApiClientMixin):
        def __init__(self):
            self.calls: list[tuple[str, dict[str, object] | str]] = []

        def create_season(self, payload):
            self.calls.append(("create_season", payload))
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            self.calls.append(("create_snapshot", {"season_id": season_id, **payload}))
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            self.calls.append(("create_entry", {"snapshot_id": snapshot_id, **payload}))
            return {"id": len([call for call in self.calls if call[0] == "create_entry"])}

        def update_snapshot_status(self, snapshot_id, status):
            self.calls.append(
                ("update_snapshot_status", {"snapshot_id": snapshot_id, "status": status})
            )
            return {
                "id": 202,
                "status": status,
                "total_rows_collected": 2,
            }

    payload = load_mock_payload(
        "collector/mock_data/sample_invalid_entries_snapshot.json"
    )
    client = FakeApiClient()

    result = import_mock_payload(payload, client)

    assert result.season_id == 101
    assert result.snapshot_id == 202
    assert len(result.entry_ids) == 4
    assert result.status == "completed"
    assert result.total_rows_collected == 2
    assert [call[0] for call in client.calls] == [
        "create_season",
        "create_snapshot",
        "create_entry",
        "create_entry",
        "create_entry",
        "create_entry",
        "update_snapshot_status",
    ]


def test_import_mock_payload_reuses_existing_season_on_duplicate_label():
    class DuplicateSeasonClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            raise ApiError(409, "Season label already exists")

        def list_seasons(self):
            return [
                {
                    "id": 777,
                    "event_type": "total_assault",
                    "server": "kr",
                    "boss_name": "Binah",
                    "armor_type": "heavy",
                    "terrain": "outdoor",
                    "season_label": "mock-valid-season-20260416-a",
                    "started_at": "2026-04-16T09:00:00Z",
                    "ended_at": "2026-04-23T09:00:00Z",
                }
            ]

        def create_snapshot(self, season_id, payload):
            assert season_id == 777
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {
                "id": snapshot_id,
                "status": status,
                "total_rows_collected": 1,
            }

    payload = load_mock_payload(
        "collector/mock_data/sample_valid_snapshot.json"
    )

    result = import_mock_payload(payload, DuplicateSeasonClient())

    assert result.season_id == 777


def test_import_mock_payload_rejects_duplicate_season_with_mismatched_metadata():
    class MismatchedSeasonClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            raise ApiError(409, "Season label already exists")

        def list_seasons(self):
            return [
                {
                    "id": 888,
                    "event_type": "total_assault",
                    "server": "global",
                    "boss_name": "Binah",
                    "armor_type": "heavy",
                    "terrain": "outdoor",
                    "season_label": "mock-valid-season-20260416-a",
                    "started_at": "2026-04-16T09:00:00Z",
                    "ended_at": "2026-04-23T09:00:00Z",
                }
            ]

    payload = load_mock_payload("collector/mock_data/sample_valid_snapshot.json")

    with pytest.raises(MockImportError) as exc_info:
        import_mock_payload(payload, MismatchedSeasonClient())

    assert "기존 season을 재사용할 수 없습니다" in str(exc_info.value)
    assert "server" in str(exc_info.value)


def test_import_mock_payload_marks_snapshot_failed_when_entry_creation_fails():
    class EntryFailureClient(SnapshotAwareApiClientMixin):
        def __init__(self):
            self.calls: list[tuple[str, dict[str, object] | str]] = []

        def create_season(self, payload):
            self.calls.append(("create_season", payload))
            return {"id": 301, **payload}

        def create_snapshot(self, season_id, payload):
            self.calls.append(("create_snapshot", {"season_id": season_id, **payload}))
            return {"id": 401, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            self.calls.append(("create_entry", {"snapshot_id": snapshot_id, **payload}))
            raise ApiError(409, "Rank already exists for this ranking snapshot")

        def update_snapshot_status(self, snapshot_id, status):
            self.calls.append(
                ("update_snapshot_status", {"snapshot_id": snapshot_id, "status": status})
            )
            return {
                "id": snapshot_id,
                "status": status,
                "total_rows_collected": 0,
            }

    payload = load_mock_payload("collector/mock_data/sample_valid_snapshot.json")
    client = EntryFailureClient()

    with pytest.raises(MockImportError) as exc_info:
        import_mock_payload(payload, client)

    assert "ranking entry 생성에 실패했습니다" in str(exc_info.value)
    assert client.calls[-1] == (
        "update_snapshot_status",
        {"snapshot_id": 401, "status": "failed"},
    )


def test_import_mock_payload_marks_snapshot_failed_when_completion_fails():
    class CompletionFailureClient(SnapshotAwareApiClientMixin):
        def __init__(self):
            self.calls: list[tuple[str, dict[str, object] | str]] = []

        def create_season(self, payload):
            self.calls.append(("create_season", payload))
            return {"id": 501, **payload}

        def create_snapshot(self, season_id, payload):
            self.calls.append(("create_snapshot", {"season_id": season_id, **payload}))
            return {"id": 601, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            self.calls.append(("create_entry", {"snapshot_id": snapshot_id, **payload}))
            return {"id": len([call for call in self.calls if call[0] == "create_entry"])}

        def update_snapshot_status(self, snapshot_id, status):
            self.calls.append(
                ("update_snapshot_status", {"snapshot_id": snapshot_id, "status": status})
            )
            if status == "completed":
                raise ApiError(500, "temporary backend error")
            return {
                "id": snapshot_id,
                "status": status,
                "total_rows_collected": 0,
            }

    payload = load_mock_payload("collector/mock_data/sample_valid_snapshot.json")
    client = CompletionFailureClient()

    with pytest.raises(MockImportError) as exc_info:
        import_mock_payload(payload, client)

    assert "snapshot completed 처리에 실패했습니다" in str(exc_info.value)
    assert client.calls[-1] == (
        "update_snapshot_status",
        {"snapshot_id": 601, "status": "failed"},
    )


def test_load_mock_payload_rejects_duplicate_ranks(tmp_path):
    mock_file = tmp_path / "duplicate-rank.json"
    mock_file.write_text(
        json.dumps(
            {
                "season": {
                    "event_type": "raid",
                    "server": "kr",
                    "boss_name": "Binah",
                    "terrain": "outdoor",
                    "season_label": "collector-duplicate-rank-test",
                },
                "snapshot": {
                    "captured_at": "2026-04-16T10:00:00Z",
                },
                "entries": [
                    {"rank": 1, "score": 1000},
                    {"rank": 1, "score": 900},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(MockImportError) as exc_info:
        load_mock_payload(mock_file)

    assert "duplicate_rank" in str(exc_info.value)


def test_load_mock_payload_rejects_duplicate_integer_like_string_ranks(tmp_path):
    mock_file = tmp_path / "duplicate-string-rank.json"
    mock_file.write_text(
        json.dumps(
            {
                "season": {
                    "event_type": "raid",
                    "server": "kr",
                    "boss_name": "Binah",
                    "terrain": "outdoor",
                    "season_label": "collector-duplicate-string-rank-test",
                },
                "snapshot": {
                    "captured_at": "2026-04-16T10:00:00Z",
                },
                "entries": [
                    {"rank": "1", "score": 1000},
                    {"rank": 1.0, "score": 900},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(MockImportError) as exc_info:
        load_mock_payload(mock_file)

    assert "duplicate_rank" in str(exc_info.value)


def test_import_mock_payload_reuses_existing_completed_snapshot_and_entries():
    class ExistingCompletedSnapshotClient(SnapshotAwareApiClientMixin):
        def __init__(self):
            self.calls: list[tuple[str, object]] = []

        def create_season(self, payload):
            self.calls.append(("create_season", payload))
            return {"id": 101, **payload}

        def list_snapshots(self, season_id):
            self.calls.append(("list_snapshots", season_id))
            return [
                {
                    "id": 202,
                    "season_id": season_id,
                    "captured_at": "2026-04-16T10:15:00Z",
                    "source_type": "mock_json",
                    "status": "completed",
                    "note": "valid-only sample snapshot",
                    "total_rows_collected": 3,
                }
            ]

        def list_entries(self, snapshot_id):
            self.calls.append(("list_entries", snapshot_id))
            return [
                {
                    "id": 1,
                    "rank": 1,
                    "score": 12345678,
                    "player_name": "Plana",
                    "ocr_confidence": 0.99,
                    "raw_text": "1 Plana 12345678",
                    "image_path": "/mock/valid/plana.png",
                    "is_valid": True,
                    "validation_issue": None,
                },
                {
                    "id": 2,
                    "rank": 10,
                    "score": 11876543,
                    "player_name": "Arona",
                    "ocr_confidence": 0.97,
                    "raw_text": "10 Arona 11876543",
                    "image_path": "/mock/valid/arona.png",
                    "is_valid": True,
                    "validation_issue": None,
                },
                {
                    "id": 3,
                    "rank": 100,
                    "score": 10999999,
                    "player_name": "Sensei",
                    "ocr_confidence": 0.95,
                    "raw_text": "100 Sensei 10999999",
                    "image_path": "/mock/valid/sensei.png",
                    "is_valid": True,
                    "validation_issue": None,
                },
            ]

        def create_snapshot(self, season_id, payload):
            raise AssertionError("기존 completed snapshot을 재사용해야 합니다")

        def create_entry(self, snapshot_id, payload):
            raise AssertionError("기존 entry를 재사용해야 합니다")

        def update_snapshot_status(self, snapshot_id, status):
            raise AssertionError("이미 completed 상태라면 상태 변경이 없어야 합니다")

    payload = load_mock_payload("collector/mock_data/sample_valid_snapshot.json")

    result = import_mock_payload(payload, ExistingCompletedSnapshotClient())

    assert result.snapshot_id == 202
    assert result.entry_ids == [1, 2, 3]
    assert result.status == "completed"
    assert result.total_rows_collected == 3


def test_import_mock_payload_resumes_collecting_snapshot_with_missing_entries():
    class ExistingCollectingSnapshotClient(SnapshotAwareApiClientMixin):
        def __init__(self):
            self.calls: list[tuple[str, object]] = []

        def create_season(self, payload):
            self.calls.append(("create_season", payload))
            return {"id": 101, **payload}

        def list_snapshots(self, season_id):
            self.calls.append(("list_snapshots", season_id))
            return [
                {
                    "id": 303,
                    "season_id": season_id,
                    "captured_at": "2026-04-16T10:15:00Z",
                    "source_type": "mock_json",
                    "status": "collecting",
                    "note": "valid-only sample snapshot",
                }
            ]

        def list_entries(self, snapshot_id):
            self.calls.append(("list_entries", snapshot_id))
            return [
                {
                    "id": 1,
                    "rank": 1,
                    "score": 12345678,
                    "player_name": "Plana",
                    "ocr_confidence": 0.99,
                    "raw_text": "1 Plana 12345678",
                    "image_path": "/mock/valid/plana.png",
                    "is_valid": True,
                    "validation_issue": None,
                }
            ]

        def create_snapshot(self, season_id, payload):
            raise AssertionError("기존 collecting snapshot을 재사용해야 합니다")

        def create_entry(self, snapshot_id, payload):
            self.calls.append(("create_entry", {"snapshot_id": snapshot_id, **payload}))
            return {
                "id": 10 if payload["rank"] == 10 else 11,
                **payload,
            }

        def update_snapshot_status(self, snapshot_id, status):
            self.calls.append(
                ("update_snapshot_status", {"snapshot_id": snapshot_id, "status": status})
            )
            return {
                "id": snapshot_id,
                "status": status,
                "total_rows_collected": 3,
            }

    payload = load_mock_payload("collector/mock_data/sample_valid_snapshot.json")

    result = import_mock_payload(payload, ExistingCollectingSnapshotClient())

    assert result.snapshot_id == 303
    assert result.entry_ids == [1, 10, 11]
    assert result.status == "completed"
    assert result.total_rows_collected == 3


def test_import_mock_payload_rejects_conflicting_existing_entry():
    class ConflictingEntryClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def list_snapshots(self, season_id):
            return [
                {
                    "id": 404,
                    "season_id": season_id,
                    "captured_at": "2026-04-16T10:15:00Z",
                    "source_type": "mock_json",
                    "status": "completed",
                    "note": "valid-only sample snapshot",
                    "total_rows_collected": 3,
                }
            ]

        def list_entries(self, snapshot_id):
            return [
                {
                    "id": 1,
                    "rank": 1,
                    "score": 1,
                    "player_name": "Plana",
                    "ocr_confidence": 0.99,
                    "raw_text": "1 Plana 12345678",
                    "image_path": "/mock/valid/plana.png",
                    "is_valid": True,
                    "validation_issue": None,
                }
            ]

    payload = load_mock_payload("collector/mock_data/sample_valid_snapshot.json")

    with pytest.raises(MockImportError) as exc_info:
        import_mock_payload(payload, ConflictingEntryClient())

    assert "기존 snapshot entry와 충돌합니다" in str(exc_info.value)
    assert "snapshot_id=404" in str(exc_info.value)


def test_import_mock_payload_rejects_completed_snapshot_with_missing_entries():
    class MissingCompletedEntryClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def list_snapshots(self, season_id):
            return [
                {
                    "id": 505,
                    "season_id": season_id,
                    "captured_at": "2026-04-16T10:15:00Z",
                    "source_type": "mock_json",
                    "status": "completed",
                    "note": "valid-only sample snapshot",
                    "total_rows_collected": 1,
                }
            ]

        def list_entries(self, snapshot_id):
            return [
                {
                    "id": 1,
                    "rank": 1,
                    "score": 12345678,
                    "player_name": "Plana",
                    "ocr_confidence": 0.99,
                    "raw_text": "1 Plana 12345678",
                    "image_path": "/mock/valid/plana.png",
                    "is_valid": True,
                    "validation_issue": None,
                }
            ]

    payload = load_mock_payload("collector/mock_data/sample_valid_snapshot.json")

    with pytest.raises(MockImportError) as exc_info:
        import_mock_payload(payload, MissingCompletedEntryClient())

    assert "기존 snapshot이 collecting 상태가 아니라" in str(exc_info.value)
    assert "snapshot_id=505" in str(exc_info.value)
