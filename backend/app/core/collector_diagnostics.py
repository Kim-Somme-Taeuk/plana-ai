from __future__ import annotations

import re
from dataclasses import dataclass


COLLECTOR_NOTE_PREFIX = "collector: "
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
    )


def _extract_collector_summary_line(note: str | None) -> str | None:
    if not isinstance(note, str) or not note.strip():
        return None

    for raw_line in reversed(note.splitlines()):
        line = raw_line.strip()
        if line.startswith(COLLECTOR_NOTE_PREFIX):
            return line.removeprefix(COLLECTOR_NOTE_PREFIX).strip() or None

    return None


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
