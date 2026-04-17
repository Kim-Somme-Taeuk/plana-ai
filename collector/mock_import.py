from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.ranking_entry_validation import (
    ValidationIssueCode,
    summarize_snapshot_entries,
    validate_ranking_entry,
)

DEFAULT_API_BASE_URL = "http://localhost:8000"
SEASON_REQUIRED_FIELDS = (
    "event_type",
    "server",
    "boss_name",
    "terrain",
    "season_label",
)
SNAPSHOT_REQUIRED_FIELDS = ("captured_at",)
ENTRY_REQUIRED_FIELDS = ("rank", "score")


class MockImportError(RuntimeError):
    pass


class ApiError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"API request failed with status {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class MockImportPayload:
    season: dict[str, Any]
    snapshot: dict[str, Any]
    entries: list[dict[str, Any]]


@dataclass(frozen=True)
class ImportResult:
    season_id: int
    snapshot_id: int
    entry_ids: list[int]
    status: str
    total_rows_collected: int | None


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def list_seasons(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/seasons")
        if not isinstance(response, list):
            raise MockImportError("GET /seasons 응답 형식이 예상과 다릅니다.")
        return response

    def create_season(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/seasons", payload)

    def create_snapshot(
        self,
        season_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/seasons/{season_id}/ranking-snapshots",
            payload,
        )

    def list_snapshots(self, season_id: int) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/seasons/{season_id}/ranking-snapshots",
        )
        if not isinstance(response, list):
            raise MockImportError(
                "GET /seasons/{season_id}/ranking-snapshots 응답 형식이 예상과 다릅니다."
            )
        return response

    def create_entry(
        self,
        snapshot_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/ranking-snapshots/{snapshot_id}/entries",
            payload,
        )

    def list_entries(self, snapshot_id: int) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/ranking-snapshots/{snapshot_id}/entries",
        )
        if not isinstance(response, list):
            raise MockImportError(
                "GET /ranking-snapshots/{snapshot_id}/entries 응답 형식이 예상과 다릅니다."
            )
        return response

    def update_snapshot_status(
        self,
        snapshot_id: int,
        status: str,
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/ranking-snapshots/{snapshot_id}/status",
            {"status": status},
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = None
        headers = {
            "Accept": "application/json",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with request.urlopen(req, timeout=15) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return {}
                return json.loads(raw)
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8")
            detail = _extract_error_detail(response_body) or exc.reason
            raise ApiError(exc.code, detail) from exc
        except error.URLError as exc:
            raise MockImportError(
                f"API 서버에 연결하지 못했습니다: {self.base_url}"
            ) from exc


def _mark_snapshot_failed(
    client: ApiClient,
    snapshot_id: int,
) -> str | None:
    try:
        client.update_snapshot_status(snapshot_id, "failed")
    except ApiError as exc:
        return f"snapshot failed 처리도 실패했습니다. status={exc.status_code}, detail={exc.detail}"
    return None


def load_mock_payload(path: str | Path) -> MockImportPayload:
    payload_path = Path(path)
    try:
        raw_payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MockImportError(f"Mock 파일을 찾을 수 없습니다: {payload_path}") from exc
    except json.JSONDecodeError as exc:
        raise MockImportError(
            f"Mock JSON 파싱에 실패했습니다: {payload_path} ({exc})"
        ) from exc

    root = _require_mapping(raw_payload, "root")
    season = _require_mapping(root.get("season"), "season")
    snapshot = _require_mapping(root.get("snapshot"), "snapshot")
    entries = root.get("entries")
    if not isinstance(entries, list):
        raise MockImportError("entries는 배열이어야 합니다.")

    _require_fields(season, SEASON_REQUIRED_FIELDS, "season")
    _require_fields(snapshot, SNAPSHOT_REQUIRED_FIELDS, "snapshot")

    for index, entry in enumerate(entries, start=1):
        entry_mapping = _require_mapping(entry, f"entries[{index}]")
        _require_fields(entry_mapping, ENTRY_REQUIRED_FIELDS, f"entries[{index}]")

    _validate_snapshot_entries(entries)

    return MockImportPayload(
        season=season,
        snapshot=snapshot,
        entries=entries,
    )


def import_mock_payload(
    payload: MockImportPayload,
    client: ApiClient,
) -> ImportResult:
    snapshot_id: int | None = None

    season = _resolve_or_create_season(
        client=client,
        payload=_build_season_payload(payload.season),
    )
    expected_snapshot_payload = _build_snapshot_payload(payload.snapshot)

    snapshot = _resolve_or_create_snapshot(
        client=client,
        season_id=season["id"],
        payload=expected_snapshot_payload,
    )
    snapshot_id = snapshot["id"]
    existing_entries_by_rank = _get_existing_entries_by_rank(
        client=client,
        snapshot=snapshot,
    )

    entry_ids: list[int] = []
    for index, entry in enumerate(payload.entries, start=1):
        existing_entry = existing_entries_by_rank.get(int(entry["rank"]))
        if existing_entry is not None:
            expected_entry_state = _build_expected_entry_state(entry)
            if not _entry_matches_expected(existing_entry, expected_entry_state):
                raise MockImportError(
                    "기존 snapshot entry와 충돌합니다. "
                    f"snapshot_id={snapshot['id']}, rank={entry['rank']}"
                )
            entry_ids.append(existing_entry["id"])
            continue

        if snapshot["status"] != "collecting":
            raise MockImportError(
                "기존 snapshot이 collecting 상태가 아니라 누락된 entry를 이어서 넣을 수 없습니다. "
                f"snapshot_id={snapshot['id']}, status={snapshot['status']}"
            )

        try:
            created_entry = client.create_entry(
                snapshot["id"],
                _build_entry_payload(entry),
            )
        except ApiError as exc:
            failed_transition_error = _mark_snapshot_failed(client, snapshot_id)
            raise MockImportError(
                "ranking entry 생성에 실패했습니다. "
                f"entry_index={index}, status={exc.status_code}, detail={exc.detail}"
                + (
                    f" {failed_transition_error}"
                    if failed_transition_error is not None
                    else ""
                )
            ) from exc
        entry_ids.append(created_entry["id"])
        existing_entries_by_rank[int(entry["rank"])] = created_entry

    if snapshot["status"] == "completed":
        return ImportResult(
            season_id=season["id"],
            snapshot_id=snapshot["id"],
            entry_ids=entry_ids,
            status=snapshot["status"],
            total_rows_collected=snapshot.get("total_rows_collected"),
        )

    try:
        completed_snapshot = client.update_snapshot_status(snapshot["id"], "completed")
    except ApiError as exc:
        failed_transition_error = _mark_snapshot_failed(client, snapshot_id)
        raise MockImportError(
            "snapshot completed 처리에 실패했습니다. "
            f"status={exc.status_code}, detail={exc.detail}"
            + (
                f" {failed_transition_error}"
                if failed_transition_error is not None
                else ""
            )
        ) from exc

    return ImportResult(
        season_id=season["id"],
        snapshot_id=completed_snapshot["id"],
        entry_ids=entry_ids,
        status=completed_snapshot["status"],
        total_rows_collected=completed_snapshot.get("total_rows_collected"),
    )


def _resolve_or_create_snapshot(
    *,
    client: ApiClient,
    season_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    existing_snapshot = _find_existing_snapshot(
        client=client,
        season_id=season_id,
        payload=payload,
    )
    if existing_snapshot is not None:
        return existing_snapshot

    try:
        return client.create_snapshot(season_id, payload)
    except ApiError as exc:
        raise MockImportError(
            f"snapshot 생성에 실패했습니다. status={exc.status_code}, detail={exc.detail}"
        ) from exc


def _find_existing_snapshot(
    *,
    client: ApiClient,
    season_id: int,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        snapshots = client.list_snapshots(season_id)
    except ApiError as exc:
        raise MockImportError(
            "기존 snapshot 조회에 실패했습니다. "
            f"status={exc.status_code}, detail={exc.detail}"
        ) from exc

    expected_captured_at = _normalize_optional_datetime(payload.get("captured_at"))
    expected_source_type = payload.get("source_type")
    expected_note = payload.get("note")

    for snapshot in snapshots:
        if (
            _normalize_optional_datetime(snapshot.get("captured_at"))
            != expected_captured_at
        ):
            continue
        if snapshot.get("source_type") != expected_source_type:
            continue
        if snapshot.get("note") != expected_note:
            continue
        if snapshot.get("status") not in {"collecting", "completed"}:
            continue
        return snapshot

    return None


def _get_existing_entries_by_rank(
    *,
    client: ApiClient,
    snapshot: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    try:
        entries = client.list_entries(snapshot["id"])
    except ApiError as exc:
        raise MockImportError(
            "기존 snapshot entry 조회에 실패했습니다. "
            f"snapshot_id={snapshot['id']}, status={exc.status_code}, detail={exc.detail}"
        ) from exc

    entries_by_rank: dict[int, dict[str, Any]] = {}
    for entry in entries:
        rank = entry.get("rank")
        if isinstance(rank, int):
            entries_by_rank[rank] = entry
    return entries_by_rank


def _resolve_or_create_season(
    *,
    client: ApiClient,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        return client.create_season(payload)
    except ApiError as exc:
        if exc.status_code != 409:
            raise MockImportError(
                "season 생성에 실패했습니다. "
                f"status={exc.status_code}, detail={exc.detail}"
            ) from exc

    existing_season = _find_existing_season_by_label(
        client=client,
        season_label=payload["season_label"],
    )
    if existing_season is None:
        raise MockImportError(
            "season_label 중복이 감지됐지만 기존 season을 찾지 못했습니다. "
            f"season_label={payload['season_label']}"
        )

    mismatched_fields = _collect_season_mismatched_fields(
        expected=payload,
        actual=existing_season,
    )
    if mismatched_fields:
        joined_fields = ", ".join(mismatched_fields)
        raise MockImportError(
            "기존 season을 재사용할 수 없습니다. "
            f"season_label={payload['season_label']}, mismatched_fields={joined_fields}"
        )

    return existing_season


def _find_existing_season_by_label(
    *,
    client: ApiClient,
    season_label: str,
) -> dict[str, Any] | None:
    try:
        seasons = client.list_seasons()
    except ApiError as exc:
        raise MockImportError(
            "기존 season 조회에 실패했습니다. "
            f"status={exc.status_code}, detail={exc.detail}"
        ) from exc

    for season in seasons:
        if season.get("season_label") == season_label:
            return season
    return None


def _collect_season_mismatched_fields(
    *,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[str]:
    mismatched_fields: list[str] = []

    for field_name in (
        "event_type",
        "server",
        "boss_name",
        "armor_type",
        "terrain",
        "season_label",
    ):
        if actual.get(field_name) != expected.get(field_name):
            mismatched_fields.append(field_name)

    for field_name in ("started_at", "ended_at"):
        expected_value = _normalize_optional_datetime(expected.get(field_name))
        actual_value = _normalize_optional_datetime(actual.get(field_name))
        if expected_value != actual_value:
            mismatched_fields.append(field_name)

    return mismatched_fields


def _normalize_optional_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            return datetime.fromisoformat(normalized).isoformat()
        except ValueError:
            return normalized
    return str(value)


def _build_season_payload(season: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": season["event_type"],
        "server": season["server"],
        "boss_name": season["boss_name"],
        "armor_type": season.get("armor_type"),
        "terrain": season["terrain"],
        "season_label": season["season_label"],
        "started_at": season.get("started_at"),
        "ended_at": season.get("ended_at"),
    }


def _build_snapshot_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "captured_at": snapshot["captured_at"],
        "source_type": snapshot.get("source_type", "mock_json"),
        "status": "collecting",
        "note": snapshot.get("note"),
    }


def _build_entry_payload(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": entry["rank"],
        "score": entry["score"],
        "player_name": entry.get("player_name"),
        "ocr_confidence": entry.get("ocr_confidence"),
        "raw_text": entry.get("raw_text"),
        "image_path": entry.get("image_path"),
        "is_valid": entry.get("is_valid", True),
        "validation_issue": entry.get("validation_issue"),
    }


def _build_expected_entry_state(entry: dict[str, Any]) -> dict[str, Any]:
    payload = _build_entry_payload(entry)
    validation = validate_ranking_entry(
        rank=payload["rank"],
        score=payload["score"],
        player_name=payload.get("player_name"),
        ocr_confidence=payload.get("ocr_confidence"),
    )
    payload["is_valid"] = validation.is_valid
    payload["validation_issue"] = validation.validation_issue
    return payload


def _entry_matches_expected(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    for field_name in (
        "rank",
        "score",
        "player_name",
        "ocr_confidence",
        "raw_text",
        "image_path",
        "is_valid",
        "validation_issue",
    ):
        if actual.get(field_name) != expected.get(field_name):
            return False
    return True


def _validate_snapshot_entries(entries: list[dict[str, Any]]) -> None:
    summary = summarize_snapshot_entries(entries)

    if summary.duplicate_ranks:
        joined_ranks = ", ".join(str(rank) for rank in summary.duplicate_ranks)
        raise MockImportError(
            "entries 사전 검증에 실패했습니다. "
            f"validation_issue={ValidationIssueCode.DUPLICATE_RANK.value}, "
            f"duplicate_ranks={joined_ranks}"
        )

    if summary.has_rank_order_violation:
        print(
            "경고: entries 순서에서 "
            f"{ValidationIssueCode.RANK_ORDER_VIOLATION.value} 징후를 감지했습니다. "
            "입력은 계속 진행합니다.",
            file=sys.stderr,
        )


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MockImportError(f"{label}는 객체여야 합니다.")
    return value


def _require_fields(
    value: dict[str, Any],
    required_fields: tuple[str, ...],
    label: str,
) -> None:
    missing_fields = [
        field_name
        for field_name in required_fields
        if value.get(field_name) is None
    ]
    if missing_fields:
        joined = ", ".join(missing_fields)
        raise MockImportError(f"{label}에 필수 필드가 없습니다: {joined}")


def _extract_error_detail(response_body: str) -> str | None:
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError:
        return response_body or None

    detail = payload.get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:
        first = detail[0]
        if isinstance(first, dict) and "msg" in first:
            return str(first["msg"])
    return response_body or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="JSON mock 데이터를 backend API로 주입합니다.",
    )
    parser.add_argument(
        "mock_file",
        help="mock JSON 파일 경로",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("PLANA_AI_API_BASE_URL", DEFAULT_API_BASE_URL),
        help=(
            "backend API base URL "
            f"(default: {DEFAULT_API_BASE_URL}, env: PLANA_AI_API_BASE_URL)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        payload = load_mock_payload(args.mock_file)
        result = import_mock_payload(payload, ApiClient(args.base_url))
    except MockImportError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "season_id": result.season_id,
                "snapshot_id": result.snapshot_id,
                "entry_count": len(result.entry_ids),
                "entry_ids": result.entry_ids,
                "status": result.status,
                "total_rows_collected": result.total_rows_collected,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
