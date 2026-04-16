from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
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
    }
)
OCR_SEPARATOR_CHARACTERS = frozenset("-_=|:;.,·~")


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
    )


def build_mock_payload_from_capture(
    payload: CaptureImportPayload,
) -> MockImportPayload:
    return parse_capture_payload(payload).mock_payload


def parse_capture_payload(
    payload: CaptureImportPayload,
) -> ParsedCapturePayload:
    entries: list[dict[str, Any]] = []
    ignored_lines: list[IgnoredOcrLine] = []

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

    _validate_snapshot_entries(entries)

    return ParsedCapturePayload(
        mock_payload=MockImportPayload(
            season=payload.season,
            snapshot=payload.snapshot,
            entries=entries,
        ),
        ignored_lines=ignored_lines,
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
) -> list[dict[str, Any]]:
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

    return entries, ignored_lines


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
    normalized = _normalize_integer_ocr_token(value)
    try:
        return int(normalized)
    except ValueError as exc:
        raise MockImportError(
            f"{label} 파싱에 실패했습니다. page={page_index}, line={line_index}, value={value!r}"
        ) from exc


def _can_parse_rank_token(value: str) -> bool:
    normalized = _normalize_integer_ocr_token(value)
    return normalized.isdigit()


def _get_ignored_line_reason(raw_line: str) -> str | None:
    stripped = raw_line.strip()
    if not stripped:
        return "blank_line"

    if _looks_like_separator_line(stripped):
        return "separator_line"

    first_token = stripped.split()[0]
    if not _can_parse_rank_token(first_token):
        return "non_entry_line"

    return None


def _looks_like_separator_line(value: str) -> bool:
    return all(character in OCR_SEPARATOR_CHARACTERS for character in value)


def _parse_float_token(
    value: str,
    label: str,
    page_index: int,
    line_index: int,
) -> float:
    normalized = _normalize_float_ocr_token(value)
    try:
        return float(normalized)
    except ValueError as exc:
        raise MockImportError(
            f"{label} 파싱에 실패했습니다. page={page_index}, line={line_index}, value={value!r}"
        ) from exc


def _normalize_integer_ocr_token(value: str) -> str:
    normalized = value.strip().replace(",", "").translate(OCR_NUMERIC_TRANSLATION)
    return normalized.strip(".:;")


def _normalize_float_ocr_token(value: str) -> str:
    normalized = value.strip().replace(",", "").translate(OCR_NUMERIC_TRANSLATION)
    return normalized.strip(".:;")


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


def _looks_like_confidence_token(value: str) -> bool:
    stripped = _normalize_float_ocr_token(value)
    if "." not in stripped:
        return False

    try:
        parsed = float(stripped)
    except ValueError:
        return False

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
    last_token_normalized = _normalize_integer_ocr_token(body_tokens[-1])
    if len(last_token_normalized) > 3:
        return body_tokens[-1:], body_tokens[:-1]

    while score_start > 0:
        candidate = body_tokens[score_start - 1]
        normalized_candidate = _normalize_integer_ocr_token(candidate)
        if not (normalized_candidate.isdigit() and len(normalized_candidate) == 3):
            break
        score_start -= 1

    if score_start > 0:
        leading_candidate = _normalize_integer_ocr_token(body_tokens[score_start - 1])
        if leading_candidate.isdigit() and 2 <= len(leading_candidate) <= 3:
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

    normalized_tokens = [_normalize_integer_ocr_token(token) for token in score_tokens]
    if not all(token.isdigit() for token in normalized_tokens):
        raise MockImportError(
            "OCR line 파싱에 실패했습니다. "
            f"page={page_index}, line={line_index}, grouped score token이 숫자가 아닙니다."
        )

    return int("".join(normalized_tokens))


def _normalize_player_name(value: str) -> str:
    return " ".join(value.split())


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
