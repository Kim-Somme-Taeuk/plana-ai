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

from collector.adb_capture import (
    DEFAULT_ADB_COMMAND,
    AdbCaptureRequest,
    AdbCaptureResult,
    AdbCaptureStopDecision,
    AdbClient,
    capture_adb_screenshot,
    load_adb_capture_request,
)
from collector.capture_import import (
    CAPTURE_SOURCE_TYPE_BY_PROVIDER,
    CaptureImportPayload,
    CapturePage,
    OcrConfig,
    build_ocr_stop_hints,
    build_ocr_stop_recommendation,
    import_parsed_capture_payload,
    load_capture_import_payload,
    parse_capture_payload,
    summarize_ignored_lines,
)
from collector.mock_import import ApiClient, DEFAULT_API_BASE_URL, MockImportError


@dataclass(frozen=True)
class CapturePipelineResult:
    output_dir: Path
    manifest_path: Path
    image_paths: list[Path]
    requested_page_count: int
    captured_page_count: int
    stopped_reason: str | None
    import_skipped: bool
    skip_reason: str | None
    season_id: int | None
    snapshot_id: int | None
    entry_ids: list[int]
    status: str | None
    total_rows_collected: int | None
    ocr_provider: str
    ignored_line_count: int
    ignored_line_reasons: list[dict[str, int | str]]
    page_summaries: list[dict[str, Any]]
    ocr_stop_hints: list[dict[str, Any]]
    ocr_stop_recommendation: dict[str, Any]
    pipeline_stop_recommendation: dict[str, Any]


def run_capture_pipeline(
    request_path: str | Path,
    *,
    base_url: str,
    output_dir: str | None = None,
    adb_command: str | None = None,
    device_serial: str | None = None,
    ocr_provider: str | None = None,
    ocr_command: str | None = None,
    ocr_language: str | None = None,
    ocr_psm: int | None = None,
    stop_on_recommendation: str | None = None,
    stop_capture_on_recommendation: str | None = None,
    adb_client: AdbClient | None = None,
    api_client: ApiClient | None = None,
) -> CapturePipelineResult:
    request = load_adb_capture_request(
        request_path,
        output_dir=output_dir,
        adb_command=adb_command,
        device_serial=device_serial,
    )
    effective_ocr_provider = _resolve_pipeline_ocr_provider(
        requested_provider=ocr_provider,
        request=request,
    )
    stop_capture_on_recommendation_mode = _resolve_stop_on_recommendation(
        requested_stop_on_recommendation=stop_capture_on_recommendation,
        request=request,
        key="stop_capture_on_recommendation",
    )

    capture_result = capture_adb_screenshot(
        request,
        adb_client or AdbClient(request.adb.adb_command),
        after_capture_page=_build_after_capture_page_callback(
            request=request,
            effective_ocr_provider=effective_ocr_provider,
            ocr_command=ocr_command,
            ocr_language=ocr_language,
            ocr_psm=ocr_psm,
            stop_capture_on_recommendation_mode=stop_capture_on_recommendation_mode,
        ),
    )
    capture_payload = load_capture_import_payload(
        capture_result.output_dir,
        ocr_provider=effective_ocr_provider,
        ocr_command=ocr_command,
        ocr_language=ocr_language,
        ocr_psm=ocr_psm,
    )
    parsed_payload = parse_capture_payload(capture_payload)
    ocr_stop_hints = build_ocr_stop_hints(parsed_payload.page_summaries)
    ocr_stop_recommendation = build_ocr_stop_recommendation(ocr_stop_hints)
    pipeline_stop_recommendation = _build_pipeline_stop_recommendation(
        capture_stopped_reason=capture_result.stopped_reason,
        capture_stopped_source=capture_result.stopped_source,
        capture_stopped_level=capture_result.stopped_level,
        ocr_stop_recommendation=ocr_stop_recommendation,
    )
    stop_on_recommendation_mode = _resolve_stop_on_recommendation(
        requested_stop_on_recommendation=stop_on_recommendation,
        request=request,
        key="stop_on_recommendation",
    )
    should_skip_import = _should_skip_import_on_recommendation(
        mode=stop_on_recommendation_mode,
        pipeline_stop_recommendation=pipeline_stop_recommendation,
    )

    if should_skip_import:
        import_skipped = True
        skip_reason = pipeline_stop_recommendation["primary_reason"]
        season_id = None
        snapshot_id = None
        entry_ids: list[int] = []
        status = None
        total_rows_collected = None
    else:
        import_result = import_parsed_capture_payload(
            parsed_payload,
            api_client or ApiClient(base_url),
        )
        import_skipped = False
        skip_reason = None
        season_id = import_result.season_id
        snapshot_id = import_result.snapshot_id
        entry_ids = import_result.entry_ids
        status = import_result.status
        total_rows_collected = import_result.total_rows_collected

    return CapturePipelineResult(
        output_dir=capture_result.output_dir,
        manifest_path=capture_result.manifest_path,
        image_paths=capture_result.image_paths,
        requested_page_count=capture_result.requested_page_count,
        captured_page_count=len(capture_result.image_paths),
        stopped_reason=capture_result.stopped_reason,
        import_skipped=import_skipped,
        skip_reason=skip_reason,
        season_id=season_id,
        snapshot_id=snapshot_id,
        entry_ids=entry_ids,
        status=status,
        total_rows_collected=total_rows_collected,
        ocr_provider=capture_payload.ocr.provider,
        ignored_line_count=len(parsed_payload.ignored_lines),
        ignored_line_reasons=summarize_ignored_lines(parsed_payload.ignored_lines),
        page_summaries=parsed_payload.page_summaries,
        ocr_stop_hints=ocr_stop_hints,
        ocr_stop_recommendation=ocr_stop_recommendation,
        pipeline_stop_recommendation=pipeline_stop_recommendation,
    )


def _resolve_pipeline_ocr_provider(
    *,
    requested_provider: str | None,
    request,
) -> str | None:
    if requested_provider is not None:
        return requested_provider

    if request.ocr_provider_explicit:
        return None

    if request.ocr.get("provider") != "sidecar":
        return None

    return "tesseract"


def _resolve_stop_on_recommendation(
    *,
    requested_stop_on_recommendation: str | None,
    request,
    key: str,
) -> str:
    if requested_stop_on_recommendation is not None:
        return requested_stop_on_recommendation

    raw_value = request.pipeline.get(key, False)
    if isinstance(raw_value, bool):
        return "hard" if raw_value else "off"
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "hard"}:
            return "hard"
        if normalized in {"any", "soft"}:
            return "any"
        if normalized in {"0", "false", "no", "off", ""}:
            return "off"
    return "hard" if bool(raw_value) else "off"


def _should_skip_import_on_recommendation(
    *,
    mode: str,
    pipeline_stop_recommendation: dict[str, Any],
) -> bool:
    if mode == "off" or not pipeline_stop_recommendation["should_stop"]:
        return False

    if mode == "any":
        return True

    return pipeline_stop_recommendation.get("level") == "hard"


def _build_pipeline_stop_recommendation(
    *,
    capture_stopped_reason: str | None,
    capture_stopped_source: str | None,
    capture_stopped_level: str | None,
    ocr_stop_recommendation: dict[str, Any],
) -> dict[str, Any]:
    if capture_stopped_reason is not None:
        return {
            "should_stop": True,
            "level": capture_stopped_level,
            "source": capture_stopped_source,
            "primary_reason": capture_stopped_reason,
            "reasons": [capture_stopped_reason],
        }

    if ocr_stop_recommendation["should_stop"]:
        reasons = list(ocr_stop_recommendation["reasons"])
        return {
            "should_stop": True,
            "level": ocr_stop_recommendation["level"],
            "source": "ocr",
            "primary_reason": ocr_stop_recommendation["primary_reason"],
            "reasons": reasons,
        }

    return {
        "should_stop": False,
        "level": None,
        "source": None,
        "primary_reason": None,
        "reasons": [],
    }


def _build_after_capture_page_callback(
    *,
    request: AdbCaptureRequest,
    effective_ocr_provider: str | None,
    ocr_command: str | None,
    ocr_language: str | None,
    ocr_psm: int | None,
    stop_capture_on_recommendation_mode: str,
):
    if stop_capture_on_recommendation_mode == "off":
        return None

    def after_capture_page(image_paths: list[Path]) -> AdbCaptureStopDecision:
        parsed_payload = parse_capture_payload(
            CaptureImportPayload(
                base_dir=request.adb.output_dir,
                season=request.season,
                snapshot={
                    **request.snapshot,
                    "source_type": CAPTURE_SOURCE_TYPE_BY_PROVIDER[
                        effective_ocr_provider or request.ocr["provider"]
                    ],
                },
                pages=[
                    CapturePage(
                        image_path=image_path.name,
                        ocr_text_path=None,
                        default_ocr_confidence=None,
                    )
                    for image_path in image_paths
                ],
                ocr=_build_runtime_ocr_config(
                    request=request,
                    effective_ocr_provider=effective_ocr_provider,
                    ocr_command=ocr_command,
                    ocr_language=ocr_language,
                    ocr_psm=ocr_psm,
                ),
            )
        )
        ocr_stop_recommendation = build_ocr_stop_recommendation(
            build_ocr_stop_hints(parsed_payload.page_summaries)
        )
        if not _should_skip_import_on_recommendation(
            mode=stop_capture_on_recommendation_mode,
            pipeline_stop_recommendation=ocr_stop_recommendation,
        ):
            return AdbCaptureStopDecision(should_continue=True)

        return AdbCaptureStopDecision(
            should_continue=False,
            reason=ocr_stop_recommendation["primary_reason"],
            source="ocr",
            level=ocr_stop_recommendation["level"],
        )

    return after_capture_page


def _build_runtime_ocr_config(
    *,
    request: AdbCaptureRequest,
    effective_ocr_provider: str | None,
    ocr_command: str | None,
    ocr_language: str | None,
    ocr_psm: int | None,
) -> OcrConfig:
    provider = effective_ocr_provider or request.ocr["provider"]
    return OcrConfig(
        provider=provider,
        command=ocr_command or request.ocr.get("command"),
        language=ocr_language or request.ocr.get("language"),
        psm=ocr_psm if ocr_psm is not None else request.ocr.get("psm"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ADB capture부터 OCR import까지 한 번에 수행합니다.",
    )
    parser.add_argument(
        "request_path",
        help="ADB capture 요청 JSON 파일 경로",
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
        "--output-dir",
        help="capture output 디렉터리 override",
    )
    parser.add_argument(
        "--adb-command",
        default=os.getenv("PLANA_AI_ADB_COMMAND"),
        help=f"adb 명령 경로 override (default: {DEFAULT_ADB_COMMAND})",
    )
    parser.add_argument(
        "--device-serial",
        help="ADB device serial override",
    )
    parser.add_argument(
        "--ocr-provider",
        choices=sorted(CAPTURE_SOURCE_TYPE_BY_PROVIDER),
        help="OCR provider override (default: request/manifest 설정)",
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
        "--stop-on-recommendation",
        action="store_true",
        help="hard stop recommendation이 있으면 backend import를 건너뜁니다.",
    )
    parser.add_argument(
        "--stop-on-soft-recommendation",
        action="store_true",
        help="soft/hard stop recommendation이 있으면 backend import를 건너뜁니다.",
    )
    parser.add_argument(
        "--stop-capture-on-recommendation",
        action="store_true",
        help="hard stop recommendation이 있으면 남은 캡처를 생략합니다.",
    )
    parser.add_argument(
        "--stop-capture-on-soft-recommendation",
        action="store_true",
        help="soft/hard stop recommendation이 있으면 남은 캡처를 생략합니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.stop_on_recommendation and args.stop_on_soft_recommendation:
        parser.error("--stop-on-recommendation과 --stop-on-soft-recommendation은 함께 사용할 수 없습니다.")
    if args.stop_capture_on_recommendation and args.stop_capture_on_soft_recommendation:
        parser.error(
            "--stop-capture-on-recommendation과 --stop-capture-on-soft-recommendation은 함께 사용할 수 없습니다."
        )

    stop_on_recommendation: str | None = None
    if args.stop_on_soft_recommendation:
        stop_on_recommendation = "any"
    elif args.stop_on_recommendation:
        stop_on_recommendation = "hard"

    stop_capture_on_recommendation: str | None = None
    if args.stop_capture_on_soft_recommendation:
        stop_capture_on_recommendation = "any"
    elif args.stop_capture_on_recommendation:
        stop_capture_on_recommendation = "hard"

    try:
        result = run_capture_pipeline(
            args.request_path,
            base_url=args.base_url,
            output_dir=args.output_dir,
            adb_command=args.adb_command,
            device_serial=args.device_serial,
            ocr_provider=args.ocr_provider,
            ocr_command=args.ocr_command,
            ocr_language=args.ocr_language,
            ocr_psm=args.ocr_psm,
            stop_on_recommendation=stop_on_recommendation,
            stop_capture_on_recommendation=stop_capture_on_recommendation,
        )
    except MockImportError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "output_dir": str(result.output_dir),
                "manifest_path": str(result.manifest_path),
                "image_paths": [str(path) for path in result.image_paths],
                "requested_page_count": result.requested_page_count,
                "captured_page_count": result.captured_page_count,
                "stopped_reason": result.stopped_reason,
                "import_skipped": result.import_skipped,
                "skip_reason": result.skip_reason,
                "season_id": result.season_id,
                "snapshot_id": result.snapshot_id,
                "entry_count": len(result.entry_ids),
                "entry_ids": result.entry_ids,
                "status": result.status,
                "total_rows_collected": result.total_rows_collected,
                "ocr_provider": result.ocr_provider,
                "ignored_line_count": result.ignored_line_count,
                "ignored_line_reasons": result.ignored_line_reasons,
                "page_summaries": result.page_summaries,
                "ocr_stop_hints": result.ocr_stop_hints,
                "ocr_stop_recommendation": result.ocr_stop_recommendation,
                "pipeline_stop_recommendation": result.pipeline_stop_recommendation,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
