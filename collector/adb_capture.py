from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from collector.capture_import import OCR_PROVIDER_SIDECAR
from collector.mock_import import (
    DEFAULT_API_BASE_URL,
    MockImportError,
    SEASON_REQUIRED_FIELDS,
    SNAPSHOT_REQUIRED_FIELDS,
)

DEFAULT_ADB_COMMAND = "adb"
DEFAULT_CAPTURE_NOTE = "adb screenshot capture"
LATEST_CAPTURE_PREVIEW_NAME = ".latest-page.png"
ADB_DEVICES_TIMEOUT_SECONDS = 10
ADB_SCREENSHOT_TIMEOUT_SECONDS = 20
ADB_SWIPE_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class AdbOptions:
    output_dir: Path
    device_serial: str | None
    page_prefix: str
    adb_command: str
    page_count: int
    stop_on_duplicate_frame: bool
    swipe: "AdbSwipeConfig | None"


@dataclass(frozen=True)
class AdbSwipeConfig:
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration_ms: int
    settle_delay_ms: int


@dataclass(frozen=True)
class AdbCaptureRequest:
    season: dict[str, Any]
    snapshot: dict[str, Any]
    ocr: dict[str, Any]
    adb: AdbOptions
    pipeline: dict[str, Any]
    ocr_provider_explicit: bool


@dataclass(frozen=True)
class PipelineStopPolicy:
    min_pages_before_ocr_stop: int
    soft_stop_repeat_threshold: int
    max_rank: int | None


@dataclass(frozen=True)
class AdbCaptureResult:
    output_dir: Path
    manifest_path: Path
    image_paths: list[Path]
    requested_page_count: int
    stopped_reason: str | None
    stopped_source: str | None
    stopped_level: str | None


@dataclass(frozen=True)
class AdbCaptureStopDecision:
    should_continue: bool
    reason: str | None = None
    source: str | None = None
    level: str | None = None
    discard_last_page: bool = False


@dataclass(frozen=True)
class AdbDeviceInfo:
    serial: str
    state: str


class AdbClient:
    def __init__(self, command: str):
        self.command = command

    def list_devices(self) -> list[AdbDeviceInfo]:
        args = [self.command, "devices"]
        result = self._run_command(
            args,
            failure_message=f"adb devices 실행에 실패했습니다: command={self.command!r}",
            timeout_seconds=ADB_DEVICES_TIMEOUT_SECONDS,
        )

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip() or "unknown error"
            raise MockImportError(
                "adb devices 조회에 실패했습니다. "
                f"returncode={result.returncode}, stderr={stderr}"
            )

        output = result.stdout.decode("utf-8", errors="replace")
        devices: list[AdbDeviceInfo] = []
        for raw_line in output.splitlines()[1:]:
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            devices.append(
                AdbDeviceInfo(
                    serial=parts[0],
                    state=parts[1],
                )
            )
        return devices

    def preflight(self, *, device_serial: str | None) -> None:
        devices = self.list_devices()
        if not devices:
            raise MockImportError(
                "연결된 adb device가 없습니다. "
                "기기를 연결하고 `adb devices` 출력 상태를 확인하세요."
            )

        if device_serial is not None:
            target_device = next(
                (device for device in devices if device.serial == device_serial),
                None,
            )
            if target_device is None:
                available_devices = ", ".join(
                    f"{device.serial}({device.state})" for device in devices
                )
                raise MockImportError(
                    "지정한 adb device를 찾지 못했습니다. "
                    f"device_serial={device_serial}, available={available_devices}"
                )
            if target_device.state != "device":
                raise MockImportError(
                    "지정한 adb device를 사용할 수 없습니다. "
                    f"device_serial={device_serial}, state={target_device.state}"
                )
            return

        if len(devices) > 1:
            available_devices = ", ".join(
                f"{device.serial}({device.state})" for device in devices
            )
            raise MockImportError(
                "여러 adb device가 연결되어 있어 device_serial 지정이 필요합니다. "
                f"available={available_devices}"
            )

        only_device = devices[0]
        if only_device.state != "device":
            raise MockImportError(
                "연결된 adb device를 사용할 수 없습니다. "
                f"device_serial={only_device.serial}, state={only_device.state}"
            )

    def capture_screenshot(self, *, device_serial: str | None) -> bytes:
        args = self._build_args(device_serial)
        args.extend(["exec-out", "screencap", "-p"])

        result = self._run_command(
            args,
            failure_message=f"adb screenshot 실행에 실패했습니다: command={self.command!r}",
            timeout_seconds=ADB_SCREENSHOT_TIMEOUT_SECONDS,
        )

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip() or "unknown error"
            raise MockImportError(
                "adb screenshot 캡처에 실패했습니다. "
                f"returncode={result.returncode}, stderr={stderr}"
            )

        if not result.stdout:
            raise MockImportError("adb screenshot 결과가 비어 있습니다.")

        return result.stdout

    def swipe(
        self,
        *,
        device_serial: str | None,
        swipe: AdbSwipeConfig,
    ) -> None:
        args = self._build_args(device_serial)
        args.extend(
            [
                "shell",
                "input",
                "swipe",
                str(swipe.start_x),
                str(swipe.start_y),
                str(swipe.end_x),
                str(swipe.end_y),
                str(swipe.duration_ms),
            ]
        )

        result = self._run_command(
            args,
            failure_message=f"adb swipe 실행에 실패했습니다: command={self.command!r}",
            timeout_seconds=ADB_SWIPE_TIMEOUT_SECONDS,
        )

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip() or "unknown error"
            raise MockImportError(
                "adb swipe에 실패했습니다. "
                f"returncode={result.returncode}, stderr={stderr}"
            )

    def _build_args(self, device_serial: str | None) -> list[str]:
        if shutil.which(self.command) is None:
            raise MockImportError(
                f"adb 명령을 찾을 수 없습니다: command={self.command!r}"
            )

        args = [self.command]
        if device_serial:
            args.extend(["-s", device_serial])
        return args

    def _run_command(
        self,
        args: list[str],
        *,
        failure_message: str,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[bytes]:
        if shutil.which(self.command) is None:
            raise MockImportError(
                f"adb 명령을 찾을 수 없습니다: command={self.command!r}"
            )

        try:
            return subprocess.run(
                args,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            command_label = " ".join(args[:3]) if args else self.command
            raise MockImportError(
                f"{command_label} 명령이 시간 초과로 중단됐습니다. "
                f"timeout={timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise MockImportError(failure_message) from exc


def load_adb_capture_request(
    path: str | Path,
    *,
    output_dir: str | None = None,
    adb_command: str | None = None,
    device_serial: str | None = None,
) -> AdbCaptureRequest:
    request_path = Path(path)
    try:
        raw_payload = json.loads(request_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MockImportError(f"ADB capture 요청 파일을 찾을 수 없습니다: {request_path}") from exc
    except json.JSONDecodeError as exc:
        raise MockImportError(
            f"ADB capture 요청 JSON 파싱에 실패했습니다: {request_path} ({exc})"
        ) from exc

    root = _require_mapping(raw_payload, "root")
    season = _require_mapping(root.get("season"), "season")
    snapshot = _require_mapping(root.get("snapshot"), "snapshot")
    ocr = _require_optional_mapping(root.get("ocr"), "ocr")
    adb = _require_optional_mapping(root.get("adb"), "adb")
    pipeline = _require_optional_mapping(root.get("pipeline"), "pipeline")
    ocr_provider_explicit = "provider" in ocr

    _require_fields(season, SEASON_REQUIRED_FIELDS, "season")
    _require_fields(snapshot, SNAPSHOT_REQUIRED_FIELDS, "snapshot")

    resolved_output_dir = _resolve_output_dir(
        request_path.parent,
        output_dir,
        adb.get("output_dir"),
    )
    page_prefix = adb.get("page_prefix", "page")
    if not isinstance(page_prefix, str) or not page_prefix.strip():
        raise MockImportError("adb.page_prefix는 비어 있지 않은 문자열이어야 합니다.")
    page_count = adb.get("page_count", 1)
    try:
        page_count = int(page_count)
    except (TypeError, ValueError) as exc:
        raise MockImportError("adb.page_count는 정수여야 합니다.") from exc
    if page_count <= 0:
        raise MockImportError("adb.page_count는 1 이상이어야 합니다.")
    stop_on_duplicate_frame = _parse_boolean_option(
        adb.get("stop_on_duplicate_frame", True),
        "adb.stop_on_duplicate_frame",
    )

    swipe = _build_swipe_config(adb.get("swipe"))
    if page_count > 1 and swipe is None:
        raise MockImportError(
            "adb.page_count가 2 이상이면 adb.swipe 설정이 필요합니다."
        )

    return AdbCaptureRequest(
        season=season,
        snapshot={
            **snapshot,
            "note": snapshot.get("note") or DEFAULT_CAPTURE_NOTE,
        },
        ocr={
            "provider": ocr.get("provider", OCR_PROVIDER_SIDECAR),
            **{key: value for key, value in ocr.items() if key != "provider"},
        },
        adb=AdbOptions(
            output_dir=resolved_output_dir,
            device_serial=device_serial or adb.get("device_serial"),
            page_prefix=page_prefix,
            adb_command=adb_command or adb.get("command") or DEFAULT_ADB_COMMAND,
            page_count=page_count,
            stop_on_duplicate_frame=stop_on_duplicate_frame,
            swipe=swipe,
        ),
        pipeline=pipeline,
        ocr_provider_explicit=ocr_provider_explicit,
    )


AfterCapturePageCallback = Callable[[list[Path], Path | None], AdbCaptureStopDecision]


def build_pipeline_stop_policy(pipeline: dict[str, Any]) -> PipelineStopPolicy:
    min_pages_before_ocr_stop = _parse_positive_int_option(
        pipeline.get("min_pages_before_ocr_stop", 2),
        "pipeline.min_pages_before_ocr_stop",
        minimum=2,
    )
    soft_stop_repeat_threshold = _parse_positive_int_option(
        pipeline.get("soft_stop_repeat_threshold", 2),
        "pipeline.soft_stop_repeat_threshold",
        minimum=2,
    )
    max_rank = pipeline.get("max_rank")
    if max_rank is None:
        parsed_max_rank = None
    else:
        parsed_max_rank = _parse_positive_int_option(
            max_rank,
            "pipeline.max_rank",
            minimum=1,
        )

    return PipelineStopPolicy(
        min_pages_before_ocr_stop=min_pages_before_ocr_stop,
        soft_stop_repeat_threshold=soft_stop_repeat_threshold,
        max_rank=parsed_max_rank,
    )


def capture_adb_screenshot(
    request: AdbCaptureRequest,
    client: AdbClient,
    *,
    after_capture_page: AfterCapturePageCallback | None = None,
    persist_manifest: bool = True,
    persist_pages_during_capture: bool = True,
) -> AdbCaptureResult:
    _run_adb_preflight_if_available(client, request.adb.device_serial)
    _ensure_capture_output_dir_is_empty(request.adb.output_dir)
    request.adb.output_dir.mkdir(parents=True, exist_ok=True)

    image_paths: list[Path] = []
    pending_page_images: list[tuple[Path, bytes]] = []
    previous_image_bytes: bytes | None = None
    seen_frame_hashes: set[str] = set()
    stopped_reason: str | None = None
    stopped_source: str | None = None
    stopped_level: str | None = None
    latest_capture_preview_path = request.adb.output_dir / LATEST_CAPTURE_PREVIEW_NAME
    for page_number in range(1, request.adb.page_count + 1):
        image_path = (
            request.adb.output_dir / f"{request.adb.page_prefix}-{page_number:03d}.png"
        )
        image_bytes = client.capture_screenshot(device_serial=request.adb.device_serial)
        image_hash = hashlib.sha256(image_bytes).hexdigest()

        if (
            request.adb.stop_on_duplicate_frame
            and previous_image_bytes is not None
            and image_bytes == previous_image_bytes
        ):
            stopped_reason = "duplicate_frame"
            stopped_source = "capture"
            stopped_level = "hard"
            break
        if request.adb.stop_on_duplicate_frame and image_hash in seen_frame_hashes:
            stopped_reason = "repeated_frame"
            stopped_source = "capture"
            stopped_level = "hard"
            break

        if persist_pages_during_capture:
            image_path.write_bytes(image_bytes)
            latest_callback_image_path = image_path
        elif after_capture_page is not None:
            latest_capture_preview_path.write_bytes(image_bytes)
            latest_callback_image_path = latest_capture_preview_path
        else:
            latest_callback_image_path = None
        image_paths.append(image_path)
        pending_page_images.append((image_path, image_bytes))
        previous_image_bytes = image_bytes
        seen_frame_hashes.add(image_hash)

        if page_number < request.adb.page_count and after_capture_page is not None:
            stop_decision = after_capture_page(
                list(image_paths),
                latest_callback_image_path,
            )
            if not stop_decision.should_continue:
                if stop_decision.discard_last_page and image_paths:
                    last_image_path = image_paths.pop()
                    pending_page_images.pop()
                    _unlink_if_exists(last_image_path)
                    if not persist_pages_during_capture:
                        _unlink_if_exists(latest_capture_preview_path)
                stopped_reason = stop_decision.reason
                stopped_source = stop_decision.source
                stopped_level = stop_decision.level
                break
            if not persist_pages_during_capture:
                _unlink_if_exists(latest_capture_preview_path)

        if page_number < request.adb.page_count:
            assert request.adb.swipe is not None  # guarded during request loading
            client.swipe(
                device_serial=request.adb.device_serial,
                swipe=request.adb.swipe,
            )
            effective_settle_delay_ms = _resolve_effective_settle_delay_ms(
                request=request,
                after_capture_page=after_capture_page,
                page_number=page_number,
            )
            if effective_settle_delay_ms > 0:
                time.sleep(effective_settle_delay_ms / 1000)

    if not persist_pages_during_capture:
        for image_path, image_bytes in pending_page_images:
            image_path.write_bytes(image_bytes)
        _unlink_if_exists(latest_capture_preview_path)

    runtime_snapshot = {
        **request.snapshot,
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    manifest_path = request.adb.output_dir / "manifest.json"
    if persist_manifest:
        manifest_path.write_text(
            json.dumps(
                {
                    "season": request.season,
                    "snapshot": runtime_snapshot,
                    "ocr": request.ocr,
                    "capture": {
                        "requested_page_count": request.adb.page_count,
                        "captured_page_count": len(image_paths),
                        "stopped_reason": stopped_reason,
                        "stopped_source": stopped_source,
                        "stopped_level": stopped_level,
                    },
                    "pages": [
                        {
                            "image_path": image_path.name,
                        }
                        for image_path in image_paths
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return AdbCaptureResult(
        output_dir=request.adb.output_dir,
        manifest_path=manifest_path,
        image_paths=image_paths,
        requested_page_count=request.adb.page_count,
        stopped_reason=stopped_reason,
        stopped_source=stopped_source,
        stopped_level=stopped_level,
    )


def _resolve_effective_settle_delay_ms(
    *,
    request: AdbCaptureRequest,
    after_capture_page: AfterCapturePageCallback | None,
    page_number: int,
) -> int:
    assert request.adb.swipe is not None
    base_delay_ms = request.adb.swipe.settle_delay_ms
    if base_delay_ms <= 0:
        return 0
    if after_capture_page is None:
        return base_delay_ms
    max_rank = request.pipeline.get("max_rank")
    if not isinstance(max_rank, int) or max_rank < 1000:
        return base_delay_ms
    if page_number <= 1:
        return base_delay_ms
    return min(base_delay_ms, 500)


def _ensure_capture_output_dir_is_empty(output_dir: Path) -> None:
    if not output_dir.exists():
        return

    if any(output_dir.iterdir()):
        raise MockImportError(
            "기존 capture 결과가 있는 output_dir에는 새 캡처를 쓰지 않습니다. "
            f"빈 디렉터리를 사용하거나 새 output_dir를 지정하세요: {output_dir}"
        )


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _run_adb_preflight_if_available(
    client: Any,
    device_serial: str | None,
) -> None:
    preflight = getattr(client, "preflight", None)
    if callable(preflight):
        preflight(device_serial=device_serial)


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


def _resolve_output_dir(
    request_dir: Path,
    cli_output_dir: str | None,
    request_output_dir: Any,
) -> Path:
    if cli_output_dir:
        return Path(cli_output_dir)
    if request_output_dir is None:
        return request_dir / "capture-output"
    if not isinstance(request_output_dir, str) or not request_output_dir.strip():
        raise MockImportError("adb.output_dir는 비어 있지 않은 문자열이어야 합니다.")

    output_dir = Path(request_output_dir)
    if output_dir.is_absolute():
        return output_dir
    return request_dir / output_dir


def _build_swipe_config(value: Any) -> AdbSwipeConfig | None:
    if value is None:
        return None
    swipe = _require_mapping(value, "adb.swipe")
    required_fields = ("start_x", "start_y", "end_x", "end_y")
    missing_fields = [field_name for field_name in required_fields if swipe.get(field_name) is None]
    if missing_fields:
        joined = ", ".join(missing_fields)
        raise MockImportError(f"adb.swipe에 필수 필드가 없습니다: {joined}")

    try:
        return AdbSwipeConfig(
            start_x=int(swipe["start_x"]),
            start_y=int(swipe["start_y"]),
            end_x=int(swipe["end_x"]),
            end_y=int(swipe["end_y"]),
            duration_ms=int(swipe.get("duration_ms", 300)),
            settle_delay_ms=int(swipe.get("settle_delay_ms", 800)),
        )
    except (TypeError, ValueError) as exc:
        raise MockImportError("adb.swipe 필드는 정수여야 합니다.") from exc


def _parse_boolean_option(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    raise MockImportError(f"{label}는 true 또는 false 여야 합니다.")


def _parse_positive_int_option(
    value: Any,
    label: str,
    *,
    minimum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MockImportError(f"{label}는 정수여야 합니다.") from exc

    if parsed < minimum:
        raise MockImportError(f"{label}는 {minimum} 이상이어야 합니다.")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ADB로 screenshot을 캡처해 capture manifest 디렉터리를 생성합니다.",
    )
    parser.add_argument(
        "request_path",
        help="ADB capture 요청 JSON 파일 경로",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        request = load_adb_capture_request(
            args.request_path,
            output_dir=args.output_dir,
            adb_command=args.adb_command,
            device_serial=args.device_serial,
        )
        result = capture_adb_screenshot(
            request,
            AdbClient(request.adb.adb_command),
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
                "ocr_provider": request.ocr["provider"],
                "device_serial": request.adb.device_serial,
                "requested_page_count": result.requested_page_count,
                "captured_page_count": len(result.image_paths),
                "stopped_reason": result.stopped_reason,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
