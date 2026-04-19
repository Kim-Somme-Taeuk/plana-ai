from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def parse_blue_archive_capture(
    *,
    resolved_pages: list[tuple[int, Path, float | None]],
    parse_page_rows: Callable[[Path, float | None, int], tuple[list[dict[str, Any]], dict[str, Any]]],
    realign_page_ranks: Callable[[list[dict[str, Any]], list[dict[str, Any]]], list[dict[str, Any]]],
    retrofit_absolute_ranks: Callable[[list[list[dict[str, Any]]], list[dict[str, Any]]], tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]],
    prune_sparse_pages: Callable[[list[list[dict[str, Any]]], list[dict[str, Any]]], tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]],
    build_page_summaries: Callable[[list[list[dict[str, Any]]], list[dict[str, Any]]], list[dict[str, Any]]],
    strip_internal_entry_fields: Callable[[dict[str, Any]], dict[str, Any]],
    build_entry_image_path: Callable[[Path], str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Any]]:
    ignored_lines: list[Any] = []
    page_metadata: list[dict[str, Any]] = []
    parsed_pages: list[list[dict[str, Any]]] = []
    previous_page_entries: list[dict[str, Any]] = []

    for page_index, image_path, default_ocr_confidence in resolved_pages:
        page_entries, page_debug = parse_page_rows(
            image_path,
            default_ocr_confidence,
            page_index,
        )
        page_entries = _apply_page_majority_difficulty(page_entries)
        page_entries = realign_page_ranks(previous_page_entries, page_entries)

        page_metadata.append(
            {
                "page_index": page_index,
                "image_path": build_entry_image_path(image_path),
                "ignored_lines": [],
                "absolute_rank_anchor": _first_internal_value(page_entries, "_absolute_rank_anchor"),
                "absolute_rank_anchor_source": _first_internal_value(page_entries, "_absolute_rank_anchor_source"),
                "absolute_rank_base": _first_internal_value(page_entries, "_absolute_rank_base"),
                "absolute_rank_base_source": _first_internal_value(page_entries, "_absolute_rank_base_source"),
                "is_blue_archive_layout": True,
                "row_bands": page_debug.get("row_bands", []),
                "detected_row_bands": page_debug.get("detected_row_bands", []),
                "row_debugs": page_debug.get("row_debugs", []),
            }
        )
        parsed_pages.append(page_entries)
        previous_page_entries = [strip_internal_entry_fields(entry) for entry in page_entries]

    parsed_pages, page_metadata = retrofit_absolute_ranks(parsed_pages, page_metadata)
    parsed_pages, page_metadata = prune_sparse_pages(parsed_pages, page_metadata)
    page_summaries = build_page_summaries(parsed_pages, page_metadata)

    entries: list[dict[str, Any]] = []
    seen_ranks: set[int] = set()
    for page_entries in parsed_pages:
        for entry in page_entries:
            rank = entry.get("rank")
            if isinstance(rank, int) and rank in seen_ranks:
                continue
            entries.append(strip_internal_entry_fields(entry))
            if isinstance(rank, int):
                seen_ranks.add(rank)

    return entries, page_summaries, ignored_lines


def _apply_page_majority_difficulty(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not entries:
        return entries

    counts: dict[str, int] = {}
    for entry in entries:
        difficulty = entry.get("player_name")
        if isinstance(difficulty, str) and difficulty.strip():
            counts[difficulty] = counts.get(difficulty, 0) + 1

    if not counts:
        return entries

    majority = max(
        counts.items(),
        key=lambda item: (item[1], item[0]),
    )[0]
    return [
        {
            **entry,
            "player_name": majority,
        }
        for entry in entries
    ]


def _first_internal_value(
    entries: list[dict[str, Any]],
    key: str,
) -> Any:
    for entry in entries:
        value = entry.get(key)
        if value is not None:
            return value
    return None
