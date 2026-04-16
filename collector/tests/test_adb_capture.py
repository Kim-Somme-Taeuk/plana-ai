from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import collector.adb_capture as adb_capture
from collector.adb_capture import (
    AdbClient,
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
    assert request.adb.output_dir == tmp_path / "capture-output"
    assert request.adb.adb_command == "adb"


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
        def capture_screenshot(self, *, device_serial):
            assert device_serial is None
            return b"\x89PNG\r\n\x1a\nfake"

    result = capture_adb_screenshot(request, FakeAdbClient())

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["ocr"]["provider"] == "tesseract"
    assert manifest["pages"] == [{"image_path": "page-001.png"}]
    assert result.image_paths[0].read_bytes().startswith(b"\x89PNG")


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


def test_adb_client_fails_when_command_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adb_capture.shutil, "which", lambda command: None)

    client = AdbClient("adb")

    with pytest.raises(MockImportError) as exc_info:
        client.capture_screenshot(device_serial=None)

    assert "adb 명령을 찾을 수 없습니다" in str(exc_info.value)


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
