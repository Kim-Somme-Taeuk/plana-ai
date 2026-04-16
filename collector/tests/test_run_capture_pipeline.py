from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import collector.capture_import as capture_import
from collector.run_capture_pipeline import run_capture_pipeline


def test_run_capture_pipeline_captures_and_imports_with_tesseract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-happy-path-season",
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            assert device_serial is None
            return b"\x89PNG\r\n\x1a\nfake"

    class FakeApiClient:
        def __init__(self):
            self.calls: list[tuple[str, object]] = []

        def create_season(self, payload):
            self.calls.append(("create_season", payload))
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            self.calls.append(("create_snapshot", {"season_id": season_id, **payload}))
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            self.calls.append(("create_entry", {"snapshot_id": snapshot_id, **payload}))
            return {"id": len([call for call in self.calls if call[0] == "create_entry"])}

        def update_snapshot_status(self, snapshot_id, status):
            self.calls.append(("update_snapshot_status", {"snapshot_id": snapshot_id, "status": status}))
            return {
                "id": snapshot_id,
                "status": status,
                "total_rows_collected": 2,
            }

    def fake_run(args, capture_output, text, check):
        assert args == [
            "tesseract",
            str((tmp_path / "capture-output" / "page-001.png").resolve()),
            "stdout",
            "-l",
            "eng",
            "--psm",
            "6",
        ]
        assert capture_output is True
        assert text is True
        assert check is False
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="1\tPlana\t12345678\t0.99\n10\tArona\t12000000\t0.97\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    api_client = FakeApiClient()
    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        ocr_provider="tesseract",
        ocr_language="eng",
        ocr_psm=6,
        adb_client=FakeAdbClient(),
        api_client=api_client,
    )

    assert result.season_id == 101
    assert result.snapshot_id == 202
    assert result.status == "completed"
    assert result.total_rows_collected == 2
    assert result.ocr_provider == "tesseract"
    assert result.requested_page_count == 1
    assert result.captured_page_count == 1
    assert result.stopped_reason is None
    assert result.ignored_line_count == 0
    assert result.ocr_stop_hints == []
    assert result.ocr_stop_recommendation == {
        "should_stop": False,
        "level": None,
        "primary_reason": None,
        "reasons": [],
    }
    assert result.pipeline_stop_recommendation == {
        "should_stop": False,
        "level": None,
        "source": None,
        "primary_reason": None,
        "reasons": [],
    }
    assert result.stop_policy == {
        "min_pages_before_ocr_stop": 2,
        "soft_stop_repeat_threshold": 2,
    }
    assert result.manifest_path.exists()
    assert len(result.image_paths) == 1
    assert [call[0] for call in api_client.calls] == [
        "create_season",
        "create_snapshot",
        "create_entry",
        "create_entry",
        "update_snapshot_status",
    ]


def test_run_capture_pipeline_defaults_to_tesseract_without_explicit_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-default-provider-season",
        include_ocr=False,
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"\x89PNG\r\n\x1a\nfake"

    class FakeApiClient:
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {
                "id": snapshot_id,
                "status": status,
                "total_rows_collected": 1,
            }

    def fake_run(args, capture_output, text, check):
        assert args[:3] == [
            "tesseract",
            str((tmp_path / "capture-output" / "page-001.png").resolve()),
            "stdout",
        ]
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="1\tPlana\t12345678\t0.99\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=FakeApiClient(),
    )

    assert result.ocr_provider == "tesseract"


def test_run_capture_pipeline_preserves_explicit_sidecar_provider(
    tmp_path: Path,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-explicit-sidecar-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["ocr"] = {"provider": "sidecar"}
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"\x89PNG\r\n\x1a\nfake"

    class UnusedApiClient:
        def create_season(self, payload):
            raise AssertionError("sidecar 단계에서 실패해야 합니다")

    with pytest.raises(capture_import.MockImportError) as exc_info:
        run_capture_pipeline(
            request_path,
            base_url="http://localhost:8000",
            output_dir=str(tmp_path / "capture-output"),
            adb_client=FakeAdbClient(),
            api_client=UnusedApiClient(),
        )

    assert "ocr_text_path가 없고 기본 OCR sidecar(.txt)도 찾을 수 없습니다" in str(
        exc_info.value
    )


def test_run_capture_pipeline_propagates_import_error_after_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-import-failure-season",
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"\x89PNG\r\n\x1a\nfake"

    class FailingApiClient:
        def create_season(self, payload):
            raise RuntimeError("unexpected import failure")

    def fake_run(args, capture_output, text, check):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="1\tPlana\t12345678\t0.99\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        run_capture_pipeline(
            request_path,
            base_url="http://localhost:8000",
            output_dir=str(tmp_path / "capture-output"),
            adb_client=FakeAdbClient(),
            api_client=FailingApiClient(),
        )

    assert "unexpected import failure" in str(exc_info.value)
    assert (tmp_path / "capture-output" / "manifest.json").exists()


def test_run_capture_pipeline_returns_repeated_frame_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-repeated-frame-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["adb"]["page_count"] = 4
    request_payload["adb"]["swipe"] = {
        "start_x": 500,
        "start_y": 1600,
        "end_x": 500,
        "end_y": 600,
        "duration_ms": 200,
        "settle_delay_ms": 0,
    }
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeAdbClient:
        def __init__(self):
            self.capture_index = 0

        def capture_screenshot(self, *, device_serial):
            self.capture_index += 1
            return [b"PNG-1", b"PNG-2", b"PNG-1", b"PNG-1"][self.capture_index - 1]

        def swipe(self, *, device_serial, swipe):
            return None

    class FakeApiClient:
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {
                "id": snapshot_id,
                "status": status,
                "total_rows_collected": 1,
            }

    def fake_run(args, capture_output, text, check):
        image_path = Path(args[1]).name
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                "1\tPlana\t12345678\t0.99\n"
                if image_path == "page-001.png"
                else "2\tArona\t12000000\t0.98\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=FakeApiClient(),
    )

    assert result.requested_page_count == 4
    assert result.captured_page_count == 2
    assert result.stopped_reason == "repeated_frame"
    assert result.ocr_stop_hints == [{"reason": "sparse_last_page", "page_index": 2, "entry_count": 1}]
    assert result.ocr_stop_recommendation == {
        "should_stop": True,
        "level": "soft",
        "primary_reason": "sparse_last_page",
        "reasons": ["sparse_last_page"],
    }
    assert result.pipeline_stop_recommendation == {
        "should_stop": True,
        "level": "hard",
        "source": "capture",
        "primary_reason": "repeated_frame",
        "reasons": ["repeated_frame"],
    }
    assert result.import_skipped is False


def test_run_capture_pipeline_tracks_ignored_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-ignored-lines-season",
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"\x89PNG\r\n\x1a\nfake"

    class FakeApiClient:
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {
                "id": snapshot_id,
                "status": status,
                "total_rows_collected": 1,
            }

    def fake_run(args, capture_output, text, check):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="RANK PLAYER SCORE\n1\tPlana\t12345678\t0.99\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=FakeApiClient(),
    )

    assert result.ignored_line_count == 1
    assert result.ignored_line_reasons == [{"reason": "non_entry_line", "count": 1}]
    assert result.ocr_stop_hints == [{"reason": "noisy_last_page", "page_index": 1, "ignored_line_count": 1, "entry_count": 1}]
    assert result.ocr_stop_recommendation == {
        "should_stop": True,
        "level": "hard",
        "primary_reason": "noisy_last_page",
        "reasons": ["noisy_last_page"],
    }
    assert result.pipeline_stop_recommendation == {
        "should_stop": True,
        "level": "hard",
        "source": "ocr",
        "primary_reason": "noisy_last_page",
        "reasons": ["noisy_last_page"],
    }
    assert result.page_summaries == [
        {
            "page_index": 1,
            "image_path": capture_import._build_entry_image_path(
                (tmp_path / "capture-output" / "page-001.png").resolve()
            ),
            "entry_count": 1,
            "ignored_line_count": 1,
            "ignored_line_reasons": [{"reason": "non_entry_line", "count": 1}],
            "first_rank": 1,
            "last_rank": 1,
            "overlap_with_previous_count": 0,
            "overlap_with_previous_ratio": 0.0,
            "overlap_with_previous_ranks": [],
        }
    ]


def test_run_capture_pipeline_skips_import_when_stop_recommendation_is_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-stop-recommendation-season",
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["pipeline"] = {"stop_on_recommendation": True}
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"\x89PNG\r\n\x1a\nfake"

    class UnusedApiClient:
        def create_season(self, payload):
            raise AssertionError("import는 건너뛰어야 합니다")

    def fake_run(args, capture_output, text, check):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="RANK PLAYER SCORE\n1\tPlana\t12345678\t0.99\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=UnusedApiClient(),
    )

    assert result.import_skipped is True
    assert result.skip_reason == "noisy_last_page"
    assert result.season_id is None
    assert result.snapshot_id is None
    assert result.entry_ids == []
    assert result.status is None
    assert result.total_rows_collected is None


def test_run_capture_pipeline_cli_flag_skips_import_on_recommendation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-cli-stop-recommendation-season",
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"\x89PNG\r\n\x1a\nfake"

    class UnusedApiClient:
        def create_season(self, payload):
            raise AssertionError("import는 건너뛰어야 합니다")

    def fake_run(args, capture_output, text, check):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="RANK PLAYER SCORE\n1\tPlana\t12345678\t0.99\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=UnusedApiClient(),
        stop_on_recommendation=True,
    )

    assert result.import_skipped is True
    assert result.skip_reason == "noisy_last_page"


def test_run_capture_pipeline_does_not_skip_import_for_soft_recommendation_in_hard_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-hard-mode-soft-recommendation-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["pipeline"] = {"stop_on_recommendation": True}
    request_payload["adb"]["page_count"] = 2
    request_payload["adb"]["swipe"] = {
        "start_x": 500,
        "start_y": 1600,
        "end_x": 500,
        "end_y": 600,
        "duration_ms": 200,
        "settle_delay_ms": 0,
    }
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeAdbClient:
        def __init__(self):
            self.capture_index = 0

        def capture_screenshot(self, *, device_serial):
            self.capture_index += 1
            return [b"PNG-1", b"PNG-2"][self.capture_index - 1]

        def swipe(self, *, device_serial, swipe):
            return None

    class FakeApiClient:
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {
                "id": snapshot_id,
                "status": status,
                "total_rows_collected": 2,
            }

    def fake_run(args, capture_output, text, check):
        image_path = Path(args[1]).name
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                "1\tPlana\t12345678\t0.99\n"
                if image_path == "page-001.png"
                else "2\tArona\t12000000\t0.98\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=FakeApiClient(),
    )

    assert result.ocr_stop_recommendation == {
        "should_stop": True,
        "level": "soft",
        "primary_reason": "sparse_last_page",
        "reasons": ["sparse_last_page"],
    }
    assert result.import_skipped is False


def test_run_capture_pipeline_skips_import_for_soft_recommendation_in_any_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-any-mode-soft-recommendation-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["pipeline"] = {"stop_on_recommendation": "any"}
    request_payload["adb"]["page_count"] = 2
    request_payload["adb"]["swipe"] = {
        "start_x": 500,
        "start_y": 1600,
        "end_x": 500,
        "end_y": 600,
        "duration_ms": 200,
        "settle_delay_ms": 0,
    }
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeAdbClient:
        def __init__(self):
            self.capture_index = 0

        def capture_screenshot(self, *, device_serial):
            self.capture_index += 1
            return [b"PNG-1", b"PNG-2"][self.capture_index - 1]

        def swipe(self, *, device_serial, swipe):
            return None

    class UnusedApiClient:
        def create_season(self, payload):
            raise AssertionError("import는 건너뛰어야 합니다")

    def fake_run(args, capture_output, text, check):
        image_path = Path(args[1]).name
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                "1\tPlana\t12345678\t0.99\n"
                if image_path == "page-001.png"
                else "2\tArona\t12000000\t0.98\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=UnusedApiClient(),
    )

    assert result.import_skipped is True
    assert result.skip_reason == "sparse_last_page"


def test_run_capture_pipeline_stops_capture_early_for_hard_recommendation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-stop-capture-hard-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["pipeline"] = {"stop_capture_on_recommendation": True}
    request_payload["adb"]["page_count"] = 3
    request_payload["adb"]["swipe"] = {
        "start_x": 500,
        "start_y": 1600,
        "end_x": 500,
        "end_y": 600,
        "duration_ms": 200,
        "settle_delay_ms": 0,
    }
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeAdbClient:
        def __init__(self):
            self.capture_index = 0
            self.swipes: list[object] = []

        def capture_screenshot(self, *, device_serial):
            self.capture_index += 1
            return [b"PNG-1", b"PNG-2", b"PNG-3"][self.capture_index - 1]

        def swipe(self, *, device_serial, swipe):
            self.swipes.append(swipe)

    class FakeApiClient:
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 2}

    def fake_run(args, capture_output, text, check):
        image_name = Path(args[1]).name
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                "1\tPlana\t12345678\t0.99\n10\tArona\t12000000\t0.98\n"
                if image_name == "page-001.png"
                else "header\n2\tSensei\t11000000\t0.98\nfooter\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=FakeApiClient(),
    )

    assert result.captured_page_count == 2
    assert result.stopped_reason == "noisy_last_page"
    assert result.pipeline_stop_recommendation == {
        "should_stop": True,
        "level": "hard",
        "source": "ocr",
        "primary_reason": "noisy_last_page",
        "reasons": ["noisy_last_page"],
    }
    assert result.import_skipped is False


def test_run_capture_pipeline_stops_capture_early_for_soft_recommendation_in_any_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-stop-capture-any-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["pipeline"] = {"stop_capture_on_recommendation": "any"}
    request_payload["adb"]["page_count"] = 4
    request_payload["adb"]["swipe"] = {
        "start_x": 500,
        "start_y": 1600,
        "end_x": 500,
        "end_y": 600,
        "duration_ms": 200,
        "settle_delay_ms": 0,
    }
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeAdbClient:
        def __init__(self):
            self.capture_index = 0
            self.swipes: list[object] = []

        def capture_screenshot(self, *, device_serial):
            self.capture_index += 1
            return [b"PNG-1", b"PNG-2", b"PNG-3", b"PNG-4"][self.capture_index - 1]

        def swipe(self, *, device_serial, swipe):
            self.swipes.append(swipe)

    class FakeApiClient:
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 4}

    def fake_run(args, capture_output, text, check):
        image_name = Path(args[1]).name
        stdout_by_image = {
            "page-001.png": "1\tPlana\t12345678\t0.99\n10\tArona\t12000000\t0.98\n",
            "page-002.png": "2\tSensei\t11000000\t0.98\n",
            "page-003.png": "3\tMari\t10900000\t0.98\n",
            "page-004.png": "4\tNoa\t10800000\t0.98\n",
        }
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=stdout_by_image[image_name],
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=FakeApiClient(),
    )

    assert result.captured_page_count == 3
    assert result.stopped_reason == "sparse_last_page"
    assert result.pipeline_stop_recommendation == {
        "should_stop": True,
        "level": "soft",
        "source": "ocr",
        "primary_reason": "sparse_last_page",
        "reasons": ["sparse_last_page"],
    }
    assert result.import_skipped is False


def test_run_capture_pipeline_does_not_stop_capture_before_minimum_ocr_stop_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-min-pages-guard-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["pipeline"] = {"stop_capture_on_recommendation": True}
    request_payload["adb"]["page_count"] = 3
    request_payload["adb"]["swipe"] = {
        "start_x": 500,
        "start_y": 1600,
        "end_x": 500,
        "end_y": 600,
        "duration_ms": 200,
        "settle_delay_ms": 0,
    }
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeAdbClient:
        def __init__(self):
            self.capture_index = 0

        def capture_screenshot(self, *, device_serial):
            self.capture_index += 1
            return [b"PNG-1", b"PNG-2", b"PNG-3"][self.capture_index - 1]

        def swipe(self, *, device_serial, swipe):
            return None

    class FakeApiClient:
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 3}

    def fake_run(args, capture_output, text, check):
        image_name = Path(args[1]).name
        stdout_by_image = {
            "page-001.png": "header\n1\tPlana\t12345678\t0.99\nfooter\n",
            "page-002.png": "2\tSensei\t11000000\t0.98\n3\tMari\t10900000\t0.98\n",
            "page-003.png": "4\tNoa\t10800000\t0.98\n5\tYuzu\t10700000\t0.97\n",
        }
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=stdout_by_image[image_name],
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=FakeApiClient(),
    )

    assert result.captured_page_count == 3
    assert result.stopped_reason is None
    assert result.import_skipped is False


def test_run_capture_pipeline_does_not_stop_capture_early_for_single_soft_recommendation_in_any_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-single-soft-stop-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["pipeline"] = {"stop_capture_on_recommendation": "any"}
    request_payload["adb"]["page_count"] = 3
    request_payload["adb"]["swipe"] = {
        "start_x": 500,
        "start_y": 1600,
        "end_x": 500,
        "end_y": 600,
        "duration_ms": 200,
        "settle_delay_ms": 0,
    }
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeAdbClient:
        def __init__(self):
            self.capture_index = 0

        def capture_screenshot(self, *, device_serial):
            self.capture_index += 1
            return [b"PNG-1", b"PNG-2", b"PNG-3"][self.capture_index - 1]

        def swipe(self, *, device_serial, swipe):
            return None

    class FakeApiClient:
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 4}

    def fake_run(args, capture_output, text, check):
        image_name = Path(args[1]).name
        stdout_by_image = {
            "page-001.png": "1\tPlana\t12345678\t0.99\n10\tArona\t12000000\t0.98\n",
            "page-002.png": "2\tSensei\t11000000\t0.98\n",
            "page-003.png": "3\tMari\t10900000\t0.98\n4\tNoa\t10800000\t0.98\n",
        }
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=stdout_by_image[image_name],
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=FakeApiClient(),
    )

    assert result.captured_page_count == 3
    assert result.stopped_reason is None
    assert result.import_skipped is False


def test_run_capture_pipeline_supports_custom_soft_stop_repeat_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-soft-threshold-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["pipeline"] = {
        "stop_capture_on_recommendation": "any",
        "soft_stop_repeat_threshold": 3,
    }
    request_payload["adb"]["page_count"] = 5
    request_payload["adb"]["swipe"] = {
        "start_x": 500,
        "start_y": 1600,
        "end_x": 500,
        "end_y": 600,
        "duration_ms": 200,
        "settle_delay_ms": 0,
    }
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeAdbClient:
        def __init__(self):
            self.capture_index = 0

        def capture_screenshot(self, *, device_serial):
            self.capture_index += 1
            return [b"PNG-1", b"PNG-2", b"PNG-3", b"PNG-4", b"PNG-5"][
                self.capture_index - 1
            ]

        def swipe(self, *, device_serial, swipe):
            return None

    class FakeApiClient:
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 4}

    def fake_run(args, capture_output, text, check):
        image_name = Path(args[1]).name
        stdout_by_image = {
            "page-001.png": "1\tPlana\t12345678\t0.99\n10\tArona\t12000000\t0.98\n",
            "page-002.png": "2\tSensei\t11000000\t0.98\n",
            "page-003.png": "3\tMari\t10900000\t0.98\n",
            "page-004.png": "4\tNoa\t10800000\t0.98\n",
            "page-005.png": "5\tYuzu\t10700000\t0.97\n",
        }
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=stdout_by_image[image_name],
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=FakeApiClient(),
    )

    assert result.captured_page_count == 4
    assert result.stopped_reason == "sparse_last_page"
    assert result.stop_policy == {
        "min_pages_before_ocr_stop": 2,
        "soft_stop_repeat_threshold": 3,
    }


def _write_request(
    base_dir: Path,
    *,
    season_label: str,
    include_ocr: bool = True,
) -> Path:
    request_path = base_dir / "pipeline-request.json"
    payload = {
        "season": {
            "event_type": "total_assault",
            "server": "kr",
            "boss_name": "Binah",
            "terrain": "outdoor",
            "season_label": season_label,
        },
        "snapshot": {
            "captured_at": "2026-04-16T12:00:00Z",
        },
        "adb": {
            "page_count": 1,
        },
    }
    if include_ocr:
        payload["ocr"] = {
            "provider": "tesseract",
            "language": "eng",
            "psm": 6,
        }
    request_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request_path
