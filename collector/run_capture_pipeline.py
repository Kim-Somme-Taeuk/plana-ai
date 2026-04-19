from __future__ import annotations

import argparse
import json
import os
import shutil
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
    PipelineStopPolicy,
    build_pipeline_stop_policy,
    capture_adb_screenshot,
    load_adb_capture_request,
)
from collector.capture_import import (
    _build_ocr_crop,
    _is_blue_archive_fixed_layout_image,
    _parse_blue_archive_page_ranks_fast,
    CAPTURE_SOURCE_TYPE_BY_PROVIDER,
    CaptureImportPayload,
    CapturePage,
    OcrConfig,
    build_ocr_stop_hints,
    build_ocr_stop_recommendation,
    import_parsed_capture_payload,
    load_capture_import_payload,
    parse_capture_payload,
    rebuild_parsed_capture_payload_snapshot_note,
    summarize_ignored_lines,
)
from collector.mock_import import ApiClient, DEFAULT_API_BASE_URL, MockImportError


@dataclass(frozen=True)
class CapturePipelineResult:
    output_dir: Path
    manifest_path: Path
    image_paths: list[Path]
    resumed_from_output: bool
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
    stop_policy: dict[str, int | None]
    highest_rank_collected: int | None
    reached_max_rank: bool


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
    reuse_tesseract_sidecar: bool | None = None,
    persist_tesseract_sidecar: bool | None = None,
    stop_on_recommendation: str | None = None,
    stop_capture_on_recommendation: str | None = None,
    resume_only: bool = False,
    force_recapture: bool = False,
    adb_client: AdbClient | None = None,
    api_client: ApiClient | None = None,
) -> CapturePipelineResult:
    request = load_adb_capture_request(
        request_path,
        output_dir=output_dir,
        adb_command=adb_command,
        device_serial=device_serial,
    )
    current_stage = "capture"
    stop_policy = build_pipeline_stop_policy(request.pipeline)
    effective_ocr_provider = _resolve_pipeline_ocr_provider(
        requested_provider=ocr_provider,
        request=request,
    )
    stop_capture_on_recommendation_mode = _resolve_stop_on_recommendation(
        requested_stop_on_recommendation=stop_capture_on_recommendation,
        request=request,
        key="stop_capture_on_recommendation",
        default_mode="hard",
    )

    capture_result: AdbCaptureResult | None = None
    resumed_from_output = False
    try:
        if force_recapture:
            _clear_pipeline_output_dir(request.adb.output_dir)
        capture_result = _load_existing_capture_result(
            request,
            require_existing=resume_only,
        )
        if capture_result is None:
            capture_result = capture_adb_screenshot(
                request,
                adb_client or AdbClient(request.adb.adb_command),
                after_capture_page=_build_after_capture_page_callback(
                    request=request,
                    stop_policy=stop_policy,
                    effective_ocr_provider=effective_ocr_provider,
                    ocr_command=ocr_command,
                    ocr_language=ocr_language,
                    ocr_psm=ocr_psm,
                    stop_capture_on_recommendation_mode=stop_capture_on_recommendation_mode,
                ),
                persist_manifest=False,
                persist_pages_during_capture=(
                    stop_capture_on_recommendation_mode != "off"
                ),
            )
        else:
            resumed_from_output = True
        current_stage = "load_capture_payload"
        if resumed_from_output:
            capture_payload = load_capture_import_payload(
                capture_result.output_dir,
                ocr_provider=effective_ocr_provider,
                ocr_command=ocr_command,
                ocr_language=ocr_language,
                ocr_psm=ocr_psm,
                reuse_tesseract_sidecar=(
                    reuse_tesseract_sidecar
                    if reuse_tesseract_sidecar is not None
                    else resumed_from_output
                ),
                persist_tesseract_sidecar=persist_tesseract_sidecar,
            )
        else:
            capture_payload = _build_capture_import_payload_from_capture_result(
                request=request,
                capture_result=capture_result,
                effective_ocr_provider=effective_ocr_provider,
                ocr_command=ocr_command,
                ocr_language=ocr_language,
                ocr_psm=ocr_psm,
                reuse_tesseract_sidecar=reuse_tesseract_sidecar,
                persist_tesseract_sidecar=persist_tesseract_sidecar,
            )
        current_stage = "parse_capture_payload"
        parsed_payload = parse_capture_payload(capture_payload)
        parsed_payload, highest_rank_collected, reached_max_rank = _apply_max_rank_limit(
            parsed_payload=parsed_payload,
            max_rank=stop_policy.max_rank,
        )
        ocr_stop_hints = build_ocr_stop_hints(parsed_payload.page_summaries)
        ocr_stop_recommendation = _apply_stop_policy_to_recommendation(
            recommendation=build_ocr_stop_recommendation(ocr_stop_hints),
            stop_policy=stop_policy,
            captured_page_count=len(capture_result.image_paths),
        )
        pipeline_stop_recommendation = _build_pipeline_stop_recommendation(
            capture_stopped_reason=capture_result.stopped_reason,
            capture_stopped_source=capture_result.stopped_source,
            capture_stopped_level=capture_result.stopped_level,
            ocr_stop_recommendation=ocr_stop_recommendation,
        )
        parsed_payload = rebuild_parsed_capture_payload_snapshot_note(
            parsed_payload,
            snapshot=capture_payload.snapshot,
            capture=capture_payload.capture,
            extra_details={
                "pipeline_stop_recommendation": pipeline_stop_recommendation,
                "stop_policy": {
                    "min_pages_before_ocr_stop": stop_policy.min_pages_before_ocr_stop,
                    "soft_stop_repeat_threshold": stop_policy.soft_stop_repeat_threshold,
                    "max_rank": stop_policy.max_rank,
                },
                "highest_rank_collected": highest_rank_collected,
                "reached_max_rank": reached_max_rank,
            },
            ocr_stop_recommendation_override=ocr_stop_recommendation,
        )
        stop_on_recommendation_mode = _resolve_stop_on_recommendation(
            requested_stop_on_recommendation=stop_on_recommendation,
            request=request,
            key="stop_on_recommendation",
            default_mode="off",
        )
        should_skip_import = _should_skip_import_on_recommendation(
            mode=stop_on_recommendation_mode,
            pipeline_stop_recommendation=pipeline_stop_recommendation,
        )
        result_pipeline_stop_recommendation = _finalize_pipeline_stop_recommendation(
            pipeline_stop_recommendation=pipeline_stop_recommendation,
            should_skip_import=should_skip_import,
            capture_stopped_reason=capture_result.stopped_reason,
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
            current_stage = "import"
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

        result = CapturePipelineResult(
            output_dir=capture_result.output_dir,
            manifest_path=capture_result.manifest_path,
            image_paths=capture_result.image_paths,
            resumed_from_output=resumed_from_output,
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
            pipeline_stop_recommendation=result_pipeline_stop_recommendation,
            stop_policy={
                "min_pages_before_ocr_stop": stop_policy.min_pages_before_ocr_stop,
                "soft_stop_repeat_threshold": stop_policy.soft_stop_repeat_threshold,
                "max_rank": stop_policy.max_rank,
            },
            highest_rank_collected=highest_rank_collected,
            reached_max_rank=reached_max_rank,
        )
        _write_pipeline_result_artifact(
            result=result,
            request_path=request_path,
        )
        return result
    except Exception as exc:
        _write_pipeline_error_artifact(
            output_dir=_resolve_pipeline_output_dir(
                request=request,
                capture_result=capture_result,
            ),
            request_path=request_path,
            stage=current_stage,
            error=exc,
        )
        raise


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


def _load_existing_capture_result(
    request: AdbCaptureRequest,
    *,
    require_existing: bool = False,
) -> AdbCaptureResult | None:
    output_dir = request.adb.output_dir
    if not output_dir.exists():
        if require_existing:
            raise MockImportError(
                "resume-only가 지정됐지만 기존 output_dir가 없습니다. "
                f"output_dir={output_dir}"
            )
        return None

    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        if any(output_dir.iterdir()):
            raise MockImportError(
                "기존 output_dir가 비어 있지 않지만 resume 가능한 manifest.json이 없습니다. "
                f"새 output_dir를 지정하거나 디렉터리를 비우세요: {output_dir}"
            )
        if require_existing:
            raise MockImportError(
                "resume-only가 지정됐지만 기존 manifest.json이 없습니다. "
                f"output_dir={output_dir}"
            )
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MockImportError(
            f"resume용 manifest.json 파싱에 실패했습니다: {manifest_path} ({exc})"
        ) from exc

    capture = manifest.get("capture")
    if not isinstance(capture, dict):
        raise MockImportError(
            f"resume용 manifest.json에 capture 정보가 없습니다: {manifest_path}"
        )

    pages = manifest.get("pages")
    if not isinstance(pages, list):
        raise MockImportError(
            f"resume용 manifest.json에 pages 배열이 없습니다: {manifest_path}"
        )

    image_paths: list[Path] = []
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or not isinstance(page.get("image_path"), str):
            raise MockImportError(
                "resume용 manifest.json pages 형식이 올바르지 않습니다. "
                f"manifest={manifest_path}, page_index={index}"
            )
        image_paths.append(output_dir / page["image_path"])

    requested_page_count = capture.get("requested_page_count", len(image_paths))
    try:
        parsed_requested_page_count = int(requested_page_count)
    except (TypeError, ValueError) as exc:
        raise MockImportError(
            "resume용 manifest.json capture.requested_page_count가 정수가 아닙니다. "
            f"manifest={manifest_path}"
        ) from exc

    return AdbCaptureResult(
        output_dir=output_dir,
        manifest_path=manifest_path,
        image_paths=image_paths,
        requested_page_count=parsed_requested_page_count,
        stopped_reason=_normalize_optional_string(capture.get("stopped_reason")),
        stopped_source=_normalize_optional_string(capture.get("stopped_source")),
        stopped_level=_normalize_optional_string(capture.get("stopped_level")),
    )


def _clear_pipeline_output_dir(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    if not output_dir.is_dir():
        raise MockImportError(f"output_dir가 디렉터리가 아닙니다: {output_dir}")
    for child in output_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _resolve_stop_on_recommendation(
    *,
    requested_stop_on_recommendation: str | None,
    request,
    key: str,
    default_mode: str = "off",
) -> str:
    if requested_stop_on_recommendation is not None:
        return requested_stop_on_recommendation

    if key not in request.pipeline:
        return default_mode

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


def _finalize_pipeline_stop_recommendation(
    *,
    pipeline_stop_recommendation: dict[str, Any],
    should_skip_import: bool,
    capture_stopped_reason: str | None,
) -> dict[str, Any]:
    if should_skip_import:
        return pipeline_stop_recommendation
    if capture_stopped_reason is not None:
        return pipeline_stop_recommendation
    return {
        "should_stop": False,
        "level": None,
        "source": None,
        "primary_reason": None,
        "reasons": [],
    }


def _apply_stop_policy_to_recommendation(
    *,
    recommendation: dict[str, Any],
    stop_policy: PipelineStopPolicy,
    captured_page_count: int,
) -> dict[str, Any]:
    if (
        recommendation["should_stop"]
        and captured_page_count < stop_policy.min_pages_before_ocr_stop
    ):
        return {
            "should_stop": False,
            "level": None,
            "primary_reason": None,
            "reasons": [],
        }
    return recommendation


def _resolve_pipeline_output_dir(
    *,
    request: AdbCaptureRequest,
    capture_result: AdbCaptureResult | None,
) -> Path:
    if capture_result is not None:
        return capture_result.output_dir
    return request.adb.output_dir


def _normalize_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _write_pipeline_result_artifact(
    *,
    result: CapturePipelineResult,
    request_path: str | Path,
) -> None:
    artifact_path = result.output_dir / "pipeline-result.json"
    artifact_path.write_text(
        json.dumps(
            {
                "request_path": str(Path(request_path)),
                "output_dir": str(result.output_dir),
                "manifest_path": str(result.manifest_path),
                "image_paths": [str(path) for path in result.image_paths],
                "resumed_from_output": result.resumed_from_output,
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
                "stop_policy": result.stop_policy,
                "highest_rank_collected": result.highest_rank_collected,
                "reached_max_rank": result.reached_max_rank,
                "recovery": _build_pipeline_recovery_payload(
                    output_dir=result.output_dir,
                    request_path=request_path,
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _unlink_if_exists(result.output_dir / "pipeline-error.json")


def _write_pipeline_error_artifact(
    *,
    output_dir: Path,
    request_path: str | Path,
    stage: str,
    error: Exception,
) -> None:
    if not output_dir.exists() or not output_dir.is_dir():
        return

    artifact_path = output_dir / "pipeline-error.json"
    artifact_path.write_text(
        json.dumps(
            {
                "request_path": str(Path(request_path)),
                "output_dir": str(output_dir),
                "stage": stage,
                "error_type": type(error).__name__,
                "message": str(error),
                "recovery": _build_pipeline_recovery_payload(
                    output_dir=output_dir,
                    request_path=request_path,
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _unlink_if_exists(output_dir / "pipeline-result.json")


def _build_pipeline_recovery_payload(
    output_dir: Path,
    request_path: str | Path,
) -> dict[str, str]:
    recovery = {
        "rerun_pipeline_command": (
            "backend/.venv/bin/python "
            f"collector/run_capture_pipeline.py --force-recapture --output-dir {output_dir} {request_path}"
        ),
    }
    if (output_dir / "manifest.json").exists():
        recovery["capture_import_command"] = (
            "backend/.venv/bin/python "
            f"collector/capture_import.py {output_dir}"
        )
        recovery["resume_pipeline_command"] = (
            "backend/.venv/bin/python "
            f"collector/run_capture_pipeline.py --resume-only --output-dir {output_dir} {request_path}"
        )
    return recovery


def _build_capture_import_payload_from_capture_result(
    *,
    request: AdbCaptureRequest,
    capture_result: AdbCaptureResult,
    effective_ocr_provider: str | None,
    ocr_command: str | None,
    ocr_language: str | None,
    ocr_psm: int | None,
    reuse_tesseract_sidecar: bool | None,
    persist_tesseract_sidecar: bool | None,
) -> CaptureImportPayload:
    provider = effective_ocr_provider or request.ocr["provider"]
    runtime_ocr = OcrConfig(
        provider=provider,
        command=ocr_command or request.ocr.get("command"),
        language=ocr_language or request.ocr.get("language"),
        psm=ocr_psm if ocr_psm is not None else request.ocr.get("psm"),
        extra_args=tuple(request.ocr.get("extra_args", [])),
        crop=_build_ocr_crop(request.ocr.get("crop")),
        upscale_ratio=float(request.ocr.get("upscale_ratio", 1.0)),
        reuse_cached_sidecar=(
            True if reuse_tesseract_sidecar is None else reuse_tesseract_sidecar
        ),
        persist_sidecar=(
            True if persist_tesseract_sidecar is None else persist_tesseract_sidecar
        ),
        blue_archive_fast_path=False,
    )
    return CaptureImportPayload(
        base_dir=capture_result.output_dir,
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
            for image_path in capture_result.image_paths
        ],
        ocr=runtime_ocr,
        capture={
            "requested_page_count": capture_result.requested_page_count,
            "captured_page_count": len(capture_result.image_paths),
            "stopped_reason": capture_result.stopped_reason,
            "stopped_source": capture_result.stopped_source,
            "stopped_level": capture_result.stopped_level,
        },
    )


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _build_after_capture_page_callback(
    *,
    request: AdbCaptureRequest,
    stop_policy: PipelineStopPolicy,
    effective_ocr_provider: str | None,
    ocr_command: str | None,
    ocr_language: str | None,
    ocr_psm: int | None,
    stop_capture_on_recommendation_mode: str,
):
    if stop_capture_on_recommendation_mode == "off" and stop_policy.max_rank is None:
        return None
    previous_soft_reason: str | None = None
    previous_soft_count = 0
    last_highest_rank_collected: int | None = None
    latest_page_only = (
        stop_capture_on_recommendation_mode == "off"
        and stop_policy.max_rank is not None
    )

    def after_capture_page(
        image_paths: list[Path],
        latest_callback_image_path: Path | None,
    ) -> AdbCaptureStopDecision:
        nonlocal previous_soft_reason, previous_soft_count, last_highest_rank_collected
        if latest_page_only and not _should_run_max_rank_callback(
            captured_page_count=len(image_paths),
            stop_policy=stop_policy,
            last_highest_rank_collected=last_highest_rank_collected,
        ):
            return AdbCaptureStopDecision(should_continue=True)
        runtime_ocr = _build_runtime_ocr_config(
            request=request,
            effective_ocr_provider=effective_ocr_provider,
            ocr_command=ocr_command,
            ocr_language=ocr_language,
            ocr_psm=ocr_psm,
            blue_archive_fast_path=latest_page_only,
        )
        latest_image_path = latest_callback_image_path or image_paths[-1]
        if latest_page_only and _is_blue_archive_fixed_layout_image(
            image_path=latest_image_path,
            ocr=runtime_ocr,
        ):
            page_ranks = _parse_blue_archive_page_ranks_fast(
                image_path=latest_image_path,
                ocr=runtime_ocr,
            )
            highest_rank_collected = max(
                (rank for rank in page_ranks if isinstance(rank, int)),
                default=None,
            )
            if highest_rank_collected is not None:
                last_highest_rank_collected = highest_rank_collected
            if (
                stop_policy.max_rank is not None
                and highest_rank_collected is not None
                and highest_rank_collected >= stop_policy.max_rank
            ):
                return AdbCaptureStopDecision(
                    should_continue=False,
                    reason="max_rank_reached",
                    source="capture",
                    level="hard",
                )
            return AdbCaptureStopDecision(should_continue=True)
        pages_for_parse = [image_paths[-1]] if latest_page_only else image_paths
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
                    for image_path in pages_for_parse
                ],
                ocr=runtime_ocr,
                capture={
                    "requested_page_count": request.adb.page_count,
                    "captured_page_count": len(image_paths),
                    "stopped_reason": None,
                    "stopped_source": None,
                    "stopped_level": None,
                },
            ),
            validate_snapshot_entries=False,
        )
        _, highest_rank_collected, reached_max_rank = _apply_max_rank_limit(
            parsed_payload=parsed_payload,
            max_rank=stop_policy.max_rank,
        )
        if highest_rank_collected is not None:
            last_highest_rank_collected = highest_rank_collected
        if reached_max_rank:
            return AdbCaptureStopDecision(
                should_continue=False,
                reason="max_rank_reached",
                source="capture",
                level="hard",
            )
        ocr_stop_recommendation = build_ocr_stop_recommendation(
            build_ocr_stop_hints(parsed_payload.page_summaries)
        )
        stop_decision = _build_capture_stop_decision(
            mode=stop_capture_on_recommendation_mode,
            ocr_stop_recommendation=ocr_stop_recommendation,
            stop_policy=stop_policy,
            captured_page_count=len(image_paths),
            previous_soft_reason=previous_soft_reason,
            previous_soft_count=previous_soft_count,
        )
        if stop_decision is None:
            if ocr_stop_recommendation["level"] == "soft":
                if previous_soft_reason == ocr_stop_recommendation["primary_reason"]:
                    previous_soft_count += 1
                else:
                    previous_soft_reason = ocr_stop_recommendation["primary_reason"]
                    previous_soft_count = 1
            else:
                previous_soft_reason = None
                previous_soft_count = 0
            return AdbCaptureStopDecision(should_continue=True)

        previous_soft_reason = None
        previous_soft_count = 0
        return stop_decision

    return after_capture_page


def _should_run_max_rank_callback(
    *,
    captured_page_count: int,
    stop_policy: PipelineStopPolicy,
    last_highest_rank_collected: int | None = None,
) -> bool:
    if stop_policy.max_rank is None:
        return True
    if stop_policy.max_rank < 1000:
        return True
    if captured_page_count <= 1:
        return True
    near_threshold_rank = stop_policy.max_rank - max(1000, stop_policy.max_rank // 6)
    if (
        last_highest_rank_collected is not None
        and last_highest_rank_collected >= near_threshold_rank
    ):
        return True
    return captured_page_count % 3 == 0


def _build_capture_stop_decision(
    *,
    mode: str,
    ocr_stop_recommendation: dict[str, Any],
    stop_policy: PipelineStopPolicy,
    captured_page_count: int,
    previous_soft_reason: str | None,
    previous_soft_count: int,
) -> AdbCaptureStopDecision | None:
    if not ocr_stop_recommendation["should_stop"]:
        return None

    level = ocr_stop_recommendation["level"]
    reason = ocr_stop_recommendation["primary_reason"]

    if captured_page_count < stop_policy.min_pages_before_ocr_stop:
        return None

    if level == "hard" and reason in {
        "noisy_last_page",
        "duplicate_last_page",
        "malformed_last_page",
    }:
        return None

    if level == "hard":
        return AdbCaptureStopDecision(
            should_continue=False,
            reason=reason,
            source="ocr",
            level=level,
            discard_last_page=(reason == "duplicate_last_page"),
        )

    if mode != "any":
        return None

    if previous_soft_reason != reason:
        return None

    if previous_soft_count + 1 < stop_policy.soft_stop_repeat_threshold:
        return None

    return AdbCaptureStopDecision(
        should_continue=False,
        reason=reason,
        source="ocr",
        level=level,
        discard_last_page=(reason == "duplicate_last_page"),
    )


def _build_runtime_ocr_config(
    *,
    request: AdbCaptureRequest,
    effective_ocr_provider: str | None,
    ocr_command: str | None,
    ocr_language: str | None,
    ocr_psm: int | None,
    blue_archive_fast_path: bool = False,
) -> OcrConfig:
    provider = effective_ocr_provider or request.ocr["provider"]
    return OcrConfig(
        provider=provider,
        command=ocr_command or request.ocr.get("command"),
        language=ocr_language or request.ocr.get("language"),
        psm=ocr_psm if ocr_psm is not None else request.ocr.get("psm"),
        extra_args=tuple(request.ocr.get("extra_args", [])),
        crop=_build_ocr_crop(request.ocr.get("crop")),
        upscale_ratio=min(float(request.ocr.get("upscale_ratio", 1.0)), 1.5)
        if blue_archive_fast_path
        else float(request.ocr.get("upscale_ratio", 1.0)),
        reuse_cached_sidecar=True,
        persist_sidecar=not blue_archive_fast_path,
        blue_archive_fast_path=blue_archive_fast_path,
    )


def _apply_max_rank_limit(
    *,
    parsed_payload,
    max_rank: int | None,
):
    entries = parsed_payload.mock_payload.entries
    highest_rank_collected = max(
        (
            entry["rank"]
            for entry in entries
            if isinstance(entry.get("rank"), int)
        ),
        default=None,
    )
    if max_rank is None or highest_rank_collected is None:
        return parsed_payload, highest_rank_collected, False

    reached_max_rank = highest_rank_collected >= max_rank
    if not reached_max_rank:
        return parsed_payload, highest_rank_collected, False

    filtered_entries = [
        entry
        for entry in entries
        if not isinstance(entry.get("rank"), int) or entry["rank"] <= max_rank
    ]
    if len(filtered_entries) == len(entries):
        return parsed_payload, highest_rank_collected, True

    return (
        type(parsed_payload)(
            mock_payload=type(parsed_payload.mock_payload)(
                season=parsed_payload.mock_payload.season,
                snapshot=parsed_payload.mock_payload.snapshot,
                entries=filtered_entries,
            ),
            ignored_lines=parsed_payload.ignored_lines,
            page_summaries=parsed_payload.page_summaries,
        ),
        highest_rank_collected,
        True,
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
        "--reuse-tesseract-sidecar",
        action="store_true",
        help="tesseract provider에서 기존 OCR sidecar(.txt)가 있으면 재사용합니다.",
    )
    parser.add_argument(
        "--no-persist-tesseract-sidecar",
        action="store_true",
        help="tesseract provider에서 OCR 결과 sidecar(.txt)를 저장하지 않습니다.",
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
    parser.add_argument(
        "--resume-only",
        action="store_true",
        help="기존 output_dir의 manifest.json이 있을 때만 resume하고 새 캡처는 하지 않습니다.",
    )
    parser.add_argument(
        "--force-recapture",
        action="store_true",
        help="기존 output_dir 내용을 지우고 처음부터 다시 캡처합니다.",
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
    if args.resume_only and args.force_recapture:
        parser.error("--resume-only와 --force-recapture는 함께 사용할 수 없습니다.")

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
            reuse_tesseract_sidecar=True if args.reuse_tesseract_sidecar else None,
            persist_tesseract_sidecar=False if args.no_persist_tesseract_sidecar else None,
            stop_on_recommendation=stop_on_recommendation,
            stop_capture_on_recommendation=stop_capture_on_recommendation,
            resume_only=args.resume_only,
            force_recapture=args.force_recapture,
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
                "resumed_from_output": result.resumed_from_output,
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
                "stop_policy": result.stop_policy,
                "highest_rank_collected": result.highest_rank_collected,
                "reached_max_rank": result.reached_max_rank,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
