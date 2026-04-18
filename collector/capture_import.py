from __future__ import annotations

import argparse
from collections import Counter
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
OCR_RANK_TRANSLATION = str.maketrans(
    {
        "S": "5",
        "s": "5",
        "Z": "2",
        "z": "2",
    }
)
OCR_SEPARATOR_CHARACTERS = frozenset("-_=|:;.,·~")
OCR_EDGE_PUNCTUATION = "[](){}<>\"'“”‘’"
PLAYER_NAME_EDGE_PUNCTUATION = "[](){}<>\"'“”‘’「」『』【】"
SCORE_SUFFIX_TOKENS = frozenset({"점", "pt", "pts"})
DIFFICULTY_LABELS = (
    "Normal",
    "Hard",
    "VeryHard",
    "Hardcore",
    "Extreme",
    "Insane",
    "Torment",
    "Lunatic",
)
DIFFICULTY_BY_NORMALIZED_TOKEN = {
    re.sub(r"[^A-Z0-9]+", "", label.upper()): label
    for label in DIFFICULTY_LABELS
}
DIFFICULTY_PRIORITY = {
    "Lunatic": 3,
    "Torment": 2,
    "Insane": 1,
}
DIFFICULTY_ALIAS_BY_NORMALIZED_TOKEN = {
    "GINATIE": "Lunatic",
    "GINATI": "Lunatic",
    "GMATI": "Lunatic",
    "GINATC": "Lunatic",
    "LUNATIE": "Lunatic",
    "INASANE": "Insane",
    "INSANE": "Insane",
    "TORMEMT": "Torment",
}
ZERO_WIDTH_CHARACTERS_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
PAGINATION_RE = re.compile(
    r"^(?:page\s*)?\d+\s*(?:/|of)\s*\d+$",
    re.IGNORECASE,
)
STRUCTURED_COLUMN_SEPARATOR_RE = re.compile(r"\s*[|¦｜]\s*")
COLLECTOR_SUMMARY_PREFIX = "collector: "
COLLECTOR_JSON_PREFIX = "collector_json: "
SNAPSHOT_NOTE_MAX_LENGTH = 255
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
    extra_args: tuple[str, ...]
    crop: "OcrCrop | None"
    upscale_ratio: float
    reuse_cached_sidecar: bool
    persist_sidecar: bool


@dataclass(frozen=True)
class OcrCrop:
    left_ratio: float
    top_ratio: float
    right_ratio: float
    bottom_ratio: float


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


@dataclass(frozen=True)
class TesseractTsvWord:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float | None
    block_num: int
    par_num: int
    line_num: int


def load_capture_import_payload(
    path: str | Path,
    *,
    ocr_provider: str | None = None,
    ocr_command: str | None = None,
    ocr_language: str | None = None,
    ocr_psm: int | None = None,
    reuse_tesseract_sidecar: bool | None = None,
    persist_tesseract_sidecar: bool | None = None,
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
        extra_args_override=None,
        reuse_cached_sidecar_override=reuse_tesseract_sidecar,
        persist_sidecar_override=persist_tesseract_sidecar,
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
    ignored_lines: list[IgnoredOcrLine] = []
    page_metadata: list[dict[str, Any]] = []
    parsed_pages: list[list[dict[str, Any]]] = []
    previous_page_entries: list[dict[str, Any]] = []

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
            ocr=payload.ocr,
            default_ocr_confidence=page.default_ocr_confidence,
            page_index=page_index,
        )
        page_entries = _realign_overlapping_page_entry_ranks(
            previous_page_entries=previous_page_entries,
            current_page_entries=page_entries,
        )
        page_absolute_rank_anchor = next(
            (
                entry.get("_absolute_rank_anchor")
                for entry in page_entries
                if entry.get("_absolute_rank_anchor") is not None
            ),
            None,
        )
        page_absolute_rank_anchor_source = next(
            (
                entry.get("_absolute_rank_anchor_source")
                for entry in page_entries
                if entry.get("_absolute_rank_anchor_source") is not None
            ),
            None,
        )
        page_absolute_rank_base = next(
            (
                entry.get("_absolute_rank_base")
                for entry in page_entries
                if entry.get("_absolute_rank_base") is not None
            ),
            None,
        )
        page_absolute_rank_base_source = next(
            (
                entry.get("_absolute_rank_base_source")
                for entry in page_entries
                if entry.get("_absolute_rank_base_source") is not None
            ),
            None,
        )
        ignored_lines.extend(page_ignored_lines)
        page_metadata.append(
            {
                "page_index": page_index,
                "image_path": _build_entry_image_path(image_path),
                "ignored_lines": page_ignored_lines,
                "absolute_rank_anchor": page_absolute_rank_anchor,
                "absolute_rank_anchor_source": page_absolute_rank_anchor_source,
                "absolute_rank_base": page_absolute_rank_base,
                "absolute_rank_base_source": page_absolute_rank_base_source,
            }
        )
        parsed_pages.append(page_entries)
        previous_page_entries = [_strip_internal_entry_fields(entry) for entry in page_entries]

    parsed_pages, page_metadata = _retrofit_blue_archive_absolute_page_ranks(
        parsed_pages=parsed_pages,
        page_metadata=page_metadata,
    )
    parsed_pages, page_metadata = _prune_blue_archive_sparse_rank_violation_pages(
        parsed_pages=parsed_pages,
        page_metadata=page_metadata,
    )
    page_summaries = _build_capture_page_summaries(
        parsed_pages=parsed_pages,
        page_metadata=page_metadata,
    )
    entries: list[dict[str, Any]] = []
    seen_ranks: set[int] = set()
    for page_entries in parsed_pages:
        entries.extend(
            _strip_internal_entry_fields(entry)
            for entry in page_entries
            if entry["rank"] not in seen_ranks
        )
        seen_ranks.update(
            entry["rank"]
            for entry in page_entries
            if isinstance(entry.get("rank"), int)
        )

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


def _strip_internal_entry_fields(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in entry.items()
        if not key.startswith("_")
    }


def _retrofit_blue_archive_absolute_page_ranks(
    *,
    parsed_pages: list[list[dict[str, Any]]],
    page_metadata: list[dict[str, Any]],
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    if len(parsed_pages) <= 1 or len(parsed_pages) != len(page_metadata):
        return parsed_pages, page_metadata

    anchor_page_index, anchor_first_rank = _select_blue_archive_absolute_retrofit_anchor(
        parsed_pages=parsed_pages,
        page_metadata=page_metadata,
    )
    if anchor_page_index is None or anchor_first_rank is None:
        return parsed_pages, page_metadata

    adjusted_pages: list[list[dict[str, Any]]] = [
        [dict(entry) for entry in page_entries]
        for page_entries in parsed_pages
    ]
    adjusted_metadata = [dict(metadata) for metadata in page_metadata]
    first_ranks: list[int | None] = [None] * len(adjusted_pages)
    first_ranks[anchor_page_index] = anchor_first_rank

    for index in range(anchor_page_index, 0, -1):
        current_first_rank = first_ranks[index]
        previous_page_entries = adjusted_pages[index - 1]
        current_page_entries = adjusted_pages[index]
        if current_first_rank is None or not previous_page_entries or not current_page_entries:
            continue
        overlap_count = _count_overlap_alignment_entries(
            previous_page_entries=previous_page_entries,
            current_page_entries=current_page_entries,
        )
        if overlap_count > 0:
            previous_last_rank = current_first_rank + overlap_count - 1
        else:
            previous_last_rank = current_first_rank - 1
        first_ranks[index - 1] = previous_last_rank - len(previous_page_entries) + 1

    for index in range(anchor_page_index + 1, len(adjusted_pages)):
        previous_first_rank = first_ranks[index - 1]
        previous_page_entries = adjusted_pages[index - 1]
        current_page_entries = adjusted_pages[index]
        if previous_first_rank is None or not previous_page_entries or not current_page_entries:
            continue
        previous_last_rank = previous_first_rank + len(previous_page_entries) - 1
        overlap_count = _count_overlap_alignment_entries(
            previous_page_entries=previous_page_entries,
            current_page_entries=current_page_entries,
        )
        if overlap_count > 0:
            first_ranks[index] = previous_last_rank - overlap_count + 1
        else:
            first_ranks[index] = previous_last_rank + 1

    for index, first_rank in enumerate(first_ranks):
        page_entries = adjusted_pages[index]
        if first_rank is None or first_rank <= 100 or not page_entries:
            continue
        for offset, entry in enumerate(page_entries):
            entry["rank"] = first_rank + offset
        if adjusted_metadata[index].get("absolute_rank_base") is None:
            adjusted_metadata[index]["absolute_rank_base"] = first_rank
            adjusted_metadata[index]["absolute_rank_base_source"] = "retrofit"

    return adjusted_pages, adjusted_metadata


def _select_blue_archive_absolute_retrofit_anchor(
    *,
    parsed_pages: list[list[dict[str, Any]]],
    page_metadata: list[dict[str, Any]],
) -> tuple[int | None, int | None]:
    candidates: list[tuple[int, int, int, str]] = []
    source_priority = {
        "row_base": 3,
        "original": 2,
        "prepared": 1,
    }
    for index, metadata in enumerate(page_metadata):
        base = metadata.get("absolute_rank_base")
        base_source = metadata.get("absolute_rank_base_source")
        anchor = metadata.get("absolute_rank_anchor")
        anchor_source = metadata.get("absolute_rank_anchor_source")
        if isinstance(base, int) and base > 100:
            candidates.append((index, base, source_priority.get(str(base_source), 0), str(base_source)))
        if isinstance(anchor, int) and anchor > 100:
            candidates.append((index, anchor, source_priority.get(str(anchor_source), 0), str(anchor_source)))
    if not candidates:
        return None, None

    scored_candidates: list[tuple[int, int, int, int, int]] = []
    for index, anchor_rank, priority, _source in candidates:
        predicted_first_ranks = _simulate_blue_archive_retrofit_first_ranks(
            parsed_pages=parsed_pages,
            anchor_page_index=index,
            anchor_first_rank=anchor_rank,
        )
        disagreement_penalty = 0
        matched_pages = 0
        for page_index, metadata in enumerate(page_metadata):
            predicted = predicted_first_ranks[page_index]
            if predicted is None:
                continue
            expected_values = [
                value
                for value in (
                    metadata.get("absolute_rank_base"),
                    metadata.get("absolute_rank_anchor"),
                )
                if isinstance(value, int) and value > 100
            ]
            if not expected_values:
                continue
            disagreement_penalty += min(abs(predicted - value) for value in expected_values)
            matched_pages += 1
        scored_candidates.append(
            (
                disagreement_penalty,
                -matched_pages,
                -priority,
                -anchor_rank,
                index,
            )
        )

    scored_candidates.sort()
    _, _, _, negative_anchor_rank, index = scored_candidates[0]
    return index, -negative_anchor_rank


def _simulate_blue_archive_retrofit_first_ranks(
    *,
    parsed_pages: list[list[dict[str, Any]]],
    anchor_page_index: int,
    anchor_first_rank: int,
) -> list[int | None]:
    first_ranks: list[int | None] = [None] * len(parsed_pages)
    first_ranks[anchor_page_index] = anchor_first_rank

    for index in range(anchor_page_index, 0, -1):
        current_first_rank = first_ranks[index]
        previous_page_entries = parsed_pages[index - 1]
        current_page_entries = parsed_pages[index]
        if current_first_rank is None or not previous_page_entries or not current_page_entries:
            continue
        overlap_count = _count_overlap_alignment_entries(
            previous_page_entries=previous_page_entries,
            current_page_entries=current_page_entries,
        )
        if overlap_count > 0:
            previous_last_rank = current_first_rank + overlap_count - 1
        else:
            previous_last_rank = current_first_rank - 1
        first_ranks[index - 1] = previous_last_rank - len(previous_page_entries) + 1

    for index in range(anchor_page_index + 1, len(parsed_pages)):
        previous_first_rank = first_ranks[index - 1]
        previous_page_entries = parsed_pages[index - 1]
        current_page_entries = parsed_pages[index]
        if previous_first_rank is None or not previous_page_entries or not current_page_entries:
            continue
        previous_last_rank = previous_first_rank + len(previous_page_entries) - 1
        overlap_count = _count_overlap_alignment_entries(
            previous_page_entries=previous_page_entries,
            current_page_entries=current_page_entries,
        )
        if overlap_count > 0:
            first_ranks[index] = previous_last_rank - overlap_count + 1
        else:
            first_ranks[index] = previous_last_rank + 1

    return first_ranks


def _build_capture_page_summaries(
    *,
    parsed_pages: list[list[dict[str, Any]]],
    page_metadata: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    page_summaries: list[dict[str, Any]] = []
    previous_page_ranks: set[int] | None = None
    for page_entries, metadata in zip(parsed_pages, page_metadata):
        current_page_ranks = {
            entry["rank"]
            for entry in page_entries
            if isinstance(entry.get("rank"), int)
        }
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
                "page_index": metadata["page_index"],
                "image_path": metadata["image_path"],
                "entry_count": len(page_entries),
                "ignored_line_count": len(metadata["ignored_lines"]),
                "ignored_line_reasons": summarize_ignored_lines(metadata["ignored_lines"]),
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
                "absolute_rank_anchor": metadata["absolute_rank_anchor"],
                "absolute_rank_anchor_source": metadata["absolute_rank_anchor_source"],
                "absolute_rank_base": metadata["absolute_rank_base"],
                "absolute_rank_base_source": metadata["absolute_rank_base_source"],
            }
        )
        previous_page_ranks = current_page_ranks
    return page_summaries


def _prune_blue_archive_sparse_rank_violation_pages(
    *,
    parsed_pages: list[list[dict[str, Any]]],
    page_metadata: list[dict[str, Any]],
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    if len(parsed_pages) <= 1 or len(parsed_pages) != len(page_metadata):
        return parsed_pages, page_metadata

    adjusted_pages: list[list[dict[str, Any]]] = []
    adjusted_metadata: list[dict[str, Any]] = []
    previous_kept_entries: list[dict[str, Any]] = []

    for page_entries, metadata in zip(parsed_pages, page_metadata):
        if not page_entries:
            adjusted_pages.append(page_entries)
            adjusted_metadata.append(metadata)
            continue

        if (
            previous_kept_entries
            and _is_blue_archive_like_page_entries(previous_kept_entries)
            and _is_blue_archive_like_page_entries(page_entries)
            and _should_drop_sparse_blue_archive_page(
                previous_page_entries=previous_kept_entries,
                current_page_entries=page_entries,
                metadata=metadata,
            )
        ):
            adjusted_pages.append([])
            adjusted_metadata.append(metadata)
            continue

        adjusted_pages.append(page_entries)
        adjusted_metadata.append(metadata)
        previous_kept_entries = page_entries

    return adjusted_pages, adjusted_metadata


def _is_blue_archive_like_page_entries(
    page_entries: list[dict[str, Any]],
) -> bool:
    if not page_entries:
        return False
    return all(
        isinstance(entry.get("player_name"), str)
        and entry["player_name"] in DIFFICULTY_PRIORITY
        and isinstance(entry.get("score"), int)
        for entry in page_entries
    )


def _should_drop_sparse_blue_archive_page(
    *,
    previous_page_entries: list[dict[str, Any]],
    current_page_entries: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> bool:
    current_absolute_base = metadata.get("absolute_rank_base")
    if isinstance(current_absolute_base, int) and current_absolute_base > 100:
        return False

    overlap_count = _count_overlap_alignment_entries(
        previous_page_entries=previous_page_entries,
        current_page_entries=current_page_entries,
    )
    previous_ranks = [
        entry["rank"]
        for entry in previous_page_entries
        if isinstance(entry.get("rank"), int)
    ]
    current_ranks = [
        entry["rank"]
        for entry in current_page_entries
        if isinstance(entry.get("rank"), int)
    ]
    if not previous_ranks or not current_ranks:
        return False

    previous_first = min(previous_ranks)
    previous_last = max(previous_ranks)
    current_first = min(current_ranks)

    if len(current_ranks) <= 1 and overlap_count == 0:
        return True
    if overlap_count == 0 and current_first > previous_last + max(2, len(current_ranks) + 1):
        return True
    if overlap_count == 0 and current_first < previous_first:
        return True
    return False


def _count_overlap_alignment_entries(
    *,
    previous_page_entries: list[dict[str, Any]],
    current_page_entries: list[dict[str, Any]],
) -> int:
    if not (
        _supports_overlap_rank_alignment(previous_page_entries)
        and _supports_overlap_rank_alignment(current_page_entries)
    ):
        return 0
    overlap_alignment = _find_overlap_rank_alignment(
        previous_page_entries=previous_page_entries,
        current_page_entries=current_page_entries,
    )
    if overlap_alignment is None:
        return 0
    return overlap_alignment[2]


def _realign_overlapping_page_entry_ranks(
    *,
    previous_page_entries: list[dict[str, Any]],
    current_page_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not previous_page_entries or not current_page_entries:
        return current_page_entries
    if not (
        _supports_overlap_rank_alignment(previous_page_entries)
        and _supports_overlap_rank_alignment(current_page_entries)
    ):
        return current_page_entries

    overlap_alignment = _find_overlap_rank_alignment(
        previous_page_entries=previous_page_entries,
        current_page_entries=current_page_entries,
    )
    if overlap_alignment is None:
        continuation_base_rank = _resolve_non_overlap_continuation_base_rank(
            previous_page_entries=previous_page_entries,
            current_page_entries=current_page_entries,
        )
        if continuation_base_rank is None:
            return current_page_entries
        return [
            {
                **entry,
                "rank": continuation_base_rank + index,
            }
            for index, entry in enumerate(current_page_entries)
        ]

    base_rank = _resolve_overlap_alignment_base_rank(
        previous_page_entries=previous_page_entries,
        current_page_entries=current_page_entries,
        overlap_alignment=overlap_alignment,
    )
    return [
        {
            **entry,
            "rank": base_rank + index,
        }
        for index, entry in enumerate(current_page_entries)
    ]


def _supports_overlap_rank_alignment(entries: list[dict[str, Any]]) -> bool:
    if not entries:
        return False
    return all(
        isinstance(entry.get("rank"), int)
        and isinstance(entry.get("score"), int)
        and isinstance(entry.get("player_name"), str)
        and entry["player_name"] in DIFFICULTY_PRIORITY
        for entry in entries
    )


def _find_overlap_rank_alignment(
    *,
    previous_page_entries: list[dict[str, Any]],
    current_page_entries: list[dict[str, Any]],
) -> tuple[int, int, int] | None:
    previous_keys = [
        _build_overlap_rank_alignment_key(entry)
        for entry in previous_page_entries
    ]
    current_keys = [
        _build_overlap_rank_alignment_key(entry)
        for entry in current_page_entries
    ]
    best_alignment: tuple[int, int, int] | None = None
    for previous_anchor_index, previous_key in enumerate(previous_keys):
        for current_anchor_index, current_key in enumerate(current_keys):
            if previous_key != current_key:
                continue
            overlap_size = 1
            while (
                previous_anchor_index + overlap_size < len(previous_keys)
                and current_anchor_index + overlap_size < len(current_keys)
                and previous_keys[previous_anchor_index + overlap_size]
                == current_keys[current_anchor_index + overlap_size]
            ):
                overlap_size += 1
            candidate = (previous_anchor_index, current_anchor_index, overlap_size)
            if best_alignment is None:
                best_alignment = candidate
                continue
            _, _, best_overlap_size = best_alignment
            if overlap_size > best_overlap_size:
                best_alignment = candidate
                continue
            if overlap_size == best_overlap_size and previous_anchor_index > best_alignment[0]:
                best_alignment = candidate
                continue
            if (
                overlap_size == best_overlap_size
                and previous_anchor_index == best_alignment[0]
                and current_anchor_index < best_alignment[1]
            ):
                best_alignment = candidate
    return best_alignment


def _resolve_overlap_alignment_base_rank(
    *,
    previous_page_entries: list[dict[str, Any]],
    current_page_entries: list[dict[str, Any]],
    overlap_alignment: tuple[int, int, int],
) -> int:
    previous_anchor_index, current_anchor_index, overlap_size = overlap_alignment
    anchor_rank = previous_page_entries[previous_anchor_index]["rank"]
    base_rank = anchor_rank - current_anchor_index
    if current_anchor_index != 0 or overlap_size != 1:
        return base_rank

    previous_keys = [
        _build_overlap_rank_alignment_key(entry)
        for entry in previous_page_entries
    ]
    current_first_key = _build_overlap_rank_alignment_key(current_page_entries[0])
    if previous_keys[-1] != current_first_key:
        return base_rank

    if (
        previous_anchor_index == len(previous_page_entries) - 1
        and len(current_page_entries) < len(previous_page_entries)
    ):
        return previous_page_entries[-1]["rank"] + 1

    trailing_duplicate_count = 0
    for previous_key in reversed(previous_keys):
        if previous_key != current_first_key:
            break
        trailing_duplicate_count += 1
    if trailing_duplicate_count <= 1:
        return base_rank
    return previous_page_entries[-1]["rank"] + 1


def _resolve_non_overlap_continuation_base_rank(
    *,
    previous_page_entries: list[dict[str, Any]],
    current_page_entries: list[dict[str, Any]],
) -> int | None:
    current_ranks = [entry["rank"] for entry in current_page_entries]
    if current_ranks != list(range(1, len(current_page_entries) + 1)):
        return None

    previous_scores = [int(entry["score"]) for entry in previous_page_entries]
    current_scores = [int(entry["score"]) for entry in current_page_entries]
    if not previous_scores or not current_scores:
        return None

    if current_scores[0] > previous_scores[-1]:
        return None

    return previous_page_entries[-1]["rank"] + 1


def _build_overlap_rank_alignment_key(entry: dict[str, Any]) -> tuple[str, int]:
    return (str(entry["player_name"]), int(entry["score"]))


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


def enrich_parsed_capture_payload_collector_details(
    parsed_payload: ParsedCapturePayload,
    *,
    extra_details: dict[str, Any] | None = None,
) -> ParsedCapturePayload:
    note = parsed_payload.mock_payload.snapshot.get("note")
    if not isinstance(note, str) or not note.strip():
        return parsed_payload

    merged_note = _merge_collector_details_into_note(note, extra_details)
    if merged_note == note:
        return parsed_payload

    return ParsedCapturePayload(
        mock_payload=MockImportPayload(
            season=parsed_payload.mock_payload.season,
            snapshot={
                **parsed_payload.mock_payload.snapshot,
                "note": merged_note,
            },
            entries=parsed_payload.mock_payload.entries,
        ),
        ignored_lines=parsed_payload.ignored_lines,
        page_summaries=parsed_payload.page_summaries,
    )


def rebuild_parsed_capture_payload_snapshot_note(
    parsed_payload: ParsedCapturePayload,
    *,
    snapshot: dict[str, Any],
    capture: dict[str, Any] | None,
    extra_details: dict[str, Any] | None = None,
    ocr_stop_recommendation_override: dict[str, Any] | None = None,
) -> ParsedCapturePayload:
    note = _build_snapshot_note_with_collector_summary(
        snapshot=snapshot,
        capture=capture,
        ignored_lines=parsed_payload.ignored_lines,
        page_summaries=parsed_payload.page_summaries,
        extra_collector_details=extra_details,
        ocr_stop_recommendation_override=ocr_stop_recommendation_override,
    )
    if note == parsed_payload.mock_payload.snapshot.get("note"):
        return parsed_payload

    return ParsedCapturePayload(
        mock_payload=MockImportPayload(
            season=parsed_payload.mock_payload.season,
            snapshot={
                **parsed_payload.mock_payload.snapshot,
                "note": note,
            },
            entries=parsed_payload.mock_payload.entries,
        ),
        ignored_lines=parsed_payload.ignored_lines,
        page_summaries=parsed_payload.page_summaries,
    )


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
    last_page_header_ignored_count = sum(
        last_page_ignored_reason_counts.get(reason, 0)
        for reason in ("header_line", "pagination_line")
    )
    last_page_malformed_entry_count = last_page_ignored_reason_counts.get(
        "malformed_entry_line",
        0,
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
        and last_page_entry_count <= 3
        and last_page_header_ignored_count > 0
    ):
        hints.append(
            {
                "reason": "header_repeat_last_page",
                "page_index": last_page["page_index"],
                "ignored_header_count": last_page_header_ignored_count,
                "entry_count": last_page_entry_count,
            }
        )

    if (
        len(page_summaries) >= 2
        and last_page_malformed_entry_count > 0
        and last_page_malformed_entry_count >= max(1, last_page_entry_count)
    ):
        hints.append(
            {
                "reason": "malformed_last_page",
                "page_index": last_page["page_index"],
                "malformed_entry_count": last_page_malformed_entry_count,
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
        "header_repeat_last_page": "hard",
        "malformed_last_page": "hard",
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
    extra_collector_details: dict[str, Any] | None = None,
    ocr_stop_recommendation_override: dict[str, Any] | None = None,
) -> str | None:
    existing_note = snapshot.get("note")
    existing_note_text = _strip_collector_note_lines(existing_note)

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

    ocr_stop_recommendation = (
        ocr_stop_recommendation_override
        if ocr_stop_recommendation_override is not None
        else build_ocr_stop_recommendation(build_ocr_stop_hints(page_summaries))
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
    collector_details = _build_collector_details_line(
        page_summaries,
        existing_note=existing_note if isinstance(existing_note, str) else None,
        extra_details=extra_collector_details,
        ocr_stop_recommendation_override=ocr_stop_recommendation_override,
    )
    if existing_note_text:
        note = "\n".join(
            line
            for line in (existing_note_text, collector_summary, collector_details)
            if line
        )
        return _fit_snapshot_note(note, base_note=existing_note_text, summary=collector_summary)
    note = "\n".join(line for line in (collector_summary, collector_details) if line)
    return _fit_snapshot_note(note, base_note=None, summary=collector_summary)


def _build_ignored_reason_count_map(
    ignored_line_reasons: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        str(row["reason"]): int(row["count"])
        for row in ignored_line_reasons
        if "reason" in row and "count" in row
    }


def _build_collector_details_line(
    page_summaries: list[dict[str, Any]],
    *,
    existing_note: str | None = None,
    extra_details: dict[str, Any] | None = None,
    ocr_stop_recommendation_override: dict[str, Any] | None = None,
) -> str | None:
    payload = _build_collector_details_payload(
        page_summaries,
        existing_note=existing_note,
        extra_details=extra_details,
        ocr_stop_recommendation_override=ocr_stop_recommendation_override,
    )
    if not payload:
        return None

    return COLLECTOR_JSON_PREFIX + json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _build_collector_details_payload(
    page_summaries: list[dict[str, Any]],
    *,
    existing_note: str | None = None,
    extra_details: dict[str, Any] | None = None,
    ocr_stop_recommendation_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = _extract_collector_details_payload(existing_note)
    ocr_stop_hints = build_ocr_stop_hints(page_summaries)
    ocr_stop_recommendation = (
        ocr_stop_recommendation_override
        if ocr_stop_recommendation_override is not None
        else build_ocr_stop_recommendation(ocr_stop_hints)
    )
    if extra_details:
        payload.update(_compact_extra_collector_details(extra_details))
    else:
        payload = {
            "p": len(page_summaries),
        }
        if ocr_stop_recommendation["should_stop"]:
            payload["o"] = ocr_stop_recommendation["primary_reason"]
    blue_archive_rank_debug = _compact_blue_archive_rank_debug(page_summaries)
    if blue_archive_rank_debug:
        payload["ba"] = blue_archive_rank_debug
    if extra_details:
        payload.setdefault("p", len(page_summaries))
        if ocr_stop_recommendation["should_stop"]:
            payload.setdefault("o", ocr_stop_recommendation["primary_reason"])
    return payload


def _merge_collector_details_into_note(
    note: str,
    extra_details: dict[str, Any] | None = None,
) -> str:
    base_note = _strip_collector_details_lines(note)
    existing_payload = _extract_collector_details_payload(note)
    if extra_details:
        existing_payload.update(_compact_extra_collector_details(extra_details))

    collector_details = None
    if existing_payload:
        collector_details = COLLECTOR_JSON_PREFIX + json.dumps(
            existing_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    merged_note = "\n".join(
        line for line in (base_note, collector_details) if line
    )
    return _fit_snapshot_note(merged_note, base_note=base_note, summary=None)


def _fit_snapshot_note(
    note: str | None,
    *,
    base_note: str | None,
    summary: str | None,
) -> str | None:
    if note is None:
        return None
    if len(note) <= SNAPSHOT_NOTE_MAX_LENGTH:
        return note

    compact_candidates = [
        "\n".join(line for line in (base_note, summary) if line),
        summary,
        base_note,
    ]
    for candidate in compact_candidates:
        if candidate and len(candidate) <= SNAPSHOT_NOTE_MAX_LENGTH:
            return candidate

    fallback = next((candidate for candidate in compact_candidates if candidate), "")
    if not fallback:
        return None
    return fallback[: SNAPSHOT_NOTE_MAX_LENGTH - 3].rstrip() + "..."


def _compact_extra_collector_details(extra_details: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    pipeline_stop = extra_details.get("pipeline_stop_recommendation")
    if isinstance(pipeline_stop, dict):
        compact["psr"] = {
            "s": pipeline_stop.get("should_stop"),
            "l": pipeline_stop.get("level"),
            "src": pipeline_stop.get("source"),
            "r": pipeline_stop.get("primary_reason"),
        }
    stop_policy = extra_details.get("stop_policy")
    if isinstance(stop_policy, dict):
        compact["sp"] = {
            "m": stop_policy.get("min_pages_before_ocr_stop"),
            "t": stop_policy.get("soft_stop_repeat_threshold"),
        }
    return compact


def _compact_blue_archive_rank_debug(
    page_summaries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not page_summaries:
        return None
    first_page = page_summaries[0]
    anchor = first_page.get("absolute_rank_anchor")
    source = first_page.get("absolute_rank_anchor_source")
    base = first_page.get("absolute_rank_base")
    base_source = first_page.get("absolute_rank_base_source")
    first_rank = first_page.get("first_rank")
    last_rank = first_page.get("last_rank")
    if anchor is None and source is None and base is None and base_source is None:
        return None
    return {
        "a": anchor,
        "s": source,
        "b": base,
        "bs": base_source,
        "f": first_rank,
        "l": last_rank,
    }


def _strip_collector_note_lines(note: object) -> str:
    if not isinstance(note, str):
        return ""

    return "\n".join(
        line.strip()
        for line in note.splitlines()
        if line.strip()
        and not line.strip().startswith(COLLECTOR_SUMMARY_PREFIX)
        and not line.strip().startswith(COLLECTOR_JSON_PREFIX)
    )


def _strip_collector_details_lines(note: str) -> str:
    return "\n".join(
        line.strip()
        for line in note.splitlines()
        if line.strip() and not line.strip().startswith(COLLECTOR_JSON_PREFIX)
    )


def _extract_collector_details_payload(note: str | None) -> dict[str, Any]:
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
    inferred_path = _resolve_ocr_sidecar_path(base_dir, page)
    if not inferred_path.exists():
        raise MockImportError(
            "ocr_text_path가 없고 기본 OCR sidecar(.txt)도 찾을 수 없습니다: "
            f"{inferred_path}"
        )
    return inferred_path


def _resolve_ocr_sidecar_path(base_dir: Path, page: CapturePage) -> Path:
    if page.ocr_text_path is not None:
        return (base_dir / page.ocr_text_path).resolve()
    image_path = (base_dir / page.image_path).resolve()
    return image_path.with_suffix(".txt")


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
        return _load_tesseract_ocr_text(
            base_dir=base_dir,
            page=page,
            image_path=image_path,
            ocr=ocr,
        )

    raise MockImportError(f"지원하지 않는 OCR provider입니다: {ocr.provider}")


def _load_tesseract_ocr_text(
    *,
    base_dir: Path,
    page: CapturePage,
    image_path: Path,
    ocr: OcrConfig,
) -> str:
    sidecar_path = _resolve_ocr_sidecar_path(base_dir, page)
    if ocr.reuse_cached_sidecar and sidecar_path.exists():
        return sidecar_path.read_text(encoding="utf-8")

    ocr_text = _run_tesseract_ocr(image_path, ocr)
    if ocr.persist_sidecar:
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(ocr_text + "\n", encoding="utf-8")
    return ocr_text


def _run_tesseract_ocr(image_path: Path, ocr: OcrConfig) -> str:
    prepared_image_path, cleanup = _prepare_image_for_ocr(image_path, ocr)
    try:
        return _run_tesseract_command(
            prepared_image_path=prepared_image_path,
            original_image_path=image_path,
            ocr=ocr,
            output_kind="text",
        )
    finally:
        cleanup()


def _run_tesseract_tsv(image_path: Path, ocr: OcrConfig) -> str:
    prepared_image_path, cleanup = _prepare_image_for_ocr(image_path, ocr)
    try:
        return _run_tesseract_command(
            prepared_image_path=prepared_image_path,
            original_image_path=image_path,
            ocr=ocr,
            output_kind="tsv",
        )
    finally:
        cleanup()


def _run_tesseract_command(
    *,
    prepared_image_path: Path,
    original_image_path: Path,
    ocr: OcrConfig,
    output_kind: str,
) -> str:
    command = ocr.command or DEFAULT_TESSERACT_COMMAND
    if shutil.which(command) is None:
        raise MockImportError(
            "tesseract 명령을 찾을 수 없습니다. "
            f"command={command!r}, image_path={original_image_path}"
        )

    args = [command, _resolve_tesseract_input_path(command, prepared_image_path), "stdout"]
    if ocr.language:
        args.extend(["-l", ocr.language])
    if ocr.psm is not None:
        args.extend(["--psm", str(ocr.psm)])
    if ocr.extra_args:
        args.extend(ocr.extra_args)
    if output_kind == "tsv":
        args.append("tsv")

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise MockImportError(
            f"tesseract 실행에 실패했습니다: command={command!r}, image_path={original_image_path}"
        ) from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        stderr = stderr or "unknown error"
        raise MockImportError(
            f"tesseract {output_kind} 추출에 실패했습니다. "
            f"image_path={original_image_path}, returncode={result.returncode}, stderr={stderr}"
        )

    if not stdout:
        raise MockImportError(
            f"tesseract {output_kind} 결과가 비어 있습니다: image_path={original_image_path}"
        )
    return stdout


def _resolve_tesseract_input_path(command: str, image_path: Path) -> str:
    path_str = str(image_path)
    if not command.lower().endswith(".exe") or not path_str.startswith("/"):
        return path_str
    try:
        result = subprocess.run(
            ["wslpath", "-w", path_str],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return path_str
    converted = (result.stdout or "").strip()
    if result.returncode != 0 or not converted:
        return path_str
    return converted


def _prepare_image_for_ocr(
    image_path: Path,
    ocr: OcrConfig,
) -> tuple[Path, callable]:
    if ocr.crop is None:
        return image_path, (lambda: None)

    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise MockImportError(
            "ocr.crop을 사용하려면 Pillow가 필요합니다. requirements를 다시 설치하세요."
        ) from exc

    if ocr.crop is None and ocr.upscale_ratio == 1.0:
        return image_path, (lambda: None)

    with Image.open(image_path) as image:
        width, height = image.size
        processed = image
        if ocr.crop is not None:
            left = max(0, int(width * ocr.crop.left_ratio))
            top = max(0, int(height * ocr.crop.top_ratio))
            right = min(width, int(width * ocr.crop.right_ratio))
            bottom = min(height, int(height * ocr.crop.bottom_ratio))
            if left >= right or top >= bottom:
                raise MockImportError(
                    f"ocr.crop이 유효한 영역을 만들지 못했습니다: image_path={image_path}"
                )
            processed = processed.crop((left, top, right, bottom))

        processed = ImageOps.grayscale(processed)
        processed = ImageOps.autocontrast(processed)
        if ocr.upscale_ratio > 1.0:
            processed = processed.resize(
                (
                    max(1, int(processed.width * ocr.upscale_ratio)),
                    max(1, int(processed.height * ocr.upscale_ratio)),
                ),
                Image.Resampling.LANCZOS,
            )
        with tempfile.NamedTemporaryFile(
            suffix=image_path.suffix,
            prefix="plana-ocr-crop-",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
        processed.save(temp_path)

    def cleanup() -> None:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass

    return temp_path, cleanup


def _build_ocr_config(
    raw_ocr: Any,
    *,
    provider_override: str | None,
    command_override: str | None,
    language_override: str | None,
    psm_override: int | None,
    extra_args_override: list[str] | None,
    reuse_cached_sidecar_override: bool | None,
    persist_sidecar_override: bool | None,
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

    raw_extra_args = (
        extra_args_override
        if extra_args_override is not None
        else ocr_mapping.get("extra_args", [])
    )
    if raw_extra_args is None:
        raw_extra_args = []
    if not isinstance(raw_extra_args, list) or not all(
        isinstance(arg, str) and arg.strip() for arg in raw_extra_args
    ):
        raise MockImportError("ocr.extra_args는 비어 있지 않은 문자열 배열이어야 합니다.")
    extra_args = tuple(raw_extra_args)

    if provider == OCR_PROVIDER_TESSERACT and command is None:
        command = DEFAULT_TESSERACT_COMMAND

    raw_reuse_cached_sidecar = (
        reuse_cached_sidecar_override
        if reuse_cached_sidecar_override is not None
        else ocr_mapping.get("reuse_cached_sidecar", False)
    )
    raw_persist_sidecar = (
        persist_sidecar_override
        if persist_sidecar_override is not None
        else ocr_mapping.get("persist_sidecar", provider == OCR_PROVIDER_TESSERACT)
    )
    reuse_cached_sidecar = _parse_boolean_option(
        raw_reuse_cached_sidecar,
        "ocr.reuse_cached_sidecar",
    )
    persist_sidecar = _parse_boolean_option(
        raw_persist_sidecar,
        "ocr.persist_sidecar",
    )

    return OcrConfig(
        provider=provider,
        command=command,
        language=language,
        psm=psm,
        extra_args=extra_args,
        crop=_build_ocr_crop(ocr_mapping.get("crop")),
        upscale_ratio=_build_ocr_upscale_ratio(ocr_mapping.get("upscale_ratio", 1.0)),
        reuse_cached_sidecar=reuse_cached_sidecar,
        persist_sidecar=persist_sidecar,
    )


def _build_ocr_crop(raw_crop: Any) -> OcrCrop | None:
    if raw_crop is None:
        return None

    crop = _require_mapping(raw_crop, "ocr.crop")
    required_keys = ("left_ratio", "top_ratio", "right_ratio", "bottom_ratio")
    _require_fields(crop, required_keys, "ocr.crop")

    parsed: dict[str, float] = {}
    for key in required_keys:
        try:
            parsed[key] = float(crop[key])
        except (TypeError, ValueError) as exc:
            raise MockImportError(f"ocr.crop.{key}는 0~1 사이 숫자여야 합니다.") from exc
        if not (0.0 <= parsed[key] <= 1.0):
            raise MockImportError(f"ocr.crop.{key}는 0~1 사이 숫자여야 합니다.")

    if parsed["left_ratio"] >= parsed["right_ratio"]:
        raise MockImportError("ocr.crop.left_ratio는 right_ratio보다 작아야 합니다.")
    if parsed["top_ratio"] >= parsed["bottom_ratio"]:
        raise MockImportError("ocr.crop.top_ratio는 bottom_ratio보다 작아야 합니다.")

    return OcrCrop(
        left_ratio=parsed["left_ratio"],
        top_ratio=parsed["top_ratio"],
        right_ratio=parsed["right_ratio"],
        bottom_ratio=parsed["bottom_ratio"],
    )


def _build_ocr_upscale_ratio(raw_value: Any) -> float:
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise MockImportError("ocr.upscale_ratio는 1 이상의 숫자여야 합니다.") from exc
    if parsed < 1.0:
        raise MockImportError("ocr.upscale_ratio는 1 이상의 숫자여야 합니다.")
    return parsed


def _parse_tesseract_layout_entries(
    *,
    image_path: Path,
    ocr: OcrConfig,
    default_ocr_confidence: float | None,
    page_index: int,
) -> list[dict[str, Any]]:
    prefer_blue_archive_fixed_rows = _is_blue_archive_fixed_layout_image(
        image_path=image_path,
        ocr=ocr,
    )
    best_blue_archive_entries: list[dict[str, Any]] = []
    for attempt_ocr in _iter_tesseract_layout_ocr_attempts(ocr):
        prepared_image_path, cleanup = _prepare_image_for_ocr(image_path, attempt_ocr)
        try:
            recovered_blue_archive_ranks: list[int] | None = None

            def get_recovered_blue_archive_ranks() -> list[int] | None:
                nonlocal recovered_blue_archive_ranks
                if not prefer_blue_archive_fixed_rows:
                    return None
                if recovered_blue_archive_ranks is None:
                    recovered_blue_archive_ranks = _recover_blue_archive_original_row_ranks(
                        prepared_image_path=prepared_image_path,
                        image_path=image_path,
                        ocr=attempt_ocr,
                    )
                return recovered_blue_archive_ranks

            if prefer_blue_archive_fixed_rows:
                entries = _parse_blue_archive_fixed_rows(
                    prepared_image_path=prepared_image_path,
                    image_path=image_path,
                    ocr=attempt_ocr,
                    default_ocr_confidence=default_ocr_confidence,
                    page_index=page_index,
                )
                if entries:
                    normalized_entries = _normalize_tesseract_page_entry_ranks(entries)
                    best_blue_archive_entries = _select_preferred_blue_archive_attempt_entries(
                        current_entries=best_blue_archive_entries,
                        candidate_entries=normalized_entries,
                    )
                    if _is_sufficient_blue_archive_fixed_row_entries(normalized_entries):
                        return normalized_entries
                    if not _should_continue_blue_archive_layout_attempt(
                        entries=normalized_entries,
                        recovered_ranks=get_recovered_blue_archive_ranks(),
                    ):
                        return normalized_entries

            try:
                tsv_text = _run_tesseract_command(
                    prepared_image_path=prepared_image_path,
                    original_image_path=image_path,
                    ocr=attempt_ocr,
                    output_kind="tsv",
                )
            except MockImportError:
                continue

            words = _parse_tesseract_tsv_words(tsv_text)
            if not words:
                continue

            entries: list[dict[str, Any]] = []
            score_words = _find_layout_score_words(words)
            if score_words:
                for index, score_word in enumerate(score_words, start=1):
                    entry = _parse_tesseract_layout_card(
                        score_word=score_word,
                        all_words=words,
                        prepared_image_path=prepared_image_path,
                        image_path=image_path,
                        ocr=attempt_ocr,
                        default_ocr_confidence=default_ocr_confidence,
                        page_index=page_index,
                        fallback_rank=index,
                    )
                    if entry is not None:
                        entries.append(entry)

            if entries:
                if prefer_blue_archive_fixed_rows:
                    entries = _apply_blue_archive_original_row_ranks(
                        entries=entries,
                        recovered_ranks=get_recovered_blue_archive_ranks(),
                    )
                    normalized_entries = _normalize_tesseract_page_entry_ranks(entries)
                    best_blue_archive_entries = _select_preferred_blue_archive_attempt_entries(
                        current_entries=best_blue_archive_entries,
                        candidate_entries=normalized_entries,
                    )
                    if _should_continue_blue_archive_layout_attempt(
                        entries=normalized_entries,
                        recovered_ranks=get_recovered_blue_archive_ranks(),
                    ):
                        continue
                    return normalized_entries
                return _normalize_tesseract_page_entry_ranks(entries)

            for line_words in _group_tesseract_words_by_line(words):
                entry = _parse_tesseract_layout_line(
                    line_words=line_words,
                    image_path=image_path,
                    default_ocr_confidence=default_ocr_confidence,
                    page_index=page_index,
                )
                if entry is not None:
                    entries.append(entry)

            if entries:
                if prefer_blue_archive_fixed_rows:
                    entries = _apply_blue_archive_original_row_ranks(
                        entries=entries,
                        recovered_ranks=get_recovered_blue_archive_ranks(),
                    )
                    normalized_entries = _normalize_tesseract_page_entry_ranks(entries)
                    best_blue_archive_entries = _select_preferred_blue_archive_attempt_entries(
                        current_entries=best_blue_archive_entries,
                        candidate_entries=normalized_entries,
                    )
                    if _should_continue_blue_archive_layout_attempt(
                        entries=normalized_entries,
                        recovered_ranks=get_recovered_blue_archive_ranks(),
                    ):
                        continue
                    return normalized_entries
                return _normalize_tesseract_page_entry_ranks(entries)

            entries = _parse_blue_archive_fixed_rows(
                prepared_image_path=prepared_image_path,
                image_path=image_path,
                ocr=attempt_ocr,
                default_ocr_confidence=default_ocr_confidence,
                page_index=page_index,
            )
            if entries:
                normalized_entries = _normalize_tesseract_page_entry_ranks(entries)
                best_blue_archive_entries = _select_preferred_blue_archive_attempt_entries(
                    current_entries=best_blue_archive_entries,
                    candidate_entries=normalized_entries,
                )
                if not _should_continue_blue_archive_layout_attempt(
                    entries=normalized_entries,
                    recovered_ranks=get_recovered_blue_archive_ranks(),
                ):
                    return normalized_entries
        finally:
            cleanup()

    if best_blue_archive_entries:
        return best_blue_archive_entries
    return []


def _is_blue_archive_fixed_layout_image(
    *,
    image_path: Path,
    ocr: OcrConfig,
) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False

    try:
        with Image.open(image_path) as image:
            width, height = image.size
    except OSError:
        return False

    if width < 1000 or height < 450:
        return False

    aspect_ratio = width / height
    if not (1.70 <= aspect_ratio <= 2.35):
        return False

    crop = ocr.crop
    if crop is None:
        return False

    crop_width_ratio = crop.right_ratio - crop.left_ratio
    crop_height_ratio = crop.bottom_ratio - crop.top_ratio
    return (
        0.14 <= crop_width_ratio <= 0.30
        and 0.45 <= crop_height_ratio <= 0.70
        and 0.30 <= crop.left_ratio <= 0.45
        and 0.30 <= crop.top_ratio <= 0.40
    )


def _iter_tesseract_layout_ocr_attempts(ocr: OcrConfig) -> list[OcrConfig]:
    attempts = [ocr]
    if ocr.crop is None:
        return attempts

    crop_variants = [
        ocr.crop,
        OcrCrop(
            left_ratio=max(0.0, ocr.crop.left_ratio - 0.03),
            top_ratio=ocr.crop.top_ratio,
            right_ratio=min(1.0, ocr.crop.right_ratio + 0.02),
            bottom_ratio=ocr.crop.bottom_ratio,
        ),
        OcrCrop(
            left_ratio=max(0.0, ocr.crop.left_ratio - 0.08),
            top_ratio=max(0.0, ocr.crop.top_ratio - 0.01),
            right_ratio=min(1.0, ocr.crop.right_ratio + 0.01),
            bottom_ratio=ocr.crop.bottom_ratio,
        ),
        OcrCrop(
            left_ratio=min(1.0, ocr.crop.left_ratio + 0.02),
            top_ratio=ocr.crop.top_ratio,
            right_ratio=max(0.0, ocr.crop.right_ratio - 0.03),
            bottom_ratio=ocr.crop.bottom_ratio,
        ),
    ]

    seen: set[tuple[float, float, float, float]] = set()
    deduped_attempts: list[OcrConfig] = []
    for crop in crop_variants:
        key = (
            round(crop.left_ratio, 4),
            round(crop.top_ratio, 4),
            round(crop.right_ratio, 4),
            round(crop.bottom_ratio, 4),
        )
        if key in seen or crop.left_ratio >= crop.right_ratio:
            continue
        seen.add(key)
        deduped_attempts.append(
            OcrConfig(
                provider=ocr.provider,
                command=ocr.command,
                language=ocr.language,
                psm=ocr.psm,
                extra_args=ocr.extra_args,
                crop=crop,
                upscale_ratio=ocr.upscale_ratio,
                reuse_cached_sidecar=ocr.reuse_cached_sidecar,
                persist_sidecar=ocr.persist_sidecar,
            )
        )
    return deduped_attempts


def _parse_blue_archive_fixed_rows(
    *,
    prepared_image_path: Path,
    image_path: Path,
    ocr: OcrConfig,
    default_ocr_confidence: float | None,
    page_index: int,
) -> list[dict[str, Any]]:
    detected_row_bands = _detect_blue_archive_row_bands(prepared_image_path) or (
        (0.02, 0.31),
        (0.35, 0.65),
        (0.69, 0.98),
    )
    row_bands = _select_visible_blue_archive_row_bands(detected_row_bands)

    raw_rows: list[dict[str, Any]] = []
    detected_ranks: list[int | None] = []
    complete_row_ranks = True

    for row_index, (top_ratio, bottom_ratio) in enumerate(row_bands, start=1):
        rank, difficulty, score = _ocr_blue_archive_row_combined_fields(
            prepared_image_path=prepared_image_path,
            ocr=ocr,
            top_ratio=top_ratio,
            bottom_ratio=bottom_ratio,
            page_index=page_index,
        )

        original_image_rank = _ocr_blue_archive_row_rank_from_original_image(
            image_path=image_path,
            ocr=ocr,
            top_ratio=top_ratio,
            bottom_ratio=bottom_ratio,
        )
        if rank is None and original_image_rank is None:
            rank = _ocr_blue_archive_row_rank(
                prepared_image_path=prepared_image_path,
                ocr=ocr,
                top_ratio=top_ratio,
                bottom_ratio=bottom_ratio,
            )
        rank = _select_blue_archive_row_rank(
            prepared_rank=rank,
            original_rank=original_image_rank,
            visible_row_count=len(row_bands),
        )
        if rank is None:
            rank = _ocr_blue_archive_row_rank(
                prepared_image_path=prepared_image_path,
                ocr=ocr,
                top_ratio=top_ratio,
                bottom_ratio=bottom_ratio,
            )
            rank = _select_blue_archive_row_rank(
                prepared_rank=rank,
                original_rank=original_image_rank,
                visible_row_count=len(row_bands),
            )
        if difficulty is None:
            difficulty = _ocr_blue_archive_row_difficulty(
                prepared_image_path=prepared_image_path,
                ocr=ocr,
                top_ratio=top_ratio,
                bottom_ratio=bottom_ratio,
            )
        if score is None:
            score = _ocr_blue_archive_row_score(
                prepared_image_path=prepared_image_path,
                ocr=ocr,
                top_ratio=top_ratio,
                bottom_ratio=bottom_ratio,
                page_index=page_index,
            )

        if score is None:
            continue

        if rank is None:
            complete_row_ranks = False
        detected_ranks.append(rank)
        raw_rows.append(
            {
                "rank": rank if rank is not None else row_index,
                "score": score,
                "player_name": difficulty,
                "ocr_confidence": default_ocr_confidence,
                "raw_text": f"row={row_index} difficulty={difficulty} score={score}",
                "image_path": _build_entry_image_path(image_path),
                "is_valid": True,
                "validation_issue": None,
            }
        )

    if not raw_rows:
        return []

    page_difficulty = _resolve_blue_archive_page_difficulty(raw_rows)
    entries = [
        {
            **entry,
            "player_name": entry["player_name"] or page_difficulty,
        }
        for entry in raw_rows
        if entry["player_name"] is not None or page_difficulty is not None
    ]

    if not entries:
        return []

    resolved_ranks = _resolve_anchor_ranks(detected_ranks)
    absolute_rank_base = _resolve_blue_archive_absolute_rank_base_from_detected_ranks(
        detected_ranks
    )
    if absolute_rank_base is None:
        absolute_rank_base = _resolve_blue_archive_absolute_rank_base_from_original_rows(
            image_path=image_path,
            ocr=ocr,
            row_bands=row_bands,
        )
    absolute_rank_base_source: str | None = None
    absolute_rank_anchor_source: str | None = None
    if absolute_rank_base is not None:
        resolved_ranks = list(
            range(
                absolute_rank_base,
                absolute_rank_base + len(resolved_ranks),
            )
        )
        absolute_rank_base_source = "row_base"
        absolute_rank_anchor_source = "row_base"

    prepared_absolute_rank_anchor = _ocr_blue_archive_page_absolute_rank_anchor(
        prepared_image_path=prepared_image_path,
        ocr=ocr,
        row_bands=row_bands,
        resolved_ranks=resolved_ranks,
    ) if absolute_rank_base is None and not complete_row_ranks else None
    absolute_rank_anchor = prepared_absolute_rank_anchor
    if _is_valid_blue_archive_absolute_anchor(
        prepared_absolute_rank_anchor,
        page_index=page_index,
    ):
        absolute_rank_anchor_source = "prepared"
    else:
        absolute_rank_anchor = _ocr_blue_archive_page_absolute_rank_anchor_from_original_image(
            image_path=image_path,
            ocr=ocr,
            row_bands=row_bands,
            resolved_ranks=resolved_ranks,
            page_index=page_index,
        ) if absolute_rank_base is None and not complete_row_ranks else None
        if _is_valid_blue_archive_absolute_anchor(
            absolute_rank_anchor,
            page_index=page_index,
        ):
            absolute_rank_anchor_source = "original"
        else:
            absolute_rank_anchor = None
            absolute_rank_anchor_source = absolute_rank_base_source
    if absolute_rank_anchor is not None and not _is_valid_blue_archive_absolute_anchor(
        absolute_rank_anchor,
        page_index=page_index,
    ):
        absolute_rank_anchor = None
        absolute_rank_anchor_source = absolute_rank_base_source
    if (
        absolute_rank_base is not None
        and absolute_rank_anchor is not None
        and page_index == 1
        and abs(absolute_rank_anchor - absolute_rank_base) > max(3, len(resolved_ranks))
    ):
        absolute_rank_anchor = None
        absolute_rank_anchor_source = absolute_rank_base_source
    if absolute_rank_anchor is not None:
        resolved_ranks = list(
            range(
                absolute_rank_anchor,
                absolute_rank_anchor + len(resolved_ranks),
            )
        )
    normalized_entries: list[dict[str, Any]] = []
    rank_index = 0
    for entry in entries:
        normalized_entries.append(
            {
                **entry,
                "rank": resolved_ranks[rank_index],
                "_absolute_rank_anchor": absolute_rank_anchor,
                "_absolute_rank_anchor_source": absolute_rank_anchor_source,
                "_absolute_rank_base": absolute_rank_base,
                "_absolute_rank_base_source": absolute_rank_base_source,
            }
        )
        rank_index += 1
    if not _blue_archive_scores_are_non_increasing(normalized_entries):
        return []
    return normalized_entries


def _apply_blue_archive_original_row_ranks(
    *,
    entries: list[dict[str, Any]],
    recovered_ranks: list[int] | None,
) -> list[dict[str, Any]]:
    if not recovered_ranks or len(recovered_ranks) < len(entries):
        return entries

    current_ranks = [
        entry.get("rank") if isinstance(entry.get("rank"), int) else None
        for entry in entries
    ]
    if current_ranks == recovered_ranks[: len(entries)]:
        return entries

    recovered_has_absolute = any(rank > 100 for rank in recovered_ranks)
    current_has_absolute = any(
        isinstance(rank, int) and rank > 100 for rank in current_ranks
    )
    if not recovered_has_absolute and current_has_absolute:
        return entries

    normalized_entries: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        normalized_entries.append(
            {
                **entry,
                "rank": recovered_ranks[index],
                "_absolute_rank_base": (
                    recovered_ranks[0] if recovered_has_absolute else entry.get("_absolute_rank_base")
                ),
                "_absolute_rank_base_source": (
                    "original_row_ranks"
                    if recovered_has_absolute
                    else entry.get("_absolute_rank_base_source")
                ),
            }
        )
    return normalized_entries


def _should_continue_blue_archive_layout_attempt(
    *,
    entries: list[dict[str, Any]],
    recovered_ranks: list[int] | None,
) -> bool:
    expected_entry_count = len(recovered_ranks or [])
    if expected_entry_count <= 1:
        return False
    return len(entries) < expected_entry_count


def _select_preferred_blue_archive_attempt_entries(
    *,
    current_entries: list[dict[str, Any]],
    candidate_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not current_entries:
        return candidate_entries
    if len(candidate_entries) != len(current_entries):
        return candidate_entries if len(candidate_entries) > len(current_entries) else current_entries

    def _absolute_score(entries: list[dict[str, Any]]) -> int:
        return sum(
            1
            for entry in entries
            if isinstance(entry.get("rank"), int) and entry["rank"] > 100
        )

    candidate_absolute = _absolute_score(candidate_entries)
    current_absolute = _absolute_score(current_entries)
    if candidate_absolute != current_absolute:
        return candidate_entries if candidate_absolute > current_absolute else current_entries
    return candidate_entries


def _is_sufficient_blue_archive_fixed_row_entries(
    entries: list[dict[str, Any]],
) -> bool:
    if len(entries) >= 3:
        return True
    if len(entries) >= 2 and any(
        isinstance(entry.get("rank"), int) and entry["rank"] > 100
        for entry in entries
    ):
        return True
    return False


def _recover_blue_archive_original_row_ranks(
    *,
    prepared_image_path: Path,
    image_path: Path,
    ocr: OcrConfig,
) -> list[int] | None:
    detected_row_bands = _detect_blue_archive_row_bands(prepared_image_path) or (
        (0.02, 0.31),
        (0.35, 0.65),
        (0.69, 0.98),
    )
    row_bands = _select_visible_blue_archive_row_bands(detected_row_bands)
    if not row_bands:
        return None

    detected_ranks: list[int | None] = []
    for top_ratio, bottom_ratio in row_bands:
        detected_ranks.append(
            _ocr_blue_archive_row_rank_from_original_image(
                image_path=image_path,
                ocr=ocr,
                top_ratio=top_ratio,
                bottom_ratio=bottom_ratio,
            )
        )

    if not any(rank is not None for rank in detected_ranks):
        return None

    resolved_ranks = _resolve_anchor_ranks(detected_ranks)
    absolute_rank_signal = _has_strong_blue_archive_absolute_row_rank_signal(detected_ranks)
    absolute_rank_base = _resolve_blue_archive_absolute_rank_base_from_detected_ranks(
        detected_ranks
    )
    if not absolute_rank_signal:
        absolute_rank_base = None
        if any(isinstance(rank, int) and rank > 100 for rank in detected_ranks):
            return None
    if absolute_rank_base is not None:
        return list(range(absolute_rank_base, absolute_rank_base + len(resolved_ranks)))
    return resolved_ranks


def _has_strong_blue_archive_absolute_row_rank_signal(
    detected_ranks: list[int | None],
) -> bool:
    absolute_ranks = [
        rank
        for rank in detected_ranks
        if isinstance(rank, int) and rank > 100
    ]
    if len(absolute_ranks) < 2:
        return False
    sorted_ranks = sorted(absolute_ranks)
    return all(
        current - previous <= 2
        for previous, current in zip(sorted_ranks, sorted_ranks[1:])
    )


def _ocr_blue_archive_page_absolute_rank_anchor(
    *,
    prepared_image_path: Path,
    ocr: OcrConfig,
    row_bands: tuple[tuple[float, float], ...],
    resolved_ranks: list[int],
) -> int | None:
    if not row_bands or not resolved_ranks:
        return None
    if not _should_attempt_blue_archive_absolute_rank_anchor(resolved_ranks):
        return None

    top_ratio, bottom_ratio = row_bands[0]
    attempts = [
        OcrRegionAttempt(
            language="eng",
            psm=6,
            extra_args=("-c", "preserve_interword_spaces=1"),
            threshold=None,
        ),
        OcrRegionAttempt(
            language="eng",
            psm=7,
            extra_args=(
                "-c",
                "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ",
            ),
            threshold=None,
        ),
        OcrRegionAttempt(
            language="eng",
            psm=11,
            extra_args=("-c", "preserve_interword_spaces=1"),
            threshold=160,
        ),
    ]
    candidates: list[tuple[tuple[float, float], str]] = []
    focused_regions = (
        ((0.04, 0.82), (top_ratio + 0.02, min(bottom_ratio, top_ratio + 0.24))),
        ((0.02, 0.84), (top_ratio + 0.01, min(bottom_ratio, top_ratio + 0.26))),
        ((0.00, 0.56), (top_ratio, min(bottom_ratio, top_ratio + 0.24))),
        ((0.02, 0.56), (top_ratio, min(bottom_ratio, top_ratio + 0.24))),
        ((0.04, 0.56), (top_ratio, min(bottom_ratio, top_ratio + 0.24))),
        ((0.06, 0.42), (top_ratio, min(bottom_ratio, top_ratio + 0.18))),
        ((0.08, 0.44), (top_ratio, min(bottom_ratio, top_ratio + 0.20))),
        ((0.06, 0.52), (top_ratio, min(bottom_ratio, top_ratio + 0.22))),
        ((0.08, 0.52), (top_ratio, min(bottom_ratio, top_ratio + 0.22))),
        ((0.18, 0.60), (top_ratio, min(bottom_ratio, top_ratio + 0.22))),
        ((0.16, 0.64), (top_ratio, min(bottom_ratio, top_ratio + 0.28))),
    )
    for x_ratios, y_ratios in focused_regions:
        candidates.extend(
            [
                (x_ratios, candidate)
                for candidate in _ocr_prepared_image_ratio_region_candidates(
                    prepared_image_path=prepared_image_path,
                    x_ratios=x_ratios,
                    y_ratios=y_ratios,
                    attempts=attempts,
                    base_ocr=ocr,
                )
            ]
        )

    prefixed_ranks: list[int] = []
    focused_numeric_ranks: list[int] = []
    broad_numeric_ranks: list[int] = []
    for x_ratios, candidate in candidates:
        normalized_candidate = _normalize_unicode_ocr_text(candidate)
        lowered_candidate = normalized_candidate.lower()
        rank_candidates = _extract_rank_candidates_from_text(normalized_candidate)
        if "rank" in lowered_candidate:
            for rank in rank_candidates:
                if rank > len(resolved_ranks):
                    prefixed_ranks.append(rank)
            if not rank_candidates:
                rank = _parse_blue_archive_rank_candidate(normalized_candidate)
                if rank is not None and rank > len(resolved_ranks):
                    prefixed_ranks.append(rank)
            continue

        for rank in rank_candidates:
            if rank <= len(resolved_ranks):
                continue
            if x_ratios[1] <= 0.52:
                if rank >= 1000:
                    focused_numeric_ranks.append(rank)
            else:
                if rank >= 1000:
                    broad_numeric_ranks.append(rank)

    if prefixed_ranks:
        return _select_preferred_blue_archive_rank_candidate(prefixed_ranks)
    if focused_numeric_ranks:
        return _select_preferred_blue_archive_rank_candidate(focused_numeric_ranks)
    if broad_numeric_ranks:
        return _select_preferred_blue_archive_rank_candidate(broad_numeric_ranks)

    return None


def _ocr_blue_archive_page_absolute_rank_anchor_from_original_image(
    *,
    image_path: Path,
    ocr: OcrConfig,
    row_bands: tuple[tuple[float, float], ...],
    resolved_ranks: list[int],
    page_index: int,
) -> int | None:
    if not resolved_ranks:
        return None
    if page_index != 1 and not _should_attempt_blue_archive_absolute_rank_anchor(resolved_ranks):
        return None
    if not image_path.exists():
        return None

    candidates: list[int] = []
    anchor_crops = [
        OcrCrop(left_ratio=0.375, top_ratio=0.36, right_ratio=0.525, bottom_ratio=0.485),
        OcrCrop(left_ratio=0.38, top_ratio=0.36, right_ratio=0.53, bottom_ratio=0.485),
        OcrCrop(left_ratio=0.37, top_ratio=0.35, right_ratio=0.535, bottom_ratio=0.50),
        OcrCrop(left_ratio=0.40, top_ratio=0.35, right_ratio=0.56, bottom_ratio=0.49),
        OcrCrop(left_ratio=0.41, top_ratio=0.35, right_ratio=0.57, bottom_ratio=0.49),
    ]
    crop = ocr.crop
    if crop is None:
        anchor_crops.extend(
            [
                OcrCrop(left_ratio=0.35, top_ratio=0.24, right_ratio=0.57, bottom_ratio=0.42),
                OcrCrop(left_ratio=0.37, top_ratio=0.24, right_ratio=0.57, bottom_ratio=0.42),
                OcrCrop(left_ratio=0.35, top_ratio=0.23, right_ratio=0.59, bottom_ratio=0.43),
            ]
        )
    else:
        crop_width = crop.right_ratio - crop.left_ratio
        crop_height = crop.bottom_ratio - crop.top_ratio
        if row_bands:
            top_ratio, bottom_ratio = row_bands[0]
            row_top_absolute = crop.top_ratio + (crop_height * top_ratio)
            row_bottom_absolute = crop.top_ratio + (crop_height * bottom_ratio)
            row_rank_bottom = min(
                row_bottom_absolute,
                row_top_absolute + ((row_bottom_absolute - row_top_absolute) * 0.42),
            )
            anchor_crops.extend(
                [
                    OcrCrop(
                        left_ratio=max(0.0, crop.left_ratio + (crop_width * 0.00)),
                        top_ratio=max(0.0, crop.top_ratio + (crop_height * (top_ratio + 0.02))),
                        right_ratio=min(1.0, crop.left_ratio + (crop_width * 0.84)),
                        bottom_ratio=min(1.0, crop.top_ratio + (crop_height * min(bottom_ratio, top_ratio + 0.24))),
                    ),
                    OcrCrop(
                        left_ratio=max(0.0, crop.left_ratio - (crop_width * 0.04)),
                        top_ratio=max(0.0, crop.top_ratio + (crop_height * (top_ratio + 0.01))),
                        right_ratio=min(1.0, crop.left_ratio + (crop_width * 0.88)),
                        bottom_ratio=min(1.0, crop.top_ratio + (crop_height * min(bottom_ratio, top_ratio + 0.26))),
                    ),
                    OcrCrop(
                        left_ratio=0.40,
                        top_ratio=max(0.0, row_top_absolute),
                        right_ratio=0.57,
                        bottom_ratio=min(1.0, row_rank_bottom),
                    ),
                    OcrCrop(
                        left_ratio=0.41,
                        top_ratio=max(0.0, row_top_absolute),
                        right_ratio=0.58,
                        bottom_ratio=min(1.0, row_rank_bottom),
                    ),
                ]
            )
        anchor_crops.extend(
            [
                OcrCrop(
                    left_ratio=max(0.0, crop.left_ratio + (crop_width * 0.04)),
                    top_ratio=max(0.0, crop.top_ratio + (crop_height * 0.03)),
                    right_ratio=min(1.0, crop.left_ratio + (crop_width * 0.80)),
                    bottom_ratio=min(1.0, crop.top_ratio + (crop_height * 0.24)),
                ),
                OcrCrop(
                    left_ratio=max(0.0, crop.left_ratio + (crop_width * 0.02)),
                    top_ratio=max(0.0, crop.top_ratio + (crop_height * 0.02)),
                    right_ratio=min(1.0, crop.left_ratio + (crop_width * 0.84)),
                    bottom_ratio=min(1.0, crop.top_ratio + (crop_height * 0.26)),
                ),
                OcrCrop(
                    left_ratio=max(0.0, crop.left_ratio - (crop_width * 0.10)),
                    top_ratio=max(0.0, crop.top_ratio + (crop_height * 0.00)),
                    right_ratio=min(1.0, crop.left_ratio + (crop_width * 0.82)),
                    bottom_ratio=min(1.0, crop.top_ratio + (crop_height * 0.24)),
                ),
                OcrCrop(
                    left_ratio=max(0.0, crop.left_ratio - (crop_width * 0.06)),
                    top_ratio=max(0.0, crop.top_ratio + (crop_height * 0.00)),
                    right_ratio=min(1.0, crop.left_ratio + (crop_width * 0.86)),
                    bottom_ratio=min(1.0, crop.top_ratio + (crop_height * 0.24)),
                ),
                OcrCrop(
                    left_ratio=max(0.0, crop.left_ratio - (crop_width * 0.10)),
                    top_ratio=max(0.0, crop.top_ratio - (crop_height * 0.01)),
                    right_ratio=min(1.0, crop.left_ratio + (crop_width * 0.90)),
                    bottom_ratio=min(1.0, crop.top_ratio + (crop_height * 0.28)),
                ),
            ]
        )

    for anchor_crop in anchor_crops:
        for attempt in (
            OcrConfig(
                provider=ocr.provider,
                command=ocr.command,
                language="eng",
                psm=6,
                extra_args=("-c", "preserve_interword_spaces=1"),
                crop=anchor_crop,
                upscale_ratio=max(2.0, ocr.upscale_ratio),
                reuse_cached_sidecar=False,
                persist_sidecar=False,
            ),
            OcrConfig(
                provider=ocr.provider,
                command=ocr.command,
                language="eng",
                psm=6,
                extra_args=("-c", "preserve_interword_spaces=1"),
                crop=anchor_crop,
                upscale_ratio=max(2.5, ocr.upscale_ratio),
                reuse_cached_sidecar=False,
                persist_sidecar=False,
            ),
            OcrConfig(
                provider=ocr.provider,
                command=ocr.command,
                language="eng",
                psm=11,
                extra_args=("-c", "preserve_interword_spaces=1"),
                crop=anchor_crop,
                upscale_ratio=max(2.0, ocr.upscale_ratio),
                reuse_cached_sidecar=False,
                persist_sidecar=False,
            ),
            OcrConfig(
                provider=ocr.provider,
                command=ocr.command,
                language="eng",
                psm=11,
                extra_args=("-c", "preserve_interword_spaces=1"),
                crop=anchor_crop,
                upscale_ratio=max(2.5, ocr.upscale_ratio),
                reuse_cached_sidecar=False,
                persist_sidecar=False,
            ),
            OcrConfig(
                provider=ocr.provider,
                command=ocr.command,
                language="eng",
                psm=8,
                extra_args=(
                    "-c",
                    "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ,",
                ),
                crop=anchor_crop,
                upscale_ratio=max(2.5, ocr.upscale_ratio),
                reuse_cached_sidecar=False,
                persist_sidecar=False,
            ),
            OcrConfig(
                provider=ocr.provider,
                command=ocr.command,
                language="eng",
                psm=7,
                extra_args=(
                    "-c",
                    "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ",
                ),
                crop=OcrCrop(
                    left_ratio=max(0.0, anchor_crop.left_ratio - 0.02),
                    top_ratio=anchor_crop.top_ratio,
                    right_ratio=min(1.0, anchor_crop.right_ratio + 0.02),
                    bottom_ratio=min(1.0, anchor_crop.bottom_ratio + 0.02),
                ),
                upscale_ratio=max(2.5, ocr.upscale_ratio),
                reuse_cached_sidecar=False,
                persist_sidecar=False,
            ),
        ):
            prepared_image_path, cleanup = _prepare_image_for_ocr(image_path, attempt)
            try:
                text = _run_tesseract_command(
                    prepared_image_path=prepared_image_path,
                    original_image_path=image_path,
                    ocr=attempt,
                    output_kind="text",
                )
            except MockImportError:
                continue
            finally:
                cleanup()

            normalized_text = _normalize_unicode_ocr_text(text)
            rank_candidates = _extract_rank_candidates_from_text(normalized_text)
            for rank in rank_candidates:
                if rank > len(resolved_ranks):
                    candidates.append(rank)
            if not rank_candidates:
                rank = _parse_blue_archive_rank_candidate(normalized_text)
                if rank is not None and rank > len(resolved_ranks):
                    candidates.append(rank)

    return _select_preferred_blue_archive_rank_candidate(candidates)


def _should_attempt_blue_archive_absolute_rank_anchor(
    resolved_ranks: list[int],
) -> bool:
    if not resolved_ranks:
        return False
    if resolved_ranks == list(range(1, len(resolved_ranks) + 1)):
        return True
    first_rank = resolved_ranks[0]
    if first_rank <= 0 or first_rank > 100:
        return False
    return resolved_ranks == list(range(first_rank, first_rank + len(resolved_ranks)))


def _resolve_blue_archive_absolute_rank_base_from_detected_ranks(
    detected_ranks: list[int | None],
) -> int | None:
    base_candidates: list[int] = []
    for index, rank in enumerate(detected_ranks):
        if rank is None or rank <= 100:
            continue
        base_rank = rank - index
        if base_rank > 100:
            base_candidates.append(base_rank)
    if not base_candidates:
        return None
    return Counter(base_candidates).most_common(1)[0][0]


def _select_preferred_blue_archive_rank_candidate(ranks: list[int]) -> int | None:
    if not ranks:
        return None
    max_digits = max(len(str(rank)) for rank in ranks)
    preferred = [rank for rank in ranks if len(str(rank)) == max_digits]
    return Counter(preferred).most_common(1)[0][0]


def _resolve_blue_archive_absolute_rank_base_from_original_rows(
    *,
    image_path: Path,
    ocr: OcrConfig,
    row_bands: tuple[tuple[float, float], ...],
) -> int | None:
    detected_ranks: list[int | None] = []
    for top_ratio, bottom_ratio in row_bands:
        rank = _ocr_blue_archive_row_rank_from_original_image(
            image_path=image_path,
            ocr=ocr,
            top_ratio=top_ratio,
            bottom_ratio=bottom_ratio,
        )
        if rank is not None and rank > 100:
            detected_ranks.append(rank)
        else:
            detected_ranks.append(None)
    return _resolve_blue_archive_absolute_rank_base_from_detected_ranks(detected_ranks)


def _is_valid_blue_archive_absolute_anchor(
    anchor: int | None,
    *,
    page_index: int,
) -> bool:
    if anchor is None:
        return False
    return anchor > 100


def _resolve_blue_archive_page_difficulty(
    entries: list[dict[str, Any]],
) -> str | None:
    counts: dict[str, int] = {}
    for entry in entries:
        difficulty = entry.get("player_name")
        if isinstance(difficulty, str) and difficulty.strip():
            counts[difficulty] = counts.get(difficulty, 0) + 1
    if not counts:
        return None
    return max(
        counts.items(),
        key=lambda item: (item[1], DIFFICULTY_PRIORITY.get(item[0], 0), item[0]),
    )[0]


def _select_blue_archive_row_rank(
    *,
    prepared_rank: int | None,
    original_rank: int | None,
    visible_row_count: int,
) -> int | None:
    if original_rank is None:
        return prepared_rank
    if prepared_rank is None:
        return original_rank
    if original_rank > 100:
        return original_rank
    if (
        0 < original_rank <= visible_row_count + 1
        and prepared_rank > visible_row_count + 1
    ):
        return original_rank
    return prepared_rank


def _blue_archive_scores_are_non_increasing(
    entries: list[dict[str, Any]],
) -> bool:
    scores = [
        entry["score"]
        for entry in entries
        if isinstance(entry.get("score"), int)
    ]
    if len(scores) <= 1:
        return True
    return all(previous >= current for previous, current in zip(scores, scores[1:]))


def _detect_blue_archive_row_bands(
    prepared_image_path: Path,
) -> tuple[tuple[float, float], ...]:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return ()

    try:
        with Image.open(prepared_image_path) as image:
            grayscale = ImageOps.grayscale(image)
            width, height = grayscale.size
            pixels = grayscale.load()
    except OSError:
        return ()

    if width <= 0 or height <= 0:
        return ()

    dark_profile: list[float] = []
    for y in range(height):
        dark_pixels = 0
        for x in range(width):
            if pixels[x, y] < 232:
                dark_pixels += 1
        dark_profile.append(dark_pixels / width)

    smoothed_profile: list[float] = []
    for index in range(height):
        start = max(0, index - 3)
        end = min(height, index + 4)
        smoothed_profile.append(sum(dark_profile[start:end]) / (end - start))

    runs: list[tuple[int, int]] = []
    in_run = False
    run_start = 0
    for index, value in enumerate(smoothed_profile):
        if value > 0.08 and not in_run:
            in_run = True
            run_start = index
            continue
        if in_run and value <= 0.08:
            if index - run_start >= 25:
                runs.append((run_start, index - 1))
            in_run = False
    if in_run and height - run_start >= 25:
        runs.append((run_start, height - 1))

    if len(runs) >= 6:
        paired_rows = []
        for index in range(0, min(len(runs), 6), 2):
            top = runs[index][0]
            bottom = runs[index + 1][1]
            paired_rows.append((top / height, bottom / height))
        return tuple(paired_rows)

    if len(runs) >= 3:
        return tuple((top / height, bottom / height) for top, bottom in runs[:3])

    return ()


def _select_visible_blue_archive_row_bands(
    row_bands: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    if len(row_bands) <= 1:
        return row_bands

    heights = [bottom_ratio - top_ratio for top_ratio, bottom_ratio in row_bands]
    reference_height = max(heights)
    minimum_visible_height = reference_height * 0.65

    selected = list(row_bands)
    first_top_ratio, first_bottom_ratio = selected[0]
    if first_top_ratio <= 0.02 and (first_bottom_ratio - first_top_ratio) < minimum_visible_height:
        selected = selected[1:]

    if len(selected) <= 1:
        return tuple(selected)

    last_top_ratio, last_bottom_ratio = selected[-1]
    if last_bottom_ratio >= 0.98 and (last_bottom_ratio - last_top_ratio) < minimum_visible_height:
        selected = selected[:-1]

    return tuple(selected)


def _ocr_blue_archive_row_combined_fields(
    *,
    prepared_image_path: Path,
    ocr: OcrConfig,
    top_ratio: float,
    bottom_ratio: float,
    page_index: int,
) -> tuple[int | None, str | None, int | None]:
    candidates = _ocr_prepared_image_ratio_region_candidates(
        prepared_image_path=prepared_image_path,
        x_ratios=(0.22, 0.86),
        y_ratios=_build_blue_archive_row_y_ratios(top_ratio, bottom_ratio, 0.0, 0.72),
        attempts=[
            OcrRegionAttempt(
                language="eng",
                psm=6,
                extra_args=("-c", "preserve_interword_spaces=1"),
                threshold=None,
            ),
            OcrRegionAttempt(
                language="eng",
                psm=11,
                extra_args=("-c", "preserve_interword_spaces=1"),
                threshold=180,
            ),
        ],
        base_ocr=ocr,
    )

    for candidate in candidates:
        raw_lines = [line.strip() for line in candidate.splitlines() if line.strip()]
        if not raw_lines:
            continue
        score: int | None = None
        difficulty: str | None = None
        rank: int | None = None

        for line in raw_lines:
            if score is None:
                score = _find_score_anchor_value(line)
            if difficulty is None:
                difficulty = _find_anchor_difficulty([line], 0)
            if rank is None:
                rank_candidates = _extract_rank_candidates_from_text(line)
                if rank_candidates:
                    rank = rank_candidates[0]
        if score is None:
            score = _find_score_anchor_value(" ".join(raw_lines))
        if difficulty is None:
            difficulty = _find_anchor_difficulty(raw_lines, max(0, len(raw_lines) - 1))
        if rank is None:
            combined_ranks = _extract_rank_candidates_from_text(" ".join(raw_lines))
            if combined_ranks:
                rank = combined_ranks[0]

        if difficulty is not None and score is not None:
            return rank, difficulty, score

    return None, None, None


def _parse_tesseract_tsv_words(tsv_text: str) -> list[TesseractTsvWord]:
    words: list[TesseractTsvWord] = []
    for index, raw_line in enumerate(tsv_text.splitlines()):
        if index == 0 or not raw_line.strip():
            continue
        parts = raw_line.split("\t")
        if len(parts) != 12:
            continue
        level, _page_num, _block_num, _par_num, _line_num, _word_num, left, top, width, height, conf, text = parts
        if level != "5" or not text.strip():
            continue
        try:
            confidence = float(conf)
        except ValueError:
            confidence = None
        try:
            words.append(
                TesseractTsvWord(
                    text=text,
                    left=int(left),
                    top=int(top),
                    width=int(width),
                    height=int(height),
                    confidence=confidence,
                    block_num=int(parts[2]),
                    par_num=int(parts[3]),
                    line_num=int(parts[4]),
                )
            )
        except ValueError:
            continue
    return words


def _group_tesseract_words_by_line(
    words: list[TesseractTsvWord],
) -> list[list[TesseractTsvWord]]:
    grouped: dict[tuple[int, int, int], list[TesseractTsvWord]] = {}
    for word in words:
        key = (word.block_num, word.par_num, word.line_num)
        grouped.setdefault(key, []).append(word)

    return [
        sorted(line_words, key=lambda item: item.left)
        for _key, line_words in sorted(
            grouped.items(),
            key=lambda item: min(word.top for word in item[1]),
        )
    ]


def _parse_tesseract_layout_line(
    *,
    line_words: list[TesseractTsvWord],
    image_path: Path,
    default_ocr_confidence: float | None,
    page_index: int,
) -> dict[str, Any] | None:
    if len(line_words) < 3:
        return None

    score_index = _find_layout_score_index(line_words)
    if score_index is None:
        return None

    difficulty = _find_layout_difficulty(line_words[:score_index])
    if difficulty is None:
        return None

    rank = _find_layout_rank(line_words[:score_index])
    if rank is None:
        return None

    score_word = line_words[score_index]
    try:
        score = _parse_score_text(
            score_word.text,
            page_index=page_index,
            line_index=score_index + 1,
        )
    except MockImportError:
        return None

    confidences = [
        word.confidence / 100
        for word in line_words[: score_index + 1]
        if word.confidence is not None and word.confidence >= 0
    ]
    ocr_confidence = (
        round(sum(confidences) / len(confidences), 4)
        if confidences
        else default_ocr_confidence
    )

    raw_text = " ".join(word.text for word in line_words)
    return {
        "rank": rank,
        "score": score,
        "player_name": difficulty,
        "ocr_confidence": ocr_confidence,
        "raw_text": raw_text,
        "image_path": _build_entry_image_path(image_path),
        "is_valid": True,
        "validation_issue": None,
    }


def _parse_tesseract_layout_card(
    *,
    score_word: TesseractTsvWord,
    all_words: list[TesseractTsvWord],
    prepared_image_path: Path,
    image_path: Path,
    ocr: OcrConfig,
    default_ocr_confidence: float | None,
    page_index: int,
    fallback_rank: int,
) -> dict[str, Any] | None:
    card_words = [
        word
        for word in all_words
        if score_word.top - 80 <= word.top <= score_word.top + 120
        and word.left <= score_word.left + 20
    ]
    if not card_words:
        return None

    difficulty = _find_layout_difficulty(card_words)
    if difficulty is None:
        difficulty = _ocr_card_difficulty_from_region(
            prepared_image_path=prepared_image_path,
            score_word=score_word,
            ocr=ocr,
        )
    if difficulty is None:
        return None

    rank = _find_layout_rank_near_score(card_words, score_word)
    if rank is None:
        rank = _ocr_card_rank_from_region(
            prepared_image_path=prepared_image_path,
            score_word=score_word,
            ocr=ocr,
        )
    if rank is None:
        rank = fallback_rank

    try:
        score = _parse_score_text(
            score_word.text,
            page_index=page_index,
            line_index=1,
        )
    except MockImportError:
        return None

    confidences = [
        word.confidence / 100
        for word in card_words
        if word.confidence is not None and word.confidence >= 0
    ]
    ocr_confidence = (
        round(sum(confidences) / len(confidences), 4)
        if confidences
        else default_ocr_confidence
    )

    raw_text = " ".join(
        word.text for word in sorted(card_words, key=lambda item: (item.top, item.left))
    )
    return {
        "rank": rank,
        "score": score,
        "player_name": difficulty,
        "ocr_confidence": ocr_confidence,
        "raw_text": raw_text,
        "image_path": _build_entry_image_path(image_path),
        "is_valid": True,
        "validation_issue": None,
    }


def _find_layout_score_words(
    words: list[TesseractTsvWord],
) -> list[TesseractTsvWord]:
    score_words = [
        word
        for word in words
        if _normalize_score_ocr_token(word.text).isdigit()
        and len(_normalize_score_ocr_token(word.text)) >= 7
    ]
    score_words.sort(key=lambda word: (word.top, word.left))

    filtered: list[TesseractTsvWord] = []
    for word in score_words:
        if filtered and abs(word.top - filtered[-1].top) <= 20:
            if word.left < filtered[-1].left:
                filtered[-1] = word
            continue
        filtered.append(word)
    return filtered


def _find_layout_score_index(line_words: list[TesseractTsvWord]) -> int | None:
    best_index: int | None = None
    best_length = 0
    for index, word in enumerate(line_words):
        normalized = _normalize_score_ocr_token(word.text)
        if not normalized.isdigit():
            continue
        if len(normalized) < 7:
            continue
        if len(normalized) > best_length:
            best_index = index
            best_length = len(normalized)
    return best_index


def _find_layout_difficulty(
    line_words: list[TesseractTsvWord],
) -> str | None:
    for word in reversed(line_words):
        normalized = re.sub(r"[^A-Z0-9]+", "", _normalize_unicode_ocr_text(word.text).upper())
        difficulty = _resolve_difficulty_label(normalized)
        if difficulty is not None:
            return difficulty
    return None


def _resolve_difficulty_label(normalized: str) -> str | None:
    if not normalized:
        return None

    exact = DIFFICULTY_BY_NORMALIZED_TOKEN.get(normalized)
    if exact is not None:
        return exact

    alias = DIFFICULTY_ALIAS_BY_NORMALIZED_TOKEN.get(normalized)
    if alias is not None:
        return alias

    if len(normalized) < 4:
        return None

    for token, label in DIFFICULTY_BY_NORMALIZED_TOKEN.items():
        if token in normalized or normalized in token:
            return label

    matches = difflib.get_close_matches(
        normalized,
        list(DIFFICULTY_BY_NORMALIZED_TOKEN.keys()),
        n=1,
        cutoff=0.72,
    )
    if matches:
        return DIFFICULTY_BY_NORMALIZED_TOKEN[matches[0]]

    return None


def _find_layout_rank(
    line_words: list[TesseractTsvWord],
) -> int | None:
    for index, word in enumerate(line_words):
        token = word.text.strip()
        if token.lower().startswith("lv"):
            continue
        candidates = [token]
        if index + 1 < len(line_words):
            candidates.append(token + line_words[index + 1].text.strip())
        for candidate in candidates:
            normalized = _normalize_rank_ocr_token(candidate)
            if not normalized.isdigit():
                continue
            rank = int(normalized)
            if rank <= 0 or rank > 100000:
                continue
            return rank
    return None


def _find_layout_rank_near_score(
    line_words: list[TesseractTsvWord],
    score_word: TesseractTsvWord,
) -> int | None:
    candidates: list[tuple[int, int]] = []
    for index, word in enumerate(line_words):
        token = word.text.strip()
        if token.lower().startswith("lv"):
            continue
        token_candidates = [token]
        if index + 1 < len(line_words):
            token_candidates.append(token + line_words[index + 1].text.strip())
        for candidate in token_candidates:
            normalized = _normalize_rank_ocr_token(candidate)
            if not normalized.isdigit():
                continue
            rank = int(normalized)
            if rank <= 0 or rank > 100000:
                continue
            distance = abs(word.top - score_word.top) + max(0, score_word.left - word.left)
            candidates.append((distance, rank))
            break

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _ocr_card_rank_from_region(
    *,
    prepared_image_path: Path,
    score_word: TesseractTsvWord,
    ocr: OcrConfig,
) -> int | None:
    box = (
        0,
        max(0, score_word.top - score_word.height),
        max(24, min(score_word.left - 12, int(score_word.left * 0.32))),
        score_word.top + score_word.height,
    )
    candidates = _ocr_prepared_image_region_candidates(
        prepared_image_path=prepared_image_path,
        box=box,
        attempts=[
            OcrRegionAttempt(
                language="eng",
                psm=7,
                extra_args=("-c", "tessedit_char_whitelist=0123456789"),
                threshold=None,
            ),
            OcrRegionAttempt(
                language="eng",
                psm=10,
                extra_args=("-c", "tessedit_char_whitelist=0123456789"),
                threshold=170,
            ),
            OcrRegionAttempt(
                language="eng",
                psm=8,
                extra_args=("-c", "tessedit_char_whitelist=0123456789"),
                threshold=200,
            ),
        ],
        base_ocr=ocr,
    )
    for candidate in candidates:
        normalized = _normalize_rank_ocr_token(candidate)
        if not normalized.isdigit():
            continue
        rank = int(normalized)
        if 0 < rank <= 100000:
            return rank
    return None


def _ocr_card_difficulty_from_region(
    *,
    prepared_image_path: Path,
    score_word: TesseractTsvWord,
    ocr: OcrConfig,
) -> str | None:
    left = max(0, int(score_word.left * 0.32))
    right = max(left + 40, score_word.left - 8)
    candidates = _ocr_prepared_image_region_candidates(
        prepared_image_path=prepared_image_path,
        box=(
            left,
            max(0, score_word.top - score_word.height),
            right,
            score_word.top + score_word.height,
        ),
        attempts=[
            OcrRegionAttempt(
                language="eng",
                psm=7,
                extra_args=(
                    "-c",
                    "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
                ),
                threshold=None,
            ),
            OcrRegionAttempt(
                language="eng",
                psm=8,
                extra_args=(
                    "-c",
                    "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
                ),
                threshold=180,
            ),
        ],
        base_ocr=ocr,
    )
    for candidate in candidates:
        normalized = re.sub(r"[^A-Z0-9]+", "", _normalize_unicode_ocr_text(candidate).upper())
        difficulty = _resolve_difficulty_label(normalized)
        if difficulty is not None:
            return difficulty
    return None


def _ocr_blue_archive_row_rank(
    *,
    prepared_image_path: Path,
    ocr: OcrConfig,
    top_ratio: float,
    bottom_ratio: float,
) -> int | None:
    attempts = [
        OcrRegionAttempt(
            language="eng",
            psm=7,
            extra_args=(
                "-c",
                "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ",
            ),
            threshold=None,
        ),
        OcrRegionAttempt(
            language="eng",
            psm=8,
            extra_args=(
                "-c",
                "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ",
            ),
            threshold=180,
        ),
        OcrRegionAttempt(
            language="eng",
            psm=6,
            extra_args=("-c", "preserve_interword_spaces=1"),
            threshold=None,
        ),
        OcrRegionAttempt(
            language="eng",
            psm=11,
            extra_args=("-c", "preserve_interword_spaces=1"),
            threshold=160,
        ),
    ]
    candidates: list[str] = []
    for x_ratios, y_ratios in (
        ((0.04, 0.82), (top_ratio + 0.02, min(bottom_ratio, top_ratio + 0.24))),
        ((0.02, 0.84), (top_ratio + 0.01, min(bottom_ratio, top_ratio + 0.26))),
        ((0.00, 0.72), (top_ratio + 0.00, min(bottom_ratio, top_ratio + 0.24))),
        ((0.06, 0.42), (top_ratio, min(bottom_ratio, top_ratio + 0.18))),
        ((0.08, 0.44), (top_ratio, min(bottom_ratio, top_ratio + 0.20))),
        ((0.06, 0.52), (top_ratio, min(bottom_ratio, top_ratio + 0.22))),
        ((0.18, 0.48), (top_ratio, min(bottom_ratio, top_ratio + 0.20))),
        ((0.18, 0.56), (top_ratio, min(bottom_ratio, top_ratio + 0.24))),
        ((0.22, 0.60), (top_ratio, min(bottom_ratio, top_ratio + 0.28))),
        ((0.12, 0.52), (top_ratio, min(bottom_ratio, top_ratio + 0.24))),
    ):
        candidates.extend(
            _ocr_prepared_image_ratio_region_candidates(
                prepared_image_path=prepared_image_path,
                x_ratios=x_ratios,
                y_ratios=y_ratios,
                attempts=attempts,
                base_ocr=ocr,
            )
        )
    parsed_ranks: list[int] = []
    prefixed_ranks: list[int] = []
    for candidate in candidates:
        rank_candidates = _extract_rank_candidates_from_text(candidate)
        if rank_candidates:
            if "rank" in _normalize_unicode_ocr_text(candidate).lower():
                prefixed_ranks.extend(rank_candidates)
            parsed_ranks.extend(rank_candidates)
            continue
        normalized_candidate = _normalize_unicode_ocr_text(candidate)
        if "rank" in normalized_candidate.lower():
            rank = _parse_blue_archive_rank_candidate(normalized_candidate)
            if rank is not None:
                prefixed_ranks.append(rank)
                parsed_ranks.append(rank)
                continue
        rank = _parse_blue_archive_rank_candidate(candidate)
        if rank is not None:
            parsed_ranks.append(rank)
    if prefixed_ranks:
        return _select_preferred_blue_archive_rank_candidate(prefixed_ranks)
    return _select_preferred_blue_archive_rank_candidate(parsed_ranks)


def _ocr_blue_archive_row_rank_from_original_image(
    *,
    image_path: Path,
    ocr: OcrConfig,
    top_ratio: float,
    bottom_ratio: float,
) -> int | None:
    crop = ocr.crop
    if crop is None or not image_path.exists():
        return None

    crop_width = crop.right_ratio - crop.left_ratio
    crop_height = crop.bottom_ratio - crop.top_ratio
    row_top_absolute = crop.top_ratio + (crop_height * top_ratio)
    row_bottom_absolute = crop.top_ratio + (crop_height * bottom_ratio)
    row_rank_bottom = min(
        row_bottom_absolute,
        row_top_absolute + ((row_bottom_absolute - row_top_absolute) * 0.42),
    )
    region_crops = (
        OcrCrop(
            left_ratio=max(0.0, crop.left_ratio + (crop_width * 0.00)),
            top_ratio=max(0.0, crop.top_ratio + (crop_height * (top_ratio + 0.02))),
            right_ratio=min(1.0, crop.left_ratio + (crop_width * 0.84)),
            bottom_ratio=min(1.0, crop.top_ratio + (crop_height * min(bottom_ratio, top_ratio + 0.24))),
        ),
        OcrCrop(
            left_ratio=max(0.0, crop.left_ratio - (crop_width * 0.04)),
            top_ratio=max(0.0, crop.top_ratio + (crop_height * (top_ratio + 0.01))),
            right_ratio=min(1.0, crop.left_ratio + (crop_width * 0.88)),
            bottom_ratio=min(1.0, crop.top_ratio + (crop_height * min(bottom_ratio, top_ratio + 0.26))),
        ),
        OcrCrop(
            left_ratio=0.375,
            top_ratio=max(0.0, crop.top_ratio + (crop_height * (top_ratio + 0.01))),
            right_ratio=0.54,
            bottom_ratio=min(1.0, crop.top_ratio + (crop_height * min(bottom_ratio, top_ratio + 0.26))),
        ),
        OcrCrop(
            left_ratio=0.40,
            top_ratio=max(0.0, row_top_absolute),
            right_ratio=0.57,
            bottom_ratio=min(1.0, row_rank_bottom),
        ),
        OcrCrop(
            left_ratio=0.41,
            top_ratio=max(0.0, row_top_absolute),
            right_ratio=0.58,
            bottom_ratio=min(1.0, row_rank_bottom),
        ),
        OcrCrop(
            left_ratio=max(0.0, crop.left_ratio - (crop_width * 0.10)),
            top_ratio=max(0.0, crop.top_ratio + (crop_height * (top_ratio + 0.00))),
            right_ratio=min(1.0, crop.left_ratio + (crop_width * 0.96)),
            bottom_ratio=min(1.0, crop.top_ratio + (crop_height * min(bottom_ratio, top_ratio + 0.28))),
        ),
        OcrCrop(
            left_ratio=max(0.0, crop.left_ratio - (crop_width * 0.14)),
            top_ratio=max(0.0, crop.top_ratio + (crop_height * (top_ratio + 0.00))),
            right_ratio=min(1.0, crop.left_ratio + (crop_width * 1.00)),
            bottom_ratio=min(1.0, crop.top_ratio + (crop_height * min(bottom_ratio, top_ratio + 0.30))),
        ),
        OcrCrop(
            left_ratio=max(0.0, crop.left_ratio - (crop_width * 0.08)),
            top_ratio=max(0.0, row_top_absolute),
            right_ratio=min(1.0, crop.left_ratio + (crop_width * 0.98)),
            bottom_ratio=min(1.0, row_rank_bottom + ((row_bottom_absolute - row_top_absolute) * 0.04)),
        ),
    )

    parsed_ranks: list[int] = []
    prefixed_ranks: list[int] = []
    for region_crop in region_crops:
        for attempt in (
            OcrConfig(
                provider=ocr.provider,
                command=ocr.command,
                language="eng",
                psm=6,
                extra_args=("-c", "preserve_interword_spaces=1"),
                crop=region_crop,
                upscale_ratio=max(2.5, ocr.upscale_ratio),
                reuse_cached_sidecar=False,
                persist_sidecar=False,
            ),
            OcrConfig(
                provider=ocr.provider,
                command=ocr.command,
                language="eng",
                psm=7,
                extra_args=(
                    "-c",
                    "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ,",
                ),
                crop=region_crop,
                upscale_ratio=max(3.0, ocr.upscale_ratio),
                reuse_cached_sidecar=False,
                persist_sidecar=False,
            ),
            OcrConfig(
                provider=ocr.provider,
                command=ocr.command,
                language="eng",
                psm=8,
                extra_args=(
                    "-c",
                    "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ,",
                ),
                crop=region_crop,
                upscale_ratio=max(2.5, ocr.upscale_ratio),
                reuse_cached_sidecar=False,
                persist_sidecar=False,
            ),
            OcrConfig(
                provider=ocr.provider,
                command=ocr.command,
                language="eng",
                psm=11,
                extra_args=("-c", "preserve_interword_spaces=1"),
                crop=region_crop,
                upscale_ratio=max(2.5, ocr.upscale_ratio),
                reuse_cached_sidecar=False,
                persist_sidecar=False,
            ),
        ):
            prepared_image_path, cleanup = _prepare_image_for_ocr(image_path, attempt)
            try:
                text = _run_tesseract_command(
                    prepared_image_path=prepared_image_path,
                    original_image_path=image_path,
                    ocr=attempt,
                    output_kind="text",
                )
            except MockImportError:
                continue
            finally:
                cleanup()

            normalized_text = _normalize_unicode_ocr_text(text)
            rank_candidates = _extract_rank_candidates_from_text(normalized_text)
            lower_text = normalized_text.lower()
            positive_rank_candidates = [rank for rank in rank_candidates if rank > 0]
            if "rank" in lower_text:
                prefixed_ranks.extend(positive_rank_candidates)
                strong_prefixed_rank = _select_preferred_blue_archive_rank_candidate(
                    positive_rank_candidates
                )
                if strong_prefixed_rank is not None and (
                    strong_prefixed_rank > 100 or strong_prefixed_rank <= 10
                ):
                    return strong_prefixed_rank
            parsed_ranks.extend(positive_rank_candidates)
            strong_rank = _select_preferred_blue_archive_rank_candidate(
                positive_rank_candidates
            )
            if strong_rank is not None and (
                strong_rank > 100 or strong_rank <= 10
            ):
                return strong_rank
            if not rank_candidates:
                rank = _parse_blue_archive_rank_candidate(normalized_text)
                if rank is not None:
                    if "rank" in lower_text:
                        prefixed_ranks.append(rank)
                        if rank > 100 or rank <= 10:
                            return rank
                    parsed_ranks.append(rank)
                    if rank > 100 or rank <= 10:
                        return rank

    if prefixed_ranks:
        return _select_preferred_blue_archive_rank_candidate(prefixed_ranks)
    if not parsed_ranks:
        return None
    return _select_preferred_blue_archive_rank_candidate(parsed_ranks)


def _ocr_blue_archive_row_difficulty(
    *,
    prepared_image_path: Path,
    ocr: OcrConfig,
    top_ratio: float,
    bottom_ratio: float,
) -> str | None:
    candidates = _ocr_prepared_image_ratio_region_candidates(
        prepared_image_path=prepared_image_path,
        x_ratios=(0.0, 0.42),
        y_ratios=(top_ratio + 0.12, min(bottom_ratio, top_ratio + 0.28)),
        attempts=[
            OcrRegionAttempt(
                language="eng",
                psm=7,
                extra_args=(
                    "-c",
                    "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
                ),
                threshold=None,
            ),
            OcrRegionAttempt(
                language="eng",
                psm=8,
                extra_args=(
                    "-c",
                    "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
                ),
                threshold=180,
            ),
        ],
        base_ocr=ocr,
    )
    for candidate in candidates:
        normalized = re.sub(r"[^A-Z0-9]+", "", _normalize_unicode_ocr_text(candidate).upper())
        difficulty = _resolve_difficulty_label(normalized)
        if difficulty is not None:
            return difficulty
    return None


def _ocr_blue_archive_row_score(
    *,
    prepared_image_path: Path,
    ocr: OcrConfig,
    top_ratio: float,
    bottom_ratio: float,
    page_index: int,
) -> int | None:
    candidates = _ocr_prepared_image_ratio_region_candidates(
        prepared_image_path=prepared_image_path,
        x_ratios=(0.3, 1.0),
        y_ratios=(top_ratio + 0.1, min(bottom_ratio, top_ratio + 0.28)),
        attempts=[
            OcrRegionAttempt(
                language="eng",
                psm=7,
                extra_args=("-c", "tessedit_char_whitelist=0123456789,"),
                threshold=None,
            ),
            OcrRegionAttempt(
                language="eng",
                psm=8,
                extra_args=("-c", "tessedit_char_whitelist=0123456789,"),
                threshold=170,
            ),
        ],
        base_ocr=ocr,
    )
    for candidate in candidates:
        try:
            return _parse_score_text(candidate, page_index=page_index, line_index=1)
        except MockImportError:
            continue
    return None


def _build_blue_archive_row_y_ratios(
    top_ratio: float,
    bottom_ratio: float,
    start_ratio: float,
    end_ratio: float,
) -> tuple[float, float]:
    row_height = bottom_ratio - top_ratio
    return (
        top_ratio + (row_height * start_ratio),
        top_ratio + (row_height * end_ratio),
    )


@dataclass(frozen=True)
class OcrRegionAttempt:
    language: str
    psm: int
    extra_args: tuple[str, ...]
    threshold: int | None


def _ocr_prepared_image_region_candidates(
    *,
    prepared_image_path: Path,
    box: tuple[int, int, int, int],
    attempts: list[OcrRegionAttempt],
    base_ocr: OcrConfig,
) -> list[str]:
    left, top, right, bottom = box
    if left >= right or top >= bottom:
        return []

    try:
        from PIL import Image
    except ImportError:
        return []

    with Image.open(prepared_image_path) as image:
        right = min(right, image.width)
        bottom = min(bottom, image.height)
        if left >= right or top >= bottom:
            return []
        region = image.crop((left, top, right, bottom))
        candidates: list[str] = []
        for attempt in attempts:
            candidate = _ocr_region_image_variant(
                region=region,
                prepared_image_path=prepared_image_path,
                attempt=attempt,
                base_ocr=base_ocr,
            )
            if candidate:
                candidates.append(candidate)
        return candidates


def _ocr_prepared_image_ratio_region_candidates(
    *,
    prepared_image_path: Path,
    x_ratios: tuple[float, float],
    y_ratios: tuple[float, float],
    attempts: list[OcrRegionAttempt],
    base_ocr: OcrConfig,
) -> list[str]:
    try:
        from PIL import Image
    except ImportError:
        return []

    with Image.open(prepared_image_path) as image:
        left = max(0, int(image.width * x_ratios[0]))
        right = min(image.width, int(image.width * x_ratios[1]))
        top = max(0, int(image.height * y_ratios[0]))
        bottom = min(image.height, int(image.height * y_ratios[1]))

    return _ocr_prepared_image_region_candidates(
        prepared_image_path=prepared_image_path,
        box=(left, top, right, bottom),
        attempts=attempts,
        base_ocr=base_ocr,
    )


def _ocr_region_image_variant(
    *,
    region,
    prepared_image_path: Path,
    attempt: OcrRegionAttempt,
    base_ocr: OcrConfig,
) -> str | None:
    from PIL import ImageOps

    processed = region.copy()
    if attempt.threshold is not None:
        grayscale = ImageOps.grayscale(processed)
        processed = grayscale.point(
            lambda value: 255 if value >= attempt.threshold else 0,
            mode="1",
        ).convert("L")

    with tempfile.NamedTemporaryFile(
        suffix=prepared_image_path.suffix,
        prefix="plana-ocr-region-",
        delete=False,
    ) as temp_file:
        temp_path = Path(temp_file.name)
    processed.save(temp_path)

    try:
        return _run_tesseract_command(
            prepared_image_path=temp_path,
            original_image_path=prepared_image_path,
            ocr=OcrConfig(
                provider=base_ocr.provider,
                command=base_ocr.command,
                language=attempt.language,
                psm=attempt.psm,
                extra_args=attempt.extra_args,
                crop=None,
                upscale_ratio=1.0,
                reuse_cached_sidecar=False,
                persist_sidecar=False,
            ),
            output_kind="text",
        )
    except MockImportError:
        return None
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


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
    ocr: OcrConfig,
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

    if not entries and ocr.provider == OCR_PROVIDER_TESSERACT:
        entries = _parse_tesseract_layout_entries(
            image_path=image_path,
            ocr=ocr,
            default_ocr_confidence=default_ocr_confidence,
            page_index=page_index,
        )

    if not entries and ocr.provider == OCR_PROVIDER_TESSERACT:
        entries = _parse_tesseract_score_anchor_lines(
            ocr_text=ocr_text,
            image_path=image_path,
            default_ocr_confidence=default_ocr_confidence,
            page_index=page_index,
        )

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


def _parse_tesseract_score_anchor_lines(
    *,
    ocr_text: str,
    image_path: Path,
    default_ocr_confidence: float | None,
    page_index: int,
) -> list[dict[str, Any]]:
    raw_lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    if not raw_lines:
        return []

    anchors: list[tuple[int, int, str | None]] = []
    detected_difficulties: list[str] = []
    for line_index, line in enumerate(raw_lines):
        score = _find_score_anchor_value(line)
        if score is None:
            continue
        difficulty = _find_anchor_difficulty(raw_lines, line_index)
        if difficulty is not None:
            detected_difficulties.append(difficulty)
        anchors.append((line_index, score, difficulty))

    if not anchors:
        return []

    page_difficulty = _pick_page_difficulty(detected_difficulties)
    detected_ranks: list[int | None] = []
    used_ranks: set[int] = set()
    for fallback_rank, (line_index, _score, _difficulty) in enumerate(anchors, start=1):
        rank = _find_anchor_rank(
            raw_lines=raw_lines,
            anchor_index=line_index,
            expected_rank=fallback_rank,
            used_ranks=used_ranks,
        )
        detected_ranks.append(rank)
        if rank is not None:
            used_ranks.add(rank)

    resolved_ranks = _resolve_anchor_ranks(detected_ranks)
    entries: list[dict[str, Any]] = []

    for index, (line_index, score, difficulty) in enumerate(anchors):
        resolved_difficulty = difficulty or page_difficulty
        if resolved_difficulty is None:
            continue

        rank = resolved_ranks[index]

        raw_text = " ".join(
            raw_lines[max(0, line_index - 2) : min(len(raw_lines), line_index + 2)]
        )
        entries.append(
            {
                "rank": rank,
                "score": score,
                "player_name": resolved_difficulty,
                "ocr_confidence": default_ocr_confidence,
                "raw_text": raw_text,
                "image_path": _build_entry_image_path(image_path),
                "is_valid": True,
                "validation_issue": None,
            }
        )

    return _normalize_tesseract_page_entry_ranks(entries)


def _resolve_anchor_ranks(detected_ranks: list[int | None]) -> list[int]:
    if not detected_ranks:
        return []

    ranks = list(detected_ranks)
    seen: set[int] = set()
    for index, rank in enumerate(ranks):
        if rank is None or rank <= 0 or rank in seen:
            ranks[index] = None
            continue
        seen.add(rank)

    ranks = _drop_inconsistent_detected_ranks(ranks)

    known_indices = [index for index, rank in enumerate(ranks) if rank is not None]
    if not known_indices:
        return [index + 1 for index in range(len(ranks))]

    first_index = known_indices[0]
    first_rank = ranks[first_index]
    assert first_rank is not None
    for index in range(first_index - 1, -1, -1):
        ranks[index] = max(1, first_rank - (first_index - index))

    for known_pos, start_index in enumerate(known_indices[:-1]):
        end_index = known_indices[known_pos + 1]
        start_rank = ranks[start_index]
        assert start_rank is not None
        for index in range(start_index + 1, end_index):
            ranks[index] = start_rank + (index - start_index)

    last_index = known_indices[-1]
    last_rank = ranks[last_index]
    assert last_rank is not None
    for index in range(last_index + 1, len(ranks)):
        ranks[index] = last_rank + (index - last_index)

    resolved: list[int] = []
    for index, rank in enumerate(ranks):
        if rank is None:
            if resolved:
                rank = resolved[-1] + 1
            else:
                rank = index + 1
        resolved.append(rank)
    return resolved


def _normalize_tesseract_page_entry_ranks(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(entries) <= 1:
        return entries

    detected_ranks: list[int | None] = []
    for entry in entries:
        rank = entry.get("rank")
        detected_ranks.append(rank if isinstance(rank, int) and rank > 0 else None)

    resolved_ranks = _resolve_anchor_ranks(detected_ranks)
    if [entry.get("rank") for entry in entries] == resolved_ranks:
        return entries

    normalized_entries: list[dict[str, Any]] = []
    for entry, rank in zip(entries, resolved_ranks):
        normalized_entries.append(
            {
                **entry,
                "rank": rank,
            }
        )
    return normalized_entries


def _drop_inconsistent_detected_ranks(ranks: list[int | None]) -> list[int | None]:
    known = [(index, rank) for index, rank in enumerate(ranks) if rank is not None]
    if len(known) <= 1:
        return ranks

    def support(anchor_index: int, anchor_rank: int) -> int:
        count = 0
        for index, rank in known:
            assert rank is not None
            expected = anchor_rank + (index - anchor_index)
            if abs(rank - expected) <= 1:
                count += 1
        return count

    supports = {
        (index, rank): support(index, rank)
        for index, rank in known
    }
    best_support = max(supports.values())
    supported_known = [
        (index, rank)
        for index, rank in known
        if supports[(index, rank)] == best_support
    ]

    large_rank_candidates = [
        item
        for item in supported_known
        if item[1] >= 1000
    ]
    if large_rank_candidates:
        best_anchor_index, best_anchor_rank = max(
            large_rank_candidates,
            key=lambda item: (item[1], -item[0]),
        )
    else:
        best_anchor_index, best_anchor_rank = min(
            supported_known,
            key=lambda item: (item[0], item[1]),
        )

    filtered = list(ranks)
    for index, rank in known:
        assert rank is not None
        expected = best_anchor_rank + (index - best_anchor_index)
        if abs(rank - expected) > 1:
            filtered[index] = None
    return filtered


def _find_score_anchor_value(raw_line: str) -> int | None:
    tokens = raw_line.split()
    if not tokens:
        return None

    candidates: list[tuple[int, int]] = []
    for start in range(len(tokens)):
        for end in range(len(tokens), start, -1):
            candidate_tokens = _strip_trailing_score_suffix_tokens(tokens[start:end])
            if not candidate_tokens:
                continue
            normalized_tokens = [
                _normalize_score_ocr_token(token)
                for token in candidate_tokens
            ]
            if not all(token.isdigit() for token in normalized_tokens):
                continue
            digit_length = len("".join(normalized_tokens))
            if digit_length < 7:
                continue
            try:
                parsed_score = _parse_grouped_score_tokens(
                    candidate_tokens,
                    page_index=1,
                    line_index=1,
                )
            except MockImportError:
                continue
            length_penalty = 0 if 7 <= digit_length <= 8 else 100 + abs(digit_length - 8)
            token_penalty = max(0, len(candidate_tokens) - 1) * 10
            trailing_penalty = len(tokens) - end
            candidates.append(
                (
                    (length_penalty * 1000) + token_penalty + trailing_penalty,
                    parsed_score,
                )
            )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _find_anchor_difficulty(raw_lines: list[str], anchor_index: int) -> str | None:
    line_candidates = [anchor_index, anchor_index - 1, anchor_index - 2, anchor_index + 1]
    for line_index in line_candidates:
        if line_index < 0 or line_index >= len(raw_lines):
            continue
        tokens = raw_lines[line_index].split()
        for token in reversed(tokens):
            normalized = re.sub(
                r"[^A-Z0-9]+",
                "",
                _normalize_unicode_ocr_text(token).upper(),
            )
            difficulty = _resolve_difficulty_label(normalized)
            if difficulty is not None:
                return difficulty
    return None


def _pick_page_difficulty(difficulties: list[str]) -> str | None:
    if not difficulties:
        return None

    counts: dict[str, int] = {}
    for difficulty in difficulties:
        counts[difficulty] = counts.get(difficulty, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]


def _find_anchor_rank(
    *,
    raw_lines: list[str],
    anchor_index: int,
    expected_rank: int,
    used_ranks: set[int],
) -> int | None:
    candidates: list[tuple[int, int, int]] = []
    start_index = max(0, anchor_index - 4)
    for line_index in range(anchor_index, start_index - 1, -1):
        raw_line = raw_lines[line_index]
        if _find_score_anchor_value(raw_line) is not None:
            continue
        if "lv" in raw_line.lower():
            continue
        for rank in _extract_rank_candidates_from_text(raw_line):
            if rank in used_ranks:
                continue
            distance = anchor_index - line_index
            score = (distance * 1000) + abs(rank - expected_rank)
            candidates.append((score, distance, rank))

    if not candidates:
        return None

    candidates.sort()
    return candidates[0][2]


def _extract_rank_candidates_from_text(raw_line: str) -> list[int]:
    tokens = raw_line.split()
    candidates: list[int] = []

    for index, token in enumerate(tokens):
        if token.lower().startswith("lv"):
            continue
        if token.startswith("(") and token.endswith(")"):
            continue
        token_candidates = [token]
        if index + 1 < len(tokens):
            token_candidates.append(token + tokens[index + 1])
        for candidate in token_candidates:
            stripped_candidate = _normalize_unicode_ocr_text(candidate).strip()
            lowered_candidate = stripped_candidate.lower()
            if not (
                stripped_candidate[:1].isdigit()
                or stripped_candidate.startswith(("#", "№"))
                or lowered_candidate.startswith("no")
                or lowered_candidate.startswith("rank")
                or stripped_candidate.endswith("위")
            ):
                continue
            rank = _parse_blue_archive_rank_candidate(candidate)
            if rank is None:
                continue
            if rank not in candidates:
                candidates.append(rank)
            break

    normalized_tokens = [_normalize_unicode_ocr_text(token).strip() for token in tokens]
    for index, token in enumerate(normalized_tokens):
        lowered_token = token.lower()
        if not (
            lowered_token.startswith("rank")
            or lowered_token.startswith("no")
            or token.startswith(("#", "№"))
        ):
            continue
        digit_parts: list[str] = []
        for candidate_token in normalized_tokens[index + 1 : index + 4]:
            normalized_part = _normalize_rank_ocr_token(candidate_token)
            if not normalized_part.isdigit():
                break
            if len("".join(digit_parts)) + len(normalized_part) > 5:
                break
            digit_parts.append(normalized_part)
        if not digit_parts:
            continue
        combined_rank = _parse_blue_archive_rank_candidate("".join(digit_parts))
        if combined_rank is not None:
            for part in digit_parts:
                if part.isdigit():
                    part_rank = int(part)
                    if part_rank in candidates and len(part) < len(str(combined_rank)):
                        candidates.remove(part_rank)
            if combined_rank not in candidates:
                candidates.append(combined_rank)

    return candidates


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
    if lowered.startswith("rank"):
        normalized = normalized[4:].lstrip(" .:-#")
        lowered = normalized.lower()
    if lowered.startswith("no."):
        normalized = normalized[3:]
    elif lowered.startswith("no"):
        normalized = normalized[2:]
    if normalized.startswith("#"):
        normalized = normalized[1:]
    normalized = normalized.removeprefix("№")
    normalized = normalized.removesuffix("위")
    normalized = normalized.translate(OCR_RANK_TRANSLATION)
    normalized = _normalize_integer_ocr_token(normalized)
    match = re.match(r"(\d+)", normalized)
    if match is not None:
        normalized = match.group(1)
    return normalized.strip(".:- ")


def _parse_blue_archive_rank_candidate(value: str) -> int | None:
    normalized = _normalize_rank_ocr_token(value)
    if normalized.isdigit():
        rank = int(normalized)
        if 0 < rank <= 100000:
            return rank

    if not normalized.isdigit() or len(normalized) < 5:
        return None

    for trim, allowed_suffixes in (
        (2, {"47", "91", "71"}),
        (1, {"7", "1"}),
    ):
        if len(normalized) <= trim:
            continue
        suffix = normalized[-trim:]
        if suffix not in allowed_suffixes:
            continue
        trimmed = normalized[:-trim]
        if not trimmed.isdigit():
            continue
        rank = int(trimmed)
        if 0 < rank <= 100000:
            return rank

    return None


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


def _parse_boolean_option(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    raise MockImportError(f"{label}는 true 또는 false 여야 합니다.")


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
    parser.add_argument(
        "--reuse-tesseract-sidecar",
        action="store_true",
        help="tesseract provider에서 기존 OCR sidecar(.txt)가 있으면 재사용합니다.",
    )
    parser.add_argument(
        "--no-persist-tesseract-sidecar",
        action="store_true",
        help="tesseract provider에서 OCR 결과 sidecar(.txt)를 저장하지 않습니다.",
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
            reuse_tesseract_sidecar=True if args.reuse_tesseract_sidecar else None,
            persist_tesseract_sidecar=False if args.no_persist_tesseract_sidecar else None,
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
