from __future__ import annotations

import json

import pytest

from collector.mock_import import (
    ApiError,
    MockImportError,
    load_mock_payload,
    import_mock_payload,
)


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
    class FakeApiClient:
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


def test_import_mock_payload_stops_on_duplicate_season():
    class DuplicateSeasonClient:
        def create_season(self, payload):
            raise ApiError(409, "Season label already exists")

    payload = load_mock_payload(
        "collector/mock_data/sample_valid_snapshot.json"
    )

    with pytest.raises(MockImportError) as exc_info:
        import_mock_payload(payload, DuplicateSeasonClient())

    assert "season 생성에 실패했습니다" in str(exc_info.value)
    assert "season_label" in str(exc_info.value)


def test_import_mock_payload_marks_snapshot_failed_when_entry_creation_fails():
    class EntryFailureClient:
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
    class CompletionFailureClient:
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
