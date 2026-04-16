from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
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

OCR_PROVIDER_SIDECAR = "sidecar"
OCR_PROVIDER_TESSERACT = "tesseract"
CAPTURE_SOURCE_TYPE_BY_PROVIDER = {
    OCR_PROVIDER_SIDECAR: "image_sidecar",
    OCR_PROVIDER_TESSERACT: "image_tesseract",
}
DEFAULT_TESSERACT_COMMAND = "tesseract"
OCR_NUMERIC_TRANSLATION = str.maketrans(
    {
        "O": "0",
        "o": "0",
        "Q": "0",
        "D": "0",
        "I": "1",
        "l": "1",
        "|": "1",
        "B": "8",
        "，": ",",
        "．": ".",
        "％": "%",
    }
)
OCR_SEPARATOR_CHARACTERS = frozenset("-_=|:;.,·~")
OCR_EDGE_PUNCTUATION = "[](){}<>\"'“”‘’"
PLAYER_NAME_EDGE_PUNCTUATION = "[](){}<>\"'“”‘’「」『』【】"
SCORE_SUFFIX_TOKENS = frozenset({"점", "pt", "pts"})
ZERO_WIDTH_CHARACTERS_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
PAGINATION_RE = re.compile(
    r"^(?:page\s*)?\d+\s*(?:/|of)\s*\d+$",
    re.IGNORECASE,
)
STRUCTURED_COLUMN_SEPARATOR_RE = re.compile(r"\s*[|¦｜]\s*")
COLLECTOR_SUMMARY_PREFIX = "collector: "
COLLECTOR_JSON_PREFIX = "collector_json: "
STALE_LAST_PAGE_NEW_RANK_RATIO_THRESHOLD = 0.25
STALE_LAST_PAGE_MIN_ENTRY_COUNT = 4


@dataclass(frozen=True)
class CapturePage:
    image_path: str
    ocr_text_path: str | None
    default_ocr_confidence: float | None


@dataclass(frozen=True)
class OcrConfig:
    provider: str
    command: str | None
    language: str | None
    psm: int | None


@dataclass(frozen=True)
class CaptureImportPayload:
    base_dir: Path
    season: dict[str, Any]
    snapshot: dict[str, Any]
    pages: list[CapturePage]
    ocr: OcrConfig
    capture: dict[str, Any] | None


@dataclass(frozen=True)
class IgnoredOcrLine:
    page_index: int
    line_index: int
    raw_text: str
    reason: str


@dataclass(frozen=True)
class ParsedCapturePayload:
    mock_payload: MockImportPayload
    ignored_lines: list[IgnoredOcrLine]
    page_summaries: list[dict[str, Any]]


def load_capture_import_payload(
    path: str | Path,
    *,
    ocr_provider: str | None = None,
    ocr_command: str | None = None,
    ocr_language: str | None = None,
    ocr_psm: int | None = None,
) -> CaptureImportPayload:
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

    ocr_config = _build_ocr_config(
        root.get("ocr"),
        provider_override=ocr_provider,
        command_override=ocr_command,
        language_override=ocr_language,
        psm_override=ocr_psm,
    )

    capture_pages = [
        _build_capture_page(page, index, manifest_path.parent)
        for index, page in enumerate(pages, start=1)
    ]

    return CaptureImportPayload(
        base_dir=manifest_path.parent,
        season=season,
        snapshot={
            **snapshot,
            "source_type": _resolve_snapshot_source_type(
                snapshot=snapshot,
                raw_ocr=root.get("ocr"),
                ocr_provider=ocr_config.provider,
                provider_override=ocr_provider,
            ),
        },
        pages=capture_pages,
        ocr=ocr_config,
        capture=_require_optional_mapping(root.get("capture"), "capture"),
    )


def build_mock_payload_from_capture(
    payload: CaptureImportPayload,
) -> MockImportPayload:
    return parse_capture_payload(payload).mock_payload


def parse_capture_payload(
    payload: CaptureImportPayload,
    *,
    validate_snapshot_entries: bool = True,
) -> ParsedCapturePayload:
    entries: list[dict[str, Any]] = []
    ignored_lines: list[IgnoredOcrLine] = []
    page_summaries: list[dict[str, Any]] = []
    previous_page_ranks: set[int] | None = None

    for page_index, page in enumerate(payload.pages, start=1):
        image_path = _resolve_existing_path(payload.base_dir, page.image_path, "image_path")
        ocr_text = _load_ocr_text(
            base_dir=payload.base_dir,
            page=page,
            image_path=image_path,
            ocr=payload.ocr,
        )

        page_entries, page_ignored_lines = _parse_page_entries(
            ocr_text=ocr_text,
            image_path=image_path,
            default_ocr_confidence=page.default_ocr_confidence,
            page_index=page_index,
        )
        entries.extend(page_entries)
        ignored_lines.extend(page_ignored_lines)
        current_page_ranks = {entry["rank"] for entry in page_entries}
        overlap_count = 0
        overlap_ratio = 0.0
        if previous_page_ranks:
            overlap_ranks = sorted(previous_page_ranks & current_page_ranks)
            overlap_count = len(overlap_ranks)
            if current_page_ranks:
                overlap_ratio = overlap_count / len(current_page_ranks)
        else:
            overlap_ranks = []
        page_summaries.append(
            {
                "page_index": page_index,
                "image_path": _build_entry_image_path(image_path),
                "entry_count": len(page_entries),
                "ignored_line_count": len(page_ignored_lines),
                "ignored_line_reasons": summarize_ignored_lines(page_ignored_lines),
                "first_rank": min(current_page_ranks) if current_page_ranks else None,
                "last_rank": max(current_page_ranks) if current_page_ranks else None,
                "overlap_with_previous_count": overlap_count,
                "overlap_with_previous_ratio": round(overlap_ratio, 4),
                "overlap_with_previous_ranks": overlap_ranks,
                "new_rank_count": len(current_page_ranks - (previous_page_ranks or set())),
                "new_rank_ratio": round(
                    (
                        len(current_page_ranks - (previous_page_ranks or set()))
                        / len(current_page_ranks)
                    ),
                    4,
                )
                if current_page_ranks
                else 0.0,
            }
        )
        previous_page_ranks = current_page_ranks

    if validate_snapshot_entries:
        _validate_snapshot_entries(entries, page_summaries)
    snapshot_note = _build_snapshot_note_with_collector_summary(
        snapshot=payload.snapshot,
        capture=payload.capture,
        ignored_lines=ignored_lines,
        page_summaries=page_summaries,
    )

    return ParsedCapturePayload(
        mock_payload=MockImportPayload(
            season=payload.season,
            snapshot={
                **payload.snapshot,
                "note": snapshot_note,
            },
            entries=entries,
        ),
        ignored_lines=ignored_lines,
        page_summaries=page_summaries,
    )


def import_capture_payload(
    payload: CaptureImportPayload,
    client: ApiClient,
) -> ImportResult:
    return import_parsed_capture_payload(parse_capture_payload(payload), client)


def import_parsed_capture_payload(
    parsed_payload: ParsedCapturePayload,
    client: ApiClient,
) -> ImportResult:
    return import_mock_payload(parsed_payload.mock_payload, client)


def summarize_ignored_lines(
    ignored_lines: list[IgnoredOcrLine],
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for ignored_line in ignored_lines:
        counts[ignored_line.reason] = counts.get(ignored_line.reason, 0) + 1

    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(counts.items())
    ]


def build_ocr_stop_hints(
    page_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not page_summaries:
        return []

    hints: list[dict[str, Any]] = []
    last_page = page_summaries[-1]
    last_page_entry_count = int(last_page.get("entry_count", 0))
    last_page_ignored_line_count = int(last_page.get("ignored_line_count", 0))
    last_page_overlap_count = int(last_page.get("overlap_with_previous_count", 0))
    last_page_overlap_ratio = float(last_page.get("overlap_with_previous_ratio", 0.0))
    last_page_new_rank_count = int(last_page.get("new_rank_count", 0))
    last_page_new_rank_ratio = float(last_page.get("new_rank_ratio", 0.0))
    last_page_ignored_reason_counts = _build_ignored_reason_count_map(
        last_page.get("ignored_line_reasons", [])
    )
    last_page_overlay_ignored_count = sum(
        last_page_ignored_reason_counts.get(reason, 0)
        for reason in ("reward_line", "ui_control_line", "status_line")
    )

    if len(page_summaries) >= 2 and last_page_entry_count == 0:
        hints.append(
            {
                "reason": "empty_last_page",
                "page_index": last_page["page_index"],
            }
        )

    if len(page_summaries) >= 2 and last_page_entry_count <= 3:
        hints.append(
            {
                "reason": "sparse_last_page",
                "page_index": last_page["page_index"],
                "entry_count": last_page_entry_count,
            }
        )

    if (
        len(page_summaries) >= 2
        and last_page_entry_count > 0
        and last_page_overlap_ratio >= 0.5
    ):
        hints.append(
            {
                "reason": "overlapping_last_page",
                "page_index": last_page["page_index"],
                "overlap_with_previous_count": last_page_overlap_count,
                "overlap_with_previous_ratio": last_page_overlap_ratio,
            }
        )

    if (
        len(page_summaries) >= 2
        and last_page_entry_count >= STALE_LAST_PAGE_MIN_ENTRY_COUNT
        and 0 < last_page_new_rank_ratio <= STALE_LAST_PAGE_NEW_RANK_RATIO_THRESHOLD
    ):
        hints.append(
            {
                "reason": "stale_last_page",
                "page_index": last_page["page_index"],
                "new_rank_count": last_page_new_rank_count,
                "new_rank_ratio": last_page_new_rank_ratio,
            }
        )

    if (
        len(page_summaries) >= 2
        and last_page_entry_count <= 3
        and last_page_overlay_ignored_count > 0
    ):
        hints.append(
            {
                "reason": "overlay_last_page",
                "page_index": last_page["page_index"],
                "ignored_overlay_count": last_page_overlay_ignored_count,
                "entry_count": last_page_entry_count,
            }
        )

    if (
        len(page_summaries) >= 2
        and last_page_entry_count > 0
        and last_page_overlap_count == last_page_entry_count
    ):
        hints.append(
            {
                "reason": "duplicate_last_page",
                "page_index": last_page["page_index"],
                "overlap_with_previous_count": last_page_overlap_count,
                "overlap_with_previous_ratio": last_page_overlap_ratio,
            }
        )

    if (
        last_page_ignored_line_count >= last_page_entry_count
        and last_page_ignored_line_count > 0
    ):
        hints.append(
            {
                "reason": "noisy_last_page",
                "page_index": last_page["page_index"],
                "ignored_line_count": last_page_ignored_line_count,
                "entry_count": last_page_entry_count,
            }
        )

    return hints


def build_ocr_stop_recommendation(
    ocr_stop_hints: list[dict[str, Any]],
) -> dict[str, Any]:
    reason_levels = {
        "empty_last_page": "hard",
        "noisy_last_page": "hard",
        "duplicate_last_page": "hard",
        "overlay_last_page": "hard",
        "sparse_last_page": "soft",
        "overlapping_last_page": "soft",
        "stale_last_page": "soft",
    }
    levels = [reason_levels.get(hint["reason"], "soft") for hint in ocr_stop_hints]

    if not levels:
        level = None
    elif "hard" in levels:
        level = "hard"
    else:
        level = "soft"

    reasons = [hint["reason"] for hint in ocr_stop_hints]
    primary_reason = None
    if reasons:
        if level == "hard":
            for hint in ocr_stop_hints:
                if reason_levels.get(hint["reason"], "soft") == "hard":
                    primary_reason = hint["reason"]
                    break
        else:
            primary_reason = reasons[0]

    return {
        "should_stop": len(ocr_stop_hints) > 0,
        "level": level,
        "primary_reason": primary_reason,
        "reasons": reasons,
    }


def _build_snapshot_note_with_collector_summary(
    *,
    snapshot: dict[str, Any],
    capture: dict[str, Any] | None,
    ignored_lines: list[IgnoredOcrLine],
    page_summaries: list[dict[str, Any]],
) -> str | None:
    existing_note = snapshot.get("note")
    existing_note_text = existing_note.strip() if isinstance(existing_note, str) else ""

    summary_parts: list[str] = []
    if capture:
        requested = capture.get("requested_page_count")
        captured = capture.get("captured_page_count")
        if requested is not None and captured is not None:
            summary_parts.append(f"pages={captured}/{requested}")
        stopped_reason = capture.get("stopped_reason")
        if isinstance(stopped_reason, str) and stopped_reason.strip():
            summary_parts.append(f"capture_stop={stopped_reason}")

    ignored_line_count = len(ignored_lines)
    if ignored_line_count > 0:
        ignored_summary = ",".join(
            f"{row['reason']}={row['count']}"
            for row in summarize_ignored_lines(ignored_lines)
        )
        summary_parts.append(f"ignored={ignored_line_count}({ignored_summary})")

    ocr_stop_recommendation = build_ocr_stop_recommendation(
        build_ocr_stop_hints(page_summaries)
    )
    if ocr_stop_recommendation["should_stop"] and (
        ocr_stop_recommendation["level"] == "hard" or bool(capture)
    ):
        summary_parts.append(
            "ocr_stop="
            f"{ocr_stop_recommendation['primary_reason']}({ocr_stop_recommendation['level']})"
        )

    if not summary_parts:
        return existing_note_text or None

    collector_summary = COLLECTOR_SUMMARY_PREFIX + "; ".join(summary_parts)
    collector_details = _build_collector_details_line(page_summaries)
    if existing_note_text:
        return "\n".join(
            line
            for line in (existing_note_text, collector_summary, collector_details)
            if line
        )
    return "\n".join(line for line in (collector_summary, collector_details) if line)


def _build_ignored_reason_count_map(
    ignored_line_reasons: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        str(row["reason"]): int(row["count"])
        for row in ignored_line_reasons
        if "reason" in row and "count" in row
    }


def _build_collector_details_line(page_summaries: list[dict[str, Any]]) -> str | None:
    if not page_summaries:
        return None

    payload = {
        "page_summaries": [
            {
                "page_index": summary["page_index"],
                "image_path": summary["image_path"],
                "entry_count": summary["entry_count"],
                "ignored_line_count": summary["ignored_line_count"],
                "ignored_line_reasons": summary["ignored_line_reasons"],
                "first_rank": summary["first_rank"],
                "last_rank": summary["last_rank"],
                "overlap_with_previous_count": summary["overlap_with_previous_count"],
                "overlap_with_previous_ratio": summary["overlap_with_previous_ratio"],
                "new_rank_count": summary["new_rank_count"],
                "new_rank_ratio": summary["new_rank_ratio"],
            }
            for summary in page_summaries
        ],
        "ocr_stop_hints": build_ocr_stop_hints(page_summaries),
        "ocr_stop_recommendation": build_ocr_stop_recommendation(
            build_ocr_stop_hints(page_summaries)
        ),
    }
    return COLLECTOR_JSON_PREFIX + json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


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


def _load_ocr_text(
    *,
    base_dir: Path,
    page: CapturePage,
    image_path: Path,
    ocr: OcrConfig,
) -> str:
    if ocr.provider == OCR_PROVIDER_SIDECAR:
        return _resolve_ocr_text_path(base_dir, page).read_text(encoding="utf-8")
    if ocr.provider == OCR_PROVIDER_TESSERACT:
        return _run_tesseract_ocr(image_path, ocr)

    raise MockImportError(f"지원하지 않는 OCR provider입니다: {ocr.provider}")


def _run_tesseract_ocr(image_path: Path, ocr: OcrConfig) -> str:
    command = ocr.command or DEFAULT_TESSERACT_COMMAND
    if shutil.which(command) is None:
        raise MockImportError(
            "tesseract 명령을 찾을 수 없습니다. "
            f"command={command!r}, image_path={image_path}"
        )

    args = [command, str(image_path), "stdout"]
    if ocr.language:
        args.extend(["-l", ocr.language])
    if ocr.psm is not None:
        args.extend(["--psm", str(ocr.psm)])

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise MockImportError(
            f"tesseract 실행에 실패했습니다: command={command!r}, image_path={image_path}"
        ) from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip() or "unknown error"
        raise MockImportError(
            "tesseract OCR에 실패했습니다. "
            f"image_path={image_path}, returncode={result.returncode}, stderr={stderr}"
        )

    ocr_text = result.stdout.strip()
    if not ocr_text:
        raise MockImportError(
            f"tesseract OCR 결과가 비어 있습니다: image_path={image_path}"
        )
    return ocr_text


def _build_ocr_config(
    raw_ocr: Any,
    *,
    provider_override: str | None,
    command_override: str | None,
    language_override: str | None,
    psm_override: int | None,
) -> OcrConfig:
    ocr_mapping = _require_optional_mapping(raw_ocr, "ocr")

    provider = provider_override or ocr_mapping.get("provider") or OCR_PROVIDER_SIDECAR
    if provider not in CAPTURE_SOURCE_TYPE_BY_PROVIDER:
        supported = ", ".join(sorted(CAPTURE_SOURCE_TYPE_BY_PROVIDER))
        raise MockImportError(
            f"지원하지 않는 OCR provider입니다: {provider}. supported={supported}"
        )

    command = command_override or ocr_mapping.get("command")
    language = language_override or ocr_mapping.get("language")
    raw_psm = psm_override if psm_override is not None else ocr_mapping.get("psm")
    psm = None
    if raw_psm is not None:
        try:
            psm = int(raw_psm)
        except (TypeError, ValueError) as exc:
            raise MockImportError("ocr.psm은 정수여야 합니다.") from exc

    if provider == OCR_PROVIDER_TESSERACT and command is None:
        command = DEFAULT_TESSERACT_COMMAND

    return OcrConfig(
        provider=provider,
        command=command,
        language=language,
        psm=psm,
    )


def _resolve_snapshot_source_type(
    *,
    snapshot: dict[str, Any],
    raw_ocr: Any,
    ocr_provider: str,
    provider_override: str | None,
) -> str:
    ocr_mapping = _require_optional_mapping(raw_ocr, "ocr")
    if provider_override is not None or "provider" in ocr_mapping:
        return CAPTURE_SOURCE_TYPE_BY_PROVIDER[ocr_provider]

    snapshot_source_type = snapshot.get("source_type")
    if isinstance(snapshot_source_type, str) and snapshot_source_type.strip():
        return snapshot_source_type

    return CAPTURE_SOURCE_TYPE_BY_PROVIDER[ocr_provider]


def _parse_page_entries(
    *,
    ocr_text: str,
    image_path: Path,
    default_ocr_confidence: float | None,
    page_index: int,
) -> tuple[list[dict[str, Any]], list[IgnoredOcrLine]]:
    entries: list[dict[str, Any]] = []
    ignored_lines: list[IgnoredOcrLine] = []

    for line_index, raw_line in enumerate(ocr_text.splitlines(), start=1):
        if not raw_line.strip():
            ignored_lines.append(
                IgnoredOcrLine(
                    page_index=page_index,
                    line_index=line_index,
                    raw_text=raw_line,
                    reason="blank_line",
                )
            )
            continue
        ignored_reason = _get_ignored_line_reason(raw_line)
        if ignored_reason is not None:
            ignored_lines.append(
                IgnoredOcrLine(
                    page_index=page_index,
                    line_index=line_index,
                    raw_text=raw_line,
                    reason=ignored_reason,
                )
            )
            continue

        try:
            entry = _parse_ocr_line(
                raw_line=raw_line,
                image_path=image_path,
                default_ocr_confidence=default_ocr_confidence,
                page_index=page_index,
                line_index=line_index,
            )
        except MockImportError:
            ignored_lines.append(
                IgnoredOcrLine(
                    page_index=page_index,
                    line_index=line_index,
                    raw_text=raw_line,
                    reason="malformed_entry_line",
                )
            )
            continue
        entries.append(entry)

    return entries, ignored_lines


def _parse_ocr_line(
    *,
    raw_line: str,
    image_path: Path,
    default_ocr_confidence: float | None,
    page_index: int,
    line_index: int,
) -> dict[str, Any]:
    normalized_line = _normalize_structured_ocr_line(raw_line)
    tab_parts = normalized_line.split("\t")
    if len(tab_parts) in (3, 4):
        rank_text, player_name, score_text, *confidence_text = tab_parts
        ocr_confidence = (
            _parse_float_token(confidence_text[0], "ocr_confidence", page_index, line_index)
            if confidence_text
            else default_ocr_confidence
        )
        return {
            "rank": _parse_int_token(rank_text, "rank", page_index, line_index),
            "score": _parse_score_text(score_text, page_index=page_index, line_index=line_index),
            "player_name": _normalize_player_name(player_name),
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
    normalized = (
        _normalize_rank_ocr_token(value)
        if label == "rank"
        else _normalize_score_ocr_token(value)
        if label == "score"
        else _normalize_integer_ocr_token(value)
    )
    try:
        return int(normalized)
    except ValueError as exc:
        raise MockImportError(
            f"{label} 파싱에 실패했습니다. page={page_index}, line={line_index}, value={value!r}"
        ) from exc


def _can_parse_rank_token(value: str) -> bool:
    normalized = _normalize_rank_ocr_token(value)
    return normalized.isdigit()


def _get_ignored_line_reason(raw_line: str) -> str | None:
    stripped = raw_line.strip()
    if not stripped:
        return "blank_line"

    normalized = _normalize_structured_ocr_line(stripped)

    if _looks_like_separator_line(normalized):
        return "separator_line"
    if _looks_like_header_line(normalized):
        return "header_line"
    if _looks_like_pagination_line(normalized):
        return "pagination_line"
    if _looks_like_footer_line(normalized):
        return "footer_line"
    if _looks_like_reward_line(normalized):
        return "reward_line"
    if _looks_like_ui_control_line(normalized):
        return "ui_control_line"
    if _looks_like_status_line(normalized):
        return "status_line"
    if _looks_like_metadata_line(normalized):
        return "metadata_line"

    first_token = normalized.split()[0]
    if not _can_parse_rank_token(first_token):
        return "non_entry_line"

    return None


def _looks_like_separator_line(value: str) -> bool:
    return all(character in OCR_SEPARATOR_CHARACTERS for character in value)


def _looks_like_header_line(value: str) -> bool:
    lowered = value.lower().replace("\t", " ")
    english_header = "rank" in lowered and any(
        keyword in lowered for keyword in ("score", "player", "nickname", "name")
    )
    korean_header = "순위" in value and any(
        keyword in value for keyword in ("점수", "스코어", "닉네임", "이름")
    )
    compact_korean_header = any(token in value for token in ("순위닉네임점수", "순위이름점수"))
    return english_header or korean_header or compact_korean_header


def _looks_like_pagination_line(value: str) -> bool:
    normalized = " ".join(value.split())
    if PAGINATION_RE.match(normalized):
        return True
    lowered = normalized.lower()
    return lowered.startswith("page ") and any(separator in lowered for separator in ("/", " of "))


def _looks_like_footer_line(value: str) -> bool:
    lowered = value.lower()
    footer_keywords = (
        "tap to continue",
        "touch to continue",
        "press any key",
        "click to continue",
        "continue",
        "back",
        "close",
        "retry",
        "next",
    )
    korean_footer_keywords = (
        "계속",
        "다음",
        "닫기",
        "뒤로",
        "재시도",
        "터치",
        "탭",
    )
    return any(keyword in lowered for keyword in footer_keywords) or any(
        keyword in value for keyword in korean_footer_keywords
    )


def _looks_like_reward_line(value: str) -> bool:
    lowered = value.lower()
    reward_keywords = (
        "reward",
        "ranking reward",
        "clear reward",
        "획득",
        "보상",
        "청휘석",
        "크레딧",
        "엘리그마",
    )
    return any(keyword in lowered for keyword in reward_keywords) or any(
        keyword in value for keyword in ("획득", "보상", "청휘석", "크레딧", "엘리그마")
    )


def _looks_like_ui_control_line(value: str) -> bool:
    lowered = value.lower()
    ui_keywords = (
        "search",
        "sort",
        "filter",
        "refresh",
        "menu",
        "검색",
        "정렬",
        "필터",
        "새로고침",
        "메뉴",
    )
    return any(keyword in lowered for keyword in ui_keywords) or any(
        keyword in value for keyword in ("검색", "정렬", "필터", "새로고침", "메뉴")
    )


def _looks_like_status_line(value: str) -> bool:
    lowered = value.lower()
    english_keywords = (
        "my rank",
        "current rank",
        "best score",
        "current score",
        "your rank",
    )
    korean_keywords = (
        "내 순위",
        "현재 순위",
        "최고 점수",
        "현재 점수",
        "내 점수",
    )
    return any(keyword in lowered for keyword in english_keywords) or any(
        keyword in value for keyword in korean_keywords
    )


def _looks_like_metadata_line(value: str) -> bool:
    lowered = value.lower()
    if any(keyword in lowered for keyword in ("page", "captured", "server", "season", "boss", "total")):
        return True
    if any(keyword in lowered for keyword in ("time", "remaining", "version", "ver.", "utc", "kst")):
        return True
    if re.search(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b", value):
        return True
    if re.search(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", value):
        return True

    if any(character.isdigit() for character in value) and any(
        keyword in value for keyword in ("총", "인원", "참여", "합계")
    ):
        return True
    if any(keyword in value for keyword in ("남은시간", "버전", "서버", "캡처", "시각")):
        return True

    return False


def _parse_float_token(
    value: str,
    label: str,
    page_index: int,
    line_index: int,
) -> float:
    normalized = _normalize_float_ocr_token(value)
    try:
        parsed = float(normalized)
    except ValueError as exc:
        raise MockImportError(
            f"{label} 파싱에 실패했습니다. page={page_index}, line={line_index}, value={value!r}"
        ) from exc

    if _looks_like_percent_token(value):
        return parsed / 100

    return parsed


def _normalize_integer_ocr_token(value: str) -> str:
    normalized = (
        _normalize_unicode_ocr_text(value).strip()
        .replace(",", "")
        .replace(".", "")
        .translate(OCR_NUMERIC_TRANSLATION)
    )
    return normalized.strip(".:;%/" + OCR_EDGE_PUNCTUATION)


def _normalize_rank_ocr_token(value: str) -> str:
    normalized = _normalize_unicode_ocr_text(value).strip().rstrip(OCR_EDGE_PUNCTUATION)
    lowered = normalized.lower()
    if lowered.startswith("no."):
        normalized = normalized[3:]
    elif lowered.startswith("no"):
        normalized = normalized[2:]
    if normalized.startswith("#"):
        normalized = normalized[1:]
    normalized = normalized.removeprefix("№")
    normalized = normalized.removesuffix("위")
    normalized = _normalize_integer_ocr_token(normalized)
    return normalized.strip(".:- ")


def _normalize_float_ocr_token(value: str) -> str:
    normalized = _normalize_unicode_ocr_text(value).strip().translate(OCR_NUMERIC_TRANSLATION)
    normalized = normalized.replace(" ", "")
    if _looks_like_percent_token(normalized):
        normalized = normalized[:-1]
    elif "," in normalized and "." not in normalized and normalized.count(",") == 1:
        integer_part, fractional_part = normalized.split(",", 1)
        if integer_part.isdigit() and fractional_part.isdigit() and 1 <= len(fractional_part) <= 2:
            normalized = f"{integer_part}.{fractional_part}"
        else:
            normalized = normalized.replace(",", "")
    else:
        normalized = normalized.replace(",", "")
    return normalized.strip(".:;/%" + OCR_EDGE_PUNCTUATION)


def _normalize_score_ocr_token(value: str) -> str:
    stripped = _normalize_unicode_ocr_text(value).strip()
    lowered = stripped.lower().rstrip(OCR_EDGE_PUNCTUATION)
    for suffix in ("pts", "pt"):
        if lowered.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break
    if stripped.endswith("점"):
        stripped = stripped[:-1]
    return _normalize_integer_ocr_token(stripped)


def _looks_like_percent_token(value: str) -> bool:
    stripped = (
        _normalize_unicode_ocr_text(value)
        .strip()
        .translate(OCR_NUMERIC_TRANSLATION)
        .rstrip(OCR_EDGE_PUNCTUATION)
    )
    return stripped.endswith("%")


def _parse_whitespace_fallback_line(
    *,
    raw_line: str,
    image_path: Path,
    default_ocr_confidence: float | None,
    page_index: int,
    line_index: int,
) -> dict[str, Any]:
    tokens = _normalize_trailing_percent_tokens(raw_line.split())
    if len(tokens) < 3:
        raise MockImportError(
            "OCR line 파싱에 실패했습니다. "
            f"page={page_index}, line={line_index}, raw_text={raw_line!r}"
        )

    rank = _parse_int_token(tokens[0], "rank", page_index, line_index)
    ocr_confidence: float | None = default_ocr_confidence
    body_tokens = tokens[1:]
    if len(tokens) >= 4 and _looks_like_confidence_token(tokens[-1]):
        body_tokens = tokens[1:-1]
        ocr_confidence = _parse_float_token(
            tokens[-1], "ocr_confidence", page_index, line_index
        )
    score_tokens, player_tokens = _split_score_and_player_tokens(
        body_tokens,
        page_index=page_index,
        line_index=line_index,
    )

    if not player_tokens:
        raise MockImportError(
            "OCR line 파싱에 실패했습니다. "
            f"page={page_index}, line={line_index}, raw_text={raw_line!r}"
        )

    return {
        "rank": rank,
        "score": _parse_grouped_score_tokens(
            score_tokens,
            page_index=page_index,
            line_index=line_index,
        ),
        "player_name": _normalize_player_name(" ".join(player_tokens)),
        "ocr_confidence": ocr_confidence,
        "raw_text": raw_line,
        "image_path": _build_entry_image_path(image_path),
        "is_valid": True,
        "validation_issue": None,
    }


def _normalize_structured_ocr_line(raw_line: str) -> str:
    raw_line = _normalize_unicode_ocr_text(raw_line)
    if not any(separator in raw_line for separator in ("|", "¦", "｜")):
        return raw_line

    columns = [
        part.strip()
        for part in STRUCTURED_COLUMN_SEPARATOR_RE.split(raw_line.strip())
    ]
    while columns and columns[-1] == "" and len(columns) > 3:
        columns.pop()
    if len(columns) in (3, 4):
        return "\t".join(columns)

    return raw_line


def _looks_like_confidence_token(value: str) -> bool:
    stripped_original = value.strip()
    stripped = _normalize_float_ocr_token(value)
    if "." not in stripped and not _looks_like_percent_token(stripped_original):
        return False

    try:
        parsed = float(stripped)
    except ValueError:
        return False

    if _looks_like_percent_token(stripped_original):
        return 0 <= parsed <= 100

    return 0 <= parsed <= 1


def _split_score_and_player_tokens(
    body_tokens: list[str],
    *,
    page_index: int,
    line_index: int,
) -> tuple[list[str], list[str]]:
    if len(body_tokens) < 2:
        raise MockImportError(
            "OCR line 파싱에 실패했습니다. "
            f"page={page_index}, line={line_index}, raw_text tokens 부족"
        )

    score_start = len(body_tokens) - 1
    last_token_normalized = _normalize_score_ocr_token(body_tokens[-1])
    if len(last_token_normalized) > 3:
        return body_tokens[-1:], body_tokens[:-1]

    while score_start > 0:
        candidate = body_tokens[score_start - 1]
        normalized_candidate = _normalize_score_ocr_token(candidate)
        if not (normalized_candidate.isdigit() and len(normalized_candidate) == 3):
            break
        score_start -= 1

    if score_start > 0:
        leading_candidate = _normalize_score_ocr_token(body_tokens[score_start - 1])
        if leading_candidate.isdigit() and 1 <= len(leading_candidate) <= 3:
            score_start -= 1

    return body_tokens[score_start:], body_tokens[:score_start]


def _parse_grouped_score_tokens(
    score_tokens: list[str],
    *,
    page_index: int,
    line_index: int,
) -> int:
    if not score_tokens:
        raise MockImportError(
            "OCR line 파싱에 실패했습니다. "
            f"page={page_index}, line={line_index}, score token이 없습니다."
        )

    if len(score_tokens) == 1:
        return _parse_int_token(score_tokens[0], "score", page_index, line_index)

    normalized_tokens = [
        _normalize_score_ocr_token(token)
        for token in _strip_trailing_score_suffix_tokens(score_tokens)
    ]
    if not all(token.isdigit() for token in normalized_tokens):
        raise MockImportError(
            "OCR line 파싱에 실패했습니다. "
            f"page={page_index}, line={line_index}, grouped score token이 숫자가 아닙니다."
        )

    return int("".join(normalized_tokens))


def _parse_score_text(
    value: str,
    *,
    page_index: int,
    line_index: int,
) -> int:
    score_tokens = value.split()
    if len(score_tokens) <= 1:
        return _parse_int_token(value, "score", page_index, line_index)

    return _parse_grouped_score_tokens(
        score_tokens,
        page_index=page_index,
        line_index=line_index,
    )


def _normalize_player_name(value: str) -> str:
    normalized = " ".join(_normalize_unicode_ocr_text(value).split())
    normalized = _strip_wrapping_player_name_punctuation(normalized)
    return normalized.strip("·•ㆍ ")


def _normalize_unicode_ocr_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return ZERO_WIDTH_CHARACTERS_RE.sub("", normalized)


def _strip_wrapping_player_name_punctuation(value: str) -> str:
    stripped = value.strip()
    while len(stripped) >= 2:
        first, last = stripped[0], stripped[-1]
        if (
            first in PLAYER_NAME_EDGE_PUNCTUATION
            and last in PLAYER_NAME_EDGE_PUNCTUATION
        ):
            stripped = stripped[1:-1].strip()
            continue
        break
    return stripped


def _normalize_trailing_percent_tokens(tokens: list[str]) -> list[str]:
    if len(tokens) >= 2 and tokens[-1] in {"%", "％"}:
        return [*tokens[:-2], tokens[-2] + tokens[-1]]
    return tokens


def _strip_trailing_score_suffix_tokens(score_tokens: list[str]) -> list[str]:
    stripped_tokens = list(score_tokens)
    while stripped_tokens:
        lowered = stripped_tokens[-1].strip().lower().rstrip(OCR_EDGE_PUNCTUATION)
        if lowered not in SCORE_SUFFIX_TOKENS:
            break
        stripped_tokens.pop()
    return stripped_tokens


def _validate_snapshot_entries(
    entries: list[dict[str, Any]],
    page_summaries: list[dict[str, Any]],
) -> None:
    if not entries:
        raise MockImportError("capture 전체에서 파싱 가능한 OCR entry가 없습니다.")

    summary = summarize_snapshot_entries(entries)

    if summary.duplicate_ranks:
        joined_ranks = ", ".join(str(rank) for rank in summary.duplicate_ranks)
        overlap_hints = [
            f"{page_summaries[index - 1]['page_index']}-{page_summary['page_index']}"
            for index, page_summary in enumerate(page_summaries)
            if index > 0 and page_summary["overlap_with_previous_count"] > 0
        ]
        overlap_hint_suffix = ""
        if overlap_hints:
            overlap_hint_suffix = (
                ", overlapping_page_pairs=" + ", ".join(overlap_hints)
            )
        raise MockImportError(
            "capture entries 사전 검증에 실패했습니다. "
            f"validation_issue={ValidationIssueCode.DUPLICATE_RANK.value}, "
            f"duplicate_ranks={joined_ranks}{overlap_hint_suffix}"
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


def _require_optional_mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    return _require_mapping(value, label)


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
    parser.add_argument(
        "--ocr-provider",
        choices=sorted(CAPTURE_SOURCE_TYPE_BY_PROVIDER),
        help="OCR provider override (default: manifest 설정 또는 sidecar)",
    )
    parser.add_argument(
        "--ocr-command",
        help="OCR 명령 경로 override. tesseract provider에서 사용합니다.",
    )
    parser.add_argument(
        "--ocr-language",
        help="OCR language override. tesseract provider에서 -l 옵션으로 전달합니다.",
    )
    parser.add_argument(
        "--ocr-psm",
        type=int,
        help="OCR page segmentation mode override. tesseract provider에서 --psm으로 전달합니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        payload = load_capture_import_payload(
            args.capture_path,
            ocr_provider=args.ocr_provider,
            ocr_command=args.ocr_command,
            ocr_language=args.ocr_language,
            ocr_psm=args.ocr_psm,
        )
        parsed_payload = parse_capture_payload(payload)
        ignored_line_reasons = summarize_ignored_lines(parsed_payload.ignored_lines)
        ocr_stop_hints = build_ocr_stop_hints(parsed_payload.page_summaries)
        ocr_stop_recommendation = build_ocr_stop_recommendation(ocr_stop_hints)
        result = import_mock_payload(parsed_payload.mock_payload, ApiClient(args.base_url))
    except MockImportError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "season_id": result.season_id,
                "snapshot_id": result.snapshot_id,
                "page_count": len(payload.pages),
                "entry_count": len(parsed_payload.mock_payload.entries),
                "ignored_line_count": len(parsed_payload.ignored_lines),
                "ignored_line_reasons": ignored_line_reasons,
                "page_summaries": parsed_payload.page_summaries,
                "ocr_stop_hints": ocr_stop_hints,
                "ocr_stop_recommendation": ocr_stop_recommendation,
                "ignored_lines": [
                    {
                        "page_index": line.page_index,
                        "line_index": line.line_index,
                        "raw_text": line.raw_text,
                        "reason": line.reason,
                    }
                    for line in parsed_payload.ignored_lines
                ],
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
