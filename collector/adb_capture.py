from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class AdbOptions:
    output_dir: Path
    device_serial: str | None
    page_prefix: str
    adb_command: str
    page_count: int
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


@dataclass(frozen=True)
class AdbCaptureResult:
    output_dir: Path
    manifest_path: Path
    image_paths: list[Path]


class AdbClient:
    def __init__(self, command: str):
        self.command = command

    def capture_screenshot(self, *, device_serial: str | None) -> bytes:
        args = self._build_args(device_serial)
        args.extend(["exec-out", "screencap", "-p"])

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise MockImportError(
                f"adb screenshot 실행에 실패했습니다: command={self.command!r}"
            ) from exc

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

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise MockImportError(
                f"adb swipe 실행에 실패했습니다: command={self.command!r}"
            ) from exc

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
            swipe=swipe,
        ),
    )


def capture_adb_screenshot(
    request: AdbCaptureRequest,
    client: AdbClient,
) -> AdbCaptureResult:
    _ensure_capture_output_dir_is_empty(request.adb.output_dir)
    request.adb.output_dir.mkdir(parents=True, exist_ok=True)

    image_paths: list[Path] = []
    for page_number in range(1, request.adb.page_count + 1):
        image_path = (
            request.adb.output_dir / f"{request.adb.page_prefix}-{page_number:03d}.png"
        )
        image_bytes = client.capture_screenshot(device_serial=request.adb.device_serial)
        image_path.write_bytes(image_bytes)
        image_paths.append(image_path)

        if page_number < request.adb.page_count:
            assert request.adb.swipe is not None  # guarded during request loading
            client.swipe(
                device_serial=request.adb.device_serial,
                swipe=request.adb.swipe,
            )
            if request.adb.swipe.settle_delay_ms > 0:
                time.sleep(request.adb.swipe.settle_delay_ms / 1000)

    manifest_path = request.adb.output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "season": request.season,
                "snapshot": request.snapshot,
                "ocr": request.ocr,
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
    )


def _ensure_capture_output_dir_is_empty(output_dir: Path) -> None:
    if not output_dir.exists():
        return

    if any(output_dir.iterdir()):
        raise MockImportError(
            "기존 capture 결과가 있는 output_dir에는 새 캡처를 쓰지 않습니다. "
            f"빈 디렉터리를 사용하거나 새 output_dir를 지정하세요: {output_dir}"
        )


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
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
