from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from collector.adb_capture import (
    DEFAULT_ADB_COMMAND,
    AdbCaptureResult,
    AdbClient,
    capture_adb_screenshot,
    load_adb_capture_request,
)
from collector.capture_import import (
    CAPTURE_SOURCE_TYPE_BY_PROVIDER,
    import_capture_payload,
    load_capture_import_payload,
)
from collector.mock_import import ApiClient, DEFAULT_API_BASE_URL, ImportResult, MockImportError


@dataclass(frozen=True)
class CapturePipelineResult:
    output_dir: Path
    manifest_path: Path
    image_paths: list[Path]
    requested_page_count: int
    captured_page_count: int
    stopped_reason: str | None
    season_id: int
    snapshot_id: int
    entry_ids: list[int]
    status: str
    total_rows_collected: int | None
    ocr_provider: str


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
    adb_client: AdbClient | None = None,
    api_client: ApiClient | None = None,
) -> CapturePipelineResult:
    request = load_adb_capture_request(
        request_path,
        output_dir=output_dir,
        adb_command=adb_command,
        device_serial=device_serial,
    )

    capture_result = capture_adb_screenshot(
        request,
        adb_client or AdbClient(request.adb.adb_command),
    )
    effective_ocr_provider = _resolve_pipeline_ocr_provider(
        requested_provider=ocr_provider,
        request=request,
        capture_result=capture_result,
    )
    capture_payload = load_capture_import_payload(
        capture_result.output_dir,
        ocr_provider=effective_ocr_provider,
        ocr_command=ocr_command,
        ocr_language=ocr_language,
        ocr_psm=ocr_psm,
    )
    import_result = import_capture_payload(
        capture_payload,
        api_client or ApiClient(base_url),
    )

    return CapturePipelineResult(
        output_dir=capture_result.output_dir,
        manifest_path=capture_result.manifest_path,
        image_paths=capture_result.image_paths,
        requested_page_count=capture_result.requested_page_count,
        captured_page_count=len(capture_result.image_paths),
        stopped_reason=capture_result.stopped_reason,
        season_id=import_result.season_id,
        snapshot_id=import_result.snapshot_id,
        entry_ids=import_result.entry_ids,
        status=import_result.status,
        total_rows_collected=import_result.total_rows_collected,
        ocr_provider=capture_payload.ocr.provider,
    )


def _resolve_pipeline_ocr_provider(
    *,
    requested_provider: str | None,
    request,
    capture_result: AdbCaptureResult,
) -> str | None:
    if requested_provider is not None:
        return requested_provider

    if request.ocr_provider_explicit:
        return None

    if request.ocr.get("provider") != "sidecar":
        return None

    sidecar_exists = any(image_path.with_suffix(".txt").exists() for image_path in capture_result.image_paths)
    if sidecar_exists:
        return None

    return "tesseract"


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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
                "season_id": result.season_id,
                "snapshot_id": result.snapshot_id,
                "entry_count": len(result.entry_ids),
                "entry_ids": result.entry_ids,
                "status": result.status,
                "total_rows_collected": result.total_rows_collected,
                "ocr_provider": result.ocr_provider,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
