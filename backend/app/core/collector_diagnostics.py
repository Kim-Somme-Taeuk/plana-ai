from __future__ import annotations

import json
import re
from dataclasses import dataclass


COLLECTOR_NOTE_PREFIX = "collector: "
COLLECTOR_JSON_PREFIX = "collector_json: "
_PAGES_PATTERN = re.compile(r"^pages=(\d+)/(\d+)$")
_IGNORED_PATTERN = re.compile(r"^ignored=(\d+)\((.+)\)$")
_OCR_STOP_PATTERN = re.compile(r"^ocr_stop=([^(]+)\(([^)]+)\)$")


@dataclass(frozen=True)
class CollectorIgnoredReasonCount:
    reason: str
    count: int


@dataclass(frozen=True)
class CollectorDiagnosticsSummary:
    raw_summary: str
    captured_page_count: int | None
    requested_page_count: int | None
    capture_stop_reason: str | None
    ignored_line_count: int
    ignored_reasons: tuple[CollectorIgnoredReasonCount, ...]
    ocr_stop_reason: str | None
    ocr_stop_level: str | None
    page_summaries: tuple[dict[str, object], ...]
    ocr_stop_hints: tuple[dict[str, object], ...]
    ocr_stop_recommendation: dict[str, object] | None


def parse_collector_diagnostics_summary(
    note: str | None,
) -> CollectorDiagnosticsSummary | None:
    summary_line = _extract_collector_summary_line(note)
    if summary_line is None:
        return None

    captured_page_count: int | None = None
    requested_page_count: int | None = None
    capture_stop_reason: str | None = None
    ignored_line_count = 0
    ignored_reasons: list[CollectorIgnoredReasonCount] = []
    ocr_stop_reason: str | None = None
    ocr_stop_level: str | None = None
    details_payload = _extract_collector_details_payload(note)

    for raw_part in summary_line.split("; "):
        part = raw_part.strip()
        if not part:
            continue

        pages_match = _PAGES_PATTERN.fullmatch(part)
        if pages_match is not None:
            captured_page_count = int(pages_match.group(1))
            requested_page_count = int(pages_match.group(2))
            continue

        if part.startswith("capture_stop="):
            capture_stop_reason = part.removeprefix("capture_stop=").strip() or None
            continue

        ignored_match = _IGNORED_PATTERN.fullmatch(part)
        if ignored_match is not None:
            ignored_line_count = int(ignored_match.group(1))
            ignored_reasons = _parse_ignored_reasons(ignored_match.group(2))
            continue

        ocr_stop_match = _OCR_STOP_PATTERN.fullmatch(part)
        if ocr_stop_match is not None:
            ocr_stop_reason = ocr_stop_match.group(1).strip() or None
            ocr_stop_level = ocr_stop_match.group(2).strip() or None

    return CollectorDiagnosticsSummary(
        raw_summary=summary_line,
        captured_page_count=captured_page_count,
        requested_page_count=requested_page_count,
        capture_stop_reason=capture_stop_reason,
        ignored_line_count=ignored_line_count,
        ignored_reasons=tuple(ignored_reasons),
        ocr_stop_reason=ocr_stop_reason,
        ocr_stop_level=ocr_stop_level,
        page_summaries=tuple(_parse_page_summaries(details_payload.get("page_summaries"))),
        ocr_stop_hints=tuple(_parse_simple_object_list(details_payload.get("ocr_stop_hints"))),
        ocr_stop_recommendation=_parse_simple_object(
            details_payload.get("ocr_stop_recommendation")
        ),
    )


def _extract_collector_summary_line(note: str | None) -> str | None:
    if not isinstance(note, str) or not note.strip():
        return None

    for raw_line in reversed(note.splitlines()):
        line = raw_line.strip()
        if line.startswith(COLLECTOR_NOTE_PREFIX):
            return line.removeprefix(COLLECTOR_NOTE_PREFIX).strip() or None

    return None


def _extract_collector_details_payload(note: str | None) -> dict[str, object]:
    if not isinstance(note, str) or not note.strip():
        return {}

    for raw_line in reversed(note.splitlines()):
        line = raw_line.strip()
        if not line.startswith(COLLECTOR_JSON_PREFIX):
            continue
        raw_json = line.removeprefix(COLLECTOR_JSON_PREFIX).strip()
        if not raw_json:
            return {}
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}

    return {}


def _parse_ignored_reasons(raw_value: str) -> list[CollectorIgnoredReasonCount]:
    reasons: list[CollectorIgnoredReasonCount] = []
    for raw_part in raw_value.split(","):
        part = raw_part.strip()
        if "=" not in part:
            continue

        reason, raw_count = part.split("=", 1)
        reason = reason.strip()
        raw_count = raw_count.strip()
        if not reason:
            continue

        try:
            count = int(raw_count)
        except ValueError:
            continue

        reasons.append(CollectorIgnoredReasonCount(reason=reason, count=count))

    return reasons


def _parse_page_summaries(raw_value: object) -> list[dict[str, object]]:
    if not isinstance(raw_value, list):
        return []

    page_summaries: list[dict[str, object]] = []
    for raw_item in raw_value:
        if not isinstance(raw_item, dict):
            continue
        page_summary = _parse_simple_object(raw_item)
        if page_summary is None:
            continue
        page_summaries.append(page_summary)
    return page_summaries


def _parse_simple_object_list(raw_value: object) -> list[dict[str, object]]:
    if not isinstance(raw_value, list):
        return []

    rows: list[dict[str, object]] = []
    for raw_item in raw_value:
        parsed = _parse_simple_object(raw_item)
        if parsed is not None:
            rows.append(parsed)
    return rows


def _parse_simple_object(raw_value: object) -> dict[str, object] | None:
    if not isinstance(raw_value, dict):
        return None

    parsed: dict[str, object] = {}
    for key, value in raw_value.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            parsed[key] = value
            continue
        if isinstance(value, list):
            scalar_rows = [
                row
                for row in value
                if isinstance(row, (str, int, float, bool)) or row is None
            ]
            if len(scalar_rows) == len(value):
                parsed[key] = scalar_rows
                continue
            rows = _parse_simple_object_list(value)
            if rows:
                parsed[key] = rows
        elif isinstance(value, dict):
            nested = _parse_simple_object(value)
            if nested is not None:
                parsed[key] = nested

    return parsed
