from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

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
    ) -> dict[str, Any]:
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

    try:
        season = client.create_season(_build_season_payload(payload.season))
    except ApiError as exc:
        raise MockImportError(
            "season 생성에 실패했습니다. "
            f"status={exc.status_code}, detail={exc.detail}. "
            "같은 season_label이 이미 존재하면 기본 동작은 실패입니다."
        ) from exc

    try:
        snapshot = client.create_snapshot(
            season["id"],
            _build_snapshot_payload(payload.snapshot),
        )
        snapshot_id = snapshot["id"]
    except ApiError as exc:
        raise MockImportError(
            f"snapshot 생성에 실패했습니다. status={exc.status_code}, detail={exc.detail}"
        ) from exc

    entry_ids: list[int] = []
    for index, entry in enumerate(payload.entries, start=1):
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
