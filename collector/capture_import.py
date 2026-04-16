from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.ranking_entry_validation import (
    ValidationIssueCode,
    summarize_snapshot_entries,
)
from collector.mock_import import (
    ApiClient,
    DEFAULT_API_BASE_URL,
    ImportResult,
    MockImportError,
    MockImportPayload,
    SEASON_REQUIRED_FIELDS,
    SNAPSHOT_REQUIRED_FIELDS,
    import_mock_payload,
)

CAPTURE_SOURCE_TYPE = "image_sidecar"


@dataclass(frozen=True)
class CapturePage:
    image_path: str
    ocr_text_path: str | None
    default_ocr_confidence: float | None


@dataclass(frozen=True)
class CaptureImportPayload:
    base_dir: Path
    season: dict[str, Any]
    snapshot: dict[str, Any]
    pages: list[CapturePage]


def load_capture_import_payload(path: str | Path) -> CaptureImportPayload:
    manifest_path = _resolve_manifest_path(path)

    try:
        raw_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MockImportError(f"Capture manifest를 찾을 수 없습니다: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise MockImportError(
            f"Capture manifest JSON 파싱에 실패했습니다: {manifest_path} ({exc})"
        ) from exc

    root = _require_mapping(raw_payload, "root")
    season = _require_mapping(root.get("season"), "season")
    snapshot = _require_mapping(root.get("snapshot"), "snapshot")
    pages = root.get("pages")
    if not isinstance(pages, list) or not pages:
        raise MockImportError("pages는 비어 있지 않은 배열이어야 합니다.")

    _require_fields(season, SEASON_REQUIRED_FIELDS, "season")
    _require_fields(snapshot, SNAPSHOT_REQUIRED_FIELDS, "snapshot")

    capture_pages = [
        _build_capture_page(page, index, manifest_path.parent)
        for index, page in enumerate(pages, start=1)
    ]

    return CaptureImportPayload(
        base_dir=manifest_path.parent,
        season=season,
        snapshot={
            **snapshot,
            "source_type": snapshot.get("source_type", CAPTURE_SOURCE_TYPE),
        },
        pages=capture_pages,
    )


def build_mock_payload_from_capture(
    payload: CaptureImportPayload,
) -> MockImportPayload:
    entries: list[dict[str, Any]] = []

    for page_index, page in enumerate(payload.pages, start=1):
        image_path = _resolve_existing_path(payload.base_dir, page.image_path, "image_path")
        text_path = _resolve_ocr_text_path(payload.base_dir, page)
        ocr_text = text_path.read_text(encoding="utf-8")

        page_entries = _parse_page_entries(
            ocr_text=ocr_text,
            image_path=image_path,
            default_ocr_confidence=page.default_ocr_confidence,
            page_index=page_index,
        )
        entries.extend(page_entries)

    _validate_snapshot_entries(entries)

    return MockImportPayload(
        season=payload.season,
        snapshot=payload.snapshot,
        entries=entries,
    )


def import_capture_payload(
    payload: CaptureImportPayload,
    client: ApiClient,
) -> ImportResult:
    return import_mock_payload(build_mock_payload_from_capture(payload), client)


def _resolve_manifest_path(path: str | Path) -> Path:
    path_obj = Path(path)
    if path_obj.is_dir():
        return path_obj / "manifest.json"
    return path_obj


def _build_capture_page(
    raw_page: object,
    page_index: int,
    base_dir: Path,
) -> CapturePage:
    page = _require_mapping(raw_page, f"pages[{page_index}]")
    image_path = page.get("image_path")
    if not isinstance(image_path, str) or not image_path.strip():
        raise MockImportError(f"pages[{page_index}].image_path는 문자열이어야 합니다.")

    _resolve_existing_path(base_dir, image_path, "image_path")

    ocr_text_path = page.get("ocr_text_path")
    if ocr_text_path is not None and (
        not isinstance(ocr_text_path, str) or not ocr_text_path.strip()
    ):
        raise MockImportError(
            f"pages[{page_index}].ocr_text_path는 문자열이어야 합니다."
        )

    default_ocr_confidence = page.get("default_ocr_confidence")
    if default_ocr_confidence is not None:
        try:
            default_ocr_confidence = float(default_ocr_confidence)
        except (TypeError, ValueError) as exc:
            raise MockImportError(
                f"pages[{page_index}].default_ocr_confidence는 숫자여야 합니다."
            ) from exc

    return CapturePage(
        image_path=image_path,
        ocr_text_path=ocr_text_path,
        default_ocr_confidence=default_ocr_confidence,
    )


def _resolve_existing_path(base_dir: Path, value: str, label: str) -> Path:
    resolved_path = (base_dir / value).resolve()
    if not resolved_path.exists():
        raise MockImportError(f"{label} 파일을 찾을 수 없습니다: {resolved_path}")
    return resolved_path


def _resolve_ocr_text_path(base_dir: Path, page: CapturePage) -> Path:
    if page.ocr_text_path is not None:
        return _resolve_existing_path(base_dir, page.ocr_text_path, "ocr_text_path")

    image_path = (base_dir / page.image_path).resolve()
    inferred_path = image_path.with_suffix(".txt")
    if not inferred_path.exists():
        raise MockImportError(
            "ocr_text_path가 없고 기본 OCR sidecar(.txt)도 찾을 수 없습니다: "
            f"{inferred_path}"
        )
    return inferred_path


def _parse_page_entries(
    *,
    ocr_text: str,
    image_path: Path,
    default_ocr_confidence: float | None,
    page_index: int,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    for line_index, raw_line in enumerate(ocr_text.splitlines(), start=1):
        if not raw_line.strip():
            continue

        entry = _parse_ocr_line(
            raw_line=raw_line,
            image_path=image_path,
            default_ocr_confidence=default_ocr_confidence,
            page_index=page_index,
            line_index=line_index,
        )
        entries.append(entry)

    if not entries:
        raise MockImportError(
            f"page {page_index}에서 파싱 가능한 OCR entry가 없습니다: {image_path}"
        )

    return entries


def _parse_ocr_line(
    *,
    raw_line: str,
    image_path: Path,
    default_ocr_confidence: float | None,
    page_index: int,
    line_index: int,
) -> dict[str, Any]:
    tab_parts = raw_line.split("\t")
    if len(tab_parts) in (3, 4):
        rank_text, player_name, score_text, *confidence_text = tab_parts
        ocr_confidence = (
            _parse_float_token(confidence_text[0], "ocr_confidence", page_index, line_index)
            if confidence_text
            else default_ocr_confidence
        )
        return {
            "rank": _parse_int_token(rank_text, "rank", page_index, line_index),
            "score": _parse_int_token(score_text, "score", page_index, line_index),
            "player_name": player_name,
            "ocr_confidence": ocr_confidence,
            "raw_text": raw_line,
            "image_path": _build_entry_image_path(image_path),
            "is_valid": True,
            "validation_issue": None,
        }

    return _parse_whitespace_fallback_line(
        raw_line=raw_line,
        image_path=image_path,
        default_ocr_confidence=default_ocr_confidence,
        page_index=page_index,
        line_index=line_index,
    )


def _parse_int_token(
    value: str,
    label: str,
    page_index: int,
    line_index: int,
) -> int:
    normalized = value.replace(",", "").strip()
    try:
        return int(normalized)
    except ValueError as exc:
        raise MockImportError(
            f"{label} 파싱에 실패했습니다. page={page_index}, line={line_index}, value={value!r}"
        ) from exc


def _parse_float_token(
    value: str,
    label: str,
    page_index: int,
    line_index: int,
) -> float:
    try:
        return float(value.strip())
    except ValueError as exc:
        raise MockImportError(
            f"{label} 파싱에 실패했습니다. page={page_index}, line={line_index}, value={value!r}"
        ) from exc


def _parse_whitespace_fallback_line(
    *,
    raw_line: str,
    image_path: Path,
    default_ocr_confidence: float | None,
    page_index: int,
    line_index: int,
) -> dict[str, Any]:
    tokens = raw_line.split()
    if len(tokens) < 3:
        raise MockImportError(
            "OCR line 파싱에 실패했습니다. "
            f"page={page_index}, line={line_index}, raw_text={raw_line!r}"
        )

    rank = _parse_int_token(tokens[0], "rank", page_index, line_index)
    ocr_confidence: float | None = default_ocr_confidence

    if len(tokens) >= 4 and _looks_like_confidence_token(tokens[-1]):
        score_index = -2
        player_tokens = tokens[1:-2]
        ocr_confidence = _parse_float_token(
            tokens[-1], "ocr_confidence", page_index, line_index
        )
    else:
        score_index = -1
        player_tokens = tokens[1:-1]

    if not player_tokens:
        raise MockImportError(
            "OCR line 파싱에 실패했습니다. "
            f"page={page_index}, line={line_index}, raw_text={raw_line!r}"
        )

    return {
        "rank": rank,
        "score": _parse_int_token(tokens[score_index], "score", page_index, line_index),
        "player_name": " ".join(player_tokens),
        "ocr_confidence": ocr_confidence,
        "raw_text": raw_line,
        "image_path": _build_entry_image_path(image_path),
        "is_valid": True,
        "validation_issue": None,
    }


def _looks_like_confidence_token(value: str) -> bool:
    stripped = value.strip()
    if "." not in stripped:
        return False

    try:
        parsed = float(stripped)
    except ValueError:
        return False

    return 0 <= parsed <= 1


def _validate_snapshot_entries(entries: list[dict[str, Any]]) -> None:
    summary = summarize_snapshot_entries(entries)

    if summary.duplicate_ranks:
        joined_ranks = ", ".join(str(rank) for rank in summary.duplicate_ranks)
        raise MockImportError(
            "capture entries 사전 검증에 실패했습니다. "
            f"validation_issue={ValidationIssueCode.DUPLICATE_RANK.value}, "
            f"duplicate_ranks={joined_ranks}"
        )

    if summary.has_rank_order_violation:
        print(
            "경고: capture entries 순서에서 "
            f"{ValidationIssueCode.RANK_ORDER_VIOLATION.value} 징후를 감지했습니다. "
            "입력은 계속 진행합니다.",
            file=sys.stderr,
        )


def _build_entry_image_path(image_path: Path) -> str:
    try:
        return str(image_path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(image_path)


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="이미지 기반 capture manifest를 backend API로 주입합니다.",
    )
    parser.add_argument(
        "capture_path",
        help="capture manifest.json 또는 이를 포함한 디렉터리 경로",
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
        payload = load_capture_import_payload(args.capture_path)
        mock_payload = build_mock_payload_from_capture(payload)
        result = import_mock_payload(mock_payload, ApiClient(args.base_url))
    except MockImportError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "season_id": result.season_id,
                "snapshot_id": result.snapshot_id,
                "page_count": len(payload.pages),
                "entry_count": len(mock_payload.entries),
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
