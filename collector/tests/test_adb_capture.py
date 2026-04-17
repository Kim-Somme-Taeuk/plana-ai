from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

import collector.adb_capture as adb_capture
from collector.adb_capture import (
    AdbCaptureStopDecision,
    AdbClient,
    build_pipeline_stop_policy,
    capture_adb_screenshot,
    load_adb_capture_request,
)
from collector.mock_import import MockImportError


def test_load_adb_capture_request_reads_defaults(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path)

    request = load_adb_capture_request(request_path)

    assert request.snapshot["note"] == "adb screenshot capture"
    assert request.ocr["provider"] == "sidecar"
    assert request.adb.page_prefix == "page"
    assert request.adb.page_count == 1
    assert request.adb.stop_on_duplicate_frame is True
    assert request.adb.swipe is None
    assert request.adb.output_dir == tmp_path / "capture-output"
    assert request.adb.adb_command == "adb"
    assert request.ocr_provider_explicit is False


def test_load_adb_capture_request_marks_explicit_ocr_provider(tmp_path: Path) -> None:
    request_path = _write_request(
        tmp_path,
        ocr={"provider": "sidecar"},
    )

    request = load_adb_capture_request(request_path)

    assert request.ocr["provider"] == "sidecar"
    assert request.ocr_provider_explicit is True


def test_build_pipeline_stop_policy_reads_defaults() -> None:
    policy = build_pipeline_stop_policy({})

    assert policy.min_pages_before_ocr_stop == 2
    assert policy.soft_stop_repeat_threshold == 2


def test_build_pipeline_stop_policy_validates_positive_thresholds() -> None:
    with pytest.raises(MockImportError) as exc_info:
        build_pipeline_stop_policy({"soft_stop_repeat_threshold": 1})

    assert "pipeline.soft_stop_repeat_threshold는 2 이상이어야 합니다." in str(
        exc_info.value
    )


def test_load_adb_capture_request_resolves_relative_output_dir_from_request_file(
    tmp_path: Path,
) -> None:
    request_path = _write_request(
        tmp_path,
        adb={"output_dir": "captures/run-001"},
    )

    request = load_adb_capture_request(request_path)

    assert request.adb.output_dir == tmp_path / "captures/run-001"


def test_capture_adb_screenshot_writes_manifest_and_image(tmp_path: Path) -> None:
    request_path = _write_request(
        tmp_path,
        ocr={"provider": "tesseract", "language": "eng", "psm": 6},
    )
    request = load_adb_capture_request(
        request_path,
        output_dir=str(tmp_path / "captured"),
    )

    class FakeAdbClient:
        def __init__(self):
            self.preflight_calls: list[str | None] = []

        def preflight(self, *, device_serial):
            self.preflight_calls.append(device_serial)

        def capture_screenshot(self, *, device_serial):
            assert device_serial is None
            return b"\x89PNG\r\n\x1a\nfake"

    client = FakeAdbClient()
    result = capture_adb_screenshot(request, client)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["ocr"]["provider"] == "tesseract"
    assert manifest["pages"] == [{"image_path": "page-001.png"}]
    assert manifest["snapshot"]["captured_at"] != "2026-04-16T12:00:00Z"
    parsed_captured_at = datetime.fromisoformat(
        manifest["snapshot"]["captured_at"].replace("Z", "+00:00")
    )
    assert parsed_captured_at.tzinfo is not None
    assert result.image_paths[0].read_bytes().startswith(b"\x89PNG")
    assert client.preflight_calls == [None]


def test_capture_adb_screenshot_supports_multi_page_scroll(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        adb={
            "page_count": 3,
            "swipe": {
                "start_x": 500,
                "start_y": 1600,
                "end_x": 500,
                "end_y": 600,
                "duration_ms": 200,
                "settle_delay_ms": 50,
            },
        },
    )
    request = load_adb_capture_request(request_path)

    class FakeAdbClient:
        def __init__(self):
            self.capture_index = 0
            self.swipes: list[tuple[str | None, object]] = []

        def capture_screenshot(self, *, device_serial):
            self.capture_index += 1
            return f"PNG-{self.capture_index}".encode("utf-8")

        def swipe(self, *, device_serial, swipe):
            self.swipes.append((device_serial, swipe))

    sleep_calls: list[float] = []
    monkeypatch.setattr(adb_capture.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    client = FakeAdbClient()
    result = capture_adb_screenshot(request, client)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert [page["image_path"] for page in manifest["pages"]] == [
        "page-001.png",
        "page-002.png",
        "page-003.png",
    ]
    assert [path.read_bytes() for path in result.image_paths] == [
        b"PNG-1",
        b"PNG-2",
        b"PNG-3",
    ]
    assert len(client.swipes) == 2
    assert sleep_calls == [0.05, 0.05]
    assert result.requested_page_count == 3
    assert result.stopped_reason is None
    assert result.stopped_source is None
    assert result.stopped_level is None


def test_capture_adb_screenshot_stops_on_duplicate_frame(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        adb={
            "page_count": 3,
            "swipe": {
                "start_x": 500,
                "start_y": 1600,
                "end_x": 500,
                "end_y": 600,
                "duration_ms": 200,
                "settle_delay_ms": 50,
            },
        },
    )
    request = load_adb_capture_request(request_path)

    class FakeAdbClient:
        def __init__(self):
            self.capture_index = 0
            self.swipes: list[tuple[str | None, object]] = []

        def capture_screenshot(self, *, device_serial):
            self.capture_index += 1
            return [b"PNG-1", b"PNG-1", b"PNG-1"][self.capture_index - 1]

        def swipe(self, *, device_serial, swipe):
            self.swipes.append((device_serial, swipe))

    sleep_calls: list[float] = []
    monkeypatch.setattr(adb_capture.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    client = FakeAdbClient()
    result = capture_adb_screenshot(request, client)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert [page["image_path"] for page in manifest["pages"]] == ["page-001.png"]
    assert manifest["capture"] == {
        "requested_page_count": 3,
        "captured_page_count": 1,
        "stopped_reason": "duplicate_frame",
        "stopped_source": "capture",
        "stopped_level": "hard",
    }
    assert [path.read_bytes() for path in result.image_paths] == [b"PNG-1"]
    assert len(client.swipes) == 1
    assert sleep_calls == [0.05]
    assert result.stopped_reason == "duplicate_frame"
    assert result.stopped_source == "capture"
    assert result.stopped_level == "hard"


def test_capture_adb_screenshot_can_keep_duplicate_frames_when_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        adb={
            "page_count": 2,
            "stop_on_duplicate_frame": False,
            "swipe": {
                "start_x": 500,
                "start_y": 1600,
                "end_x": 500,
                "end_y": 600,
                "duration_ms": 200,
                "settle_delay_ms": 50,
            },
        },
    )
    request = load_adb_capture_request(request_path)

    class FakeAdbClient:
        def __init__(self):
            self.swipes: list[tuple[str | None, object]] = []

        def capture_screenshot(self, *, device_serial):
            return b"PNG-same"

        def swipe(self, *, device_serial, swipe):
            self.swipes.append((device_serial, swipe))

    monkeypatch.setattr(adb_capture.time, "sleep", lambda seconds: None)

    client = FakeAdbClient()
    result = capture_adb_screenshot(request, client)

    assert len(result.image_paths) == 2
    assert result.stopped_reason is None
    assert result.stopped_source is None
    assert result.stopped_level is None
    assert len(client.swipes) == 1


def test_capture_adb_screenshot_stops_on_repeated_non_consecutive_frame(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        adb={
            "page_count": 4,
            "swipe": {
                "start_x": 500,
                "start_y": 1600,
                "end_x": 500,
                "end_y": 600,
                "duration_ms": 200,
                "settle_delay_ms": 50,
            },
        },
    )
    request = load_adb_capture_request(request_path)

    class FakeAdbClient:
        def __init__(self):
            self.capture_index = 0
            self.swipes: list[tuple[str | None, object]] = []

        def capture_screenshot(self, *, device_serial):
            self.capture_index += 1
            return [b"PNG-1", b"PNG-2", b"PNG-1", b"PNG-1"][self.capture_index - 1]

        def swipe(self, *, device_serial, swipe):
            self.swipes.append((device_serial, swipe))

    monkeypatch.setattr(adb_capture.time, "sleep", lambda seconds: None)

    client = FakeAdbClient()
    result = capture_adb_screenshot(request, client)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert [page["image_path"] for page in manifest["pages"]] == [
        "page-001.png",
        "page-002.png",
    ]
    assert manifest["capture"] == {
        "requested_page_count": 4,
        "captured_page_count": 2,
        "stopped_reason": "repeated_frame",
        "stopped_source": "capture",
        "stopped_level": "hard",
    }
    assert result.stopped_reason == "repeated_frame"
    assert result.stopped_source == "capture"
    assert result.stopped_level == "hard"
    assert len(client.swipes) == 2


def test_capture_adb_screenshot_can_stop_from_after_capture_page_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        adb={
            "page_count": 3,
            "swipe": {
                "start_x": 500,
                "start_y": 1600,
                "end_x": 500,
                "end_y": 600,
                "duration_ms": 200,
                "settle_delay_ms": 50,
            },
        },
    )
    request = load_adb_capture_request(request_path)

    class FakeAdbClient:
        def __init__(self):
            self.capture_index = 0
            self.swipes: list[tuple[str | None, object]] = []

        def capture_screenshot(self, *, device_serial):
            self.capture_index += 1
            return [b"PNG-1", b"PNG-2", b"PNG-3"][self.capture_index - 1]

        def swipe(self, *, device_serial, swipe):
            self.swipes.append((device_serial, swipe))

    monkeypatch.setattr(adb_capture.time, "sleep", lambda seconds: None)

    callback_calls: list[list[str]] = []

    def after_capture_page(image_paths: list[Path]) -> AdbCaptureStopDecision:
        callback_calls.append([path.name for path in image_paths])
        if len(image_paths) == 2:
            return AdbCaptureStopDecision(
                should_continue=False,
                reason="sparse_last_page",
                source="ocr",
                level="soft",
            )
        return AdbCaptureStopDecision(should_continue=True)

    client = FakeAdbClient()
    result = capture_adb_screenshot(
        request,
        client,
        after_capture_page=after_capture_page,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert callback_calls == [["page-001.png"], ["page-001.png", "page-002.png"]]
    assert [page["image_path"] for page in manifest["pages"]] == [
        "page-001.png",
        "page-002.png",
    ]
    assert manifest["capture"] == {
        "requested_page_count": 3,
        "captured_page_count": 2,
        "stopped_reason": "sparse_last_page",
        "stopped_source": "ocr",
        "stopped_level": "soft",
    }
    assert result.stopped_reason == "sparse_last_page"
    assert result.stopped_source == "ocr"
    assert result.stopped_level == "soft"
    assert len(client.swipes) == 1


def test_capture_adb_screenshot_rejects_non_empty_output_dir(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path)
    output_dir = tmp_path / "captured"
    output_dir.mkdir()
    (output_dir / "manifest.json").write_text("{}", encoding="utf-8")
    request = load_adb_capture_request(
        request_path,
        output_dir=str(output_dir),
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"PNG"

    with pytest.raises(MockImportError) as exc_info:
        capture_adb_screenshot(request, FakeAdbClient())

    assert "기존 capture 결과가 있는 output_dir" in str(exc_info.value)


def test_adb_client_uses_serial_and_screencap_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_args: list[str] = []

    def fake_run(args, capture_output, check):
        captured_args.extend(args)
        assert capture_output is True
        assert check is False
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"PNG", stderr=b"")

    monkeypatch.setattr(adb_capture.shutil, "which", lambda command: "/usr/bin/adb")
    monkeypatch.setattr(adb_capture.subprocess, "run", fake_run)

    client = AdbClient("adb")
    screenshot = client.capture_screenshot(device_serial="emulator-5554")

    assert screenshot == b"PNG"
    assert captured_args == [
        "adb",
        "-s",
        "emulator-5554",
        "exec-out",
        "screencap",
        "-p",
    ]


def test_adb_client_uses_swipe_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_args: list[str] = []

    def fake_run(args, capture_output, check):
        captured_args.extend(args)
        assert capture_output is True
        assert check is False
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(adb_capture.shutil, "which", lambda command: "/usr/bin/adb")
    monkeypatch.setattr(adb_capture.subprocess, "run", fake_run)

    client = AdbClient("adb")
    client.swipe(
        device_serial="device-01",
        swipe=adb_capture.AdbSwipeConfig(
            start_x=500,
            start_y=1600,
            end_x=500,
            end_y=600,
            duration_ms=200,
            settle_delay_ms=800,
        ),
    )

    assert captured_args == [
        "adb",
        "-s",
        "device-01",
        "shell",
        "input",
        "swipe",
        "500",
        "1600",
        "500",
        "600",
        "200",
    ]


def test_adb_client_preflight_accepts_single_connected_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(args, capture_output, check):
        assert args == ["adb", "devices"]
        assert capture_output is True
        assert check is False
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=b"List of devices attached\nemulator-5554\tdevice\n",
            stderr=b"",
        )

    monkeypatch.setattr(adb_capture.shutil, "which", lambda command: "/usr/bin/adb")
    monkeypatch.setattr(adb_capture.subprocess, "run", fake_run)

    client = AdbClient("adb")
    client.preflight(device_serial=None)


def test_adb_client_preflight_requires_serial_for_multiple_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(args, capture_output, check):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                b"List of devices attached\n"
                b"emulator-5554\tdevice\n"
                b"device-01\tdevice\n"
            ),
            stderr=b"",
        )

    monkeypatch.setattr(adb_capture.shutil, "which", lambda command: "/usr/bin/adb")
    monkeypatch.setattr(adb_capture.subprocess, "run", fake_run)

    client = AdbClient("adb")

    with pytest.raises(MockImportError) as exc_info:
        client.preflight(device_serial=None)

    assert "여러 adb device가 연결되어 있어 device_serial 지정이 필요합니다" in str(
        exc_info.value
    )
    assert "emulator-5554(device)" in str(exc_info.value)


def test_adb_client_preflight_rejects_missing_requested_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(args, capture_output, check):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=b"List of devices attached\nemulator-5554\tdevice\n",
            stderr=b"",
        )

    monkeypatch.setattr(adb_capture.shutil, "which", lambda command: "/usr/bin/adb")
    monkeypatch.setattr(adb_capture.subprocess, "run", fake_run)

    client = AdbClient("adb")

    with pytest.raises(MockImportError) as exc_info:
        client.preflight(device_serial="device-01")

    assert "지정한 adb device를 찾지 못했습니다" in str(exc_info.value)
    assert "device_serial=device-01" in str(exc_info.value)


def test_adb_client_preflight_rejects_unavailable_device_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(args, capture_output, check):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=b"List of devices attached\ndevice-01\tunauthorized\n",
            stderr=b"",
        )

    monkeypatch.setattr(adb_capture.shutil, "which", lambda command: "/usr/bin/adb")
    monkeypatch.setattr(adb_capture.subprocess, "run", fake_run)

    client = AdbClient("adb")

    with pytest.raises(MockImportError) as exc_info:
        client.preflight(device_serial="device-01")

    assert "지정한 adb device를 사용할 수 없습니다" in str(exc_info.value)
    assert "state=unauthorized" in str(exc_info.value)


def test_adb_client_fails_when_command_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adb_capture.shutil, "which", lambda command: None)

    client = AdbClient("adb")

    with pytest.raises(MockImportError) as exc_info:
        client.capture_screenshot(device_serial=None)

    assert "adb 명령을 찾을 수 없습니다" in str(exc_info.value)


def test_load_adb_capture_request_requires_swipe_for_multiple_pages(
    tmp_path: Path,
) -> None:
    request_path = _write_request(
        tmp_path,
        adb={"page_count": 2},
    )

    with pytest.raises(MockImportError) as exc_info:
        load_adb_capture_request(request_path)

    assert "adb.page_count가 2 이상이면 adb.swipe 설정이 필요합니다" in str(exc_info.value)


def _write_request(
    base_dir: Path,
    *,
    ocr: dict[str, object] | None = None,
    adb: dict[str, object] | None = None,
) -> Path:
    request_path = base_dir / "adb-request.json"
    request_path.write_text(
        json.dumps(
            {
                "season": {
                    "event_type": "total_assault",
                    "server": "kr",
                    "boss_name": "Binah",
                    "terrain": "outdoor",
                    "season_label": "adb-capture-test-season",
                },
                "snapshot": {
                    "captured_at": "2026-04-16T12:00:00Z",
                },
                "ocr": ocr or {},
                "adb": adb or {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return request_path
