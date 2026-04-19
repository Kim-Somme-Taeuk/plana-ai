from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import collector.capture_import as capture_import
import collector.run_capture_pipeline as capture_pipeline
from collector.adb_capture import PipelineStopPolicy
from collector.mock_import import ApiError
from collector.run_capture_pipeline import run_capture_pipeline


class SnapshotAwareApiClientMixin:
    def list_seasons(self):
        return []

    def list_snapshots(self, season_id):
        return []

    def list_entries(self, snapshot_id):
        return []


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

    class FakeApiClient(SnapshotAwareApiClientMixin):
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

    def fake_run(args, capture_output, text, check, **kwargs):
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
    assert result.resumed_from_output is False
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
        "max_rank": None,
    }
    assert result.highest_rank_collected == 10
    assert result.reached_max_rank is False
    assert result.manifest_path.exists() is False
    assert len(result.image_paths) == 1
    pipeline_result = json.loads(
        (tmp_path / "capture-output" / "pipeline-result.json").read_text(
            encoding="utf-8"
        )
    )
    assert pipeline_result["status"] == "completed"
    assert pipeline_result["entry_count"] == 2
    assert pipeline_result["highest_rank_collected"] == 10
    assert pipeline_result["reached_max_rank"] is False
    assert pipeline_result["recovery"]["rerun_pipeline_command"].endswith(
        "--force-recapture --output-dir "
        f"{tmp_path / 'capture-output'} {request_path}"
    )
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

    class FakeApiClient(SnapshotAwareApiClientMixin):
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

    def fake_run(args, capture_output, text, check, **kwargs):
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


def test_run_capture_pipeline_resumes_existing_capture_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-resume-season",
    )
    output_dir = tmp_path / "capture-output"
    output_dir.mkdir()
    (output_dir / "page-001.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (output_dir / "page-001.txt").write_text(
        "1\tCached OCR\t12345678\t0.99\n",
        encoding="utf-8",
    )
    (output_dir / "pipeline-error.json").write_text("{}", encoding="utf-8")
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "season": {
                    "event_type": "total_assault",
                    "server": "kr",
                    "boss_name": "Binah",
                    "terrain": "outdoor",
                    "season_label": "pipeline-resume-season",
                },
                "snapshot": {
                    "captured_at": "2026-04-16T12:00:00Z",
                    "note": "adb screenshot capture",
                },
                "ocr": {
                    "provider": "tesseract",
                    "language": "eng",
                    "psm": 6,
                },
                "capture": {
                    "requested_page_count": 3,
                    "captured_page_count": 1,
                    "stopped_reason": "repeated_frame",
                    "stopped_source": "capture",
                    "stopped_level": "hard",
                },
                "pages": [
                    {
                        "image_path": "page-001.png",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class UnusedAdbClient:
        def capture_screenshot(self, *, device_serial):
            raise AssertionError("기존 capture output을 resume해야 합니다")

    class FakeApiClient(SnapshotAwareApiClientMixin):
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

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(
        capture_import.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("resume에서는 cached sidecar를 재사용해야 합니다")),
    )

    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(output_dir),
        adb_client=UnusedAdbClient(),
        api_client=FakeApiClient(),
    )

    assert result.resumed_from_output is True
    assert result.requested_page_count == 3
    assert result.captured_page_count == 1
    assert result.stopped_reason == "repeated_frame"
    assert result.entry_ids == [1]
    pipeline_result = json.loads(
        (output_dir / "pipeline-result.json").read_text(encoding="utf-8")
    )
    assert pipeline_result["resumed_from_output"] is True
    assert not (output_dir / "pipeline-error.json").exists()


def test_run_capture_pipeline_rejects_nonempty_output_without_manifest(tmp_path: Path) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-invalid-resume-season",
        include_ocr=False,
    )
    output_dir = tmp_path / "capture-output"
    output_dir.mkdir()
    (output_dir / "page-001.png").write_bytes(b"fake")

    class UnusedAdbClient:
        def capture_screenshot(self, *, device_serial):
            raise AssertionError("resume 실패 시 캡처로 진행하면 안 됩니다")

    with pytest.raises(capture_import.MockImportError) as exc_info:
        run_capture_pipeline(
            request_path,
            base_url="http://localhost:8000",
            output_dir=str(output_dir),
            adb_client=UnusedAdbClient(),
            api_client=SnapshotAwareApiClientMixin(),
        )

    assert "resume 가능한 manifest.json이 없습니다" in str(exc_info.value)
    pipeline_error = json.loads(
        (output_dir / "pipeline-error.json").read_text(encoding="utf-8")
    )
    assert pipeline_error["stage"] == "capture"
    assert pipeline_error["error_type"] == "MockImportError"


def test_run_capture_pipeline_resume_only_requires_existing_manifest(tmp_path: Path) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-resume-only-season",
        include_ocr=False,
    )

    class UnusedAdbClient:
        def capture_screenshot(self, *, device_serial):
            raise AssertionError("resume-only에서는 새 캡처를 하면 안 됩니다")

    with pytest.raises(capture_import.MockImportError) as exc_info:
        run_capture_pipeline(
            request_path,
            base_url="http://localhost:8000",
            output_dir=str(tmp_path / "capture-output"),
            adb_client=UnusedAdbClient(),
            api_client=SnapshotAwareApiClientMixin(),
            resume_only=True,
        )

    assert "resume-only가 지정됐지만 기존 output_dir가 없습니다" in str(exc_info.value)


def test_run_capture_pipeline_writes_error_artifact_on_capture_timeout(
    tmp_path: Path,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-capture-timeout-season",
        include_ocr=False,
    )
    output_dir = tmp_path / "capture-output"

    class TimeoutAdbClient:
        def capture_screenshot(self, *, device_serial):
            raise capture_import.MockImportError(
                "adb exec-out screencap 명령이 시간 초과로 중단됐습니다. timeout=20s"
            )

    with pytest.raises(capture_import.MockImportError) as exc_info:
        run_capture_pipeline(
            request_path,
            base_url="http://localhost:8000",
            output_dir=str(output_dir),
            adb_client=TimeoutAdbClient(),
            api_client=SnapshotAwareApiClientMixin(),
        )

    assert "시간 초과로 중단됐습니다" in str(exc_info.value)
    pipeline_error = json.loads(
        (output_dir / "pipeline-error.json").read_text(encoding="utf-8")
    )
    assert pipeline_error["stage"] == "capture"
    assert pipeline_error["error_type"] == "MockImportError"
    assert "timeout=20s" in pipeline_error["message"]


def test_run_capture_pipeline_writes_error_artifact_on_tesseract_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-tesseract-timeout-season",
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"\x89PNG\r\n\x1a\nfake"

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=kwargs.get("args", args[0] if args else []),
            timeout=kwargs["timeout"],
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    output_dir = tmp_path / "capture-output"
    with pytest.raises(capture_import.MockImportError) as exc_info:
        run_capture_pipeline(
            request_path,
            base_url="http://localhost:8000",
            output_dir=str(output_dir),
            ocr_provider="tesseract",
            ocr_language="eng",
            ocr_psm=6,
            adb_client=FakeAdbClient(),
            api_client=SnapshotAwareApiClientMixin(),
        )

    assert "시간 초과로 중단됐습니다" in str(exc_info.value)
    pipeline_error = json.loads(
        (output_dir / "pipeline-error.json").read_text(encoding="utf-8")
    )
    assert pipeline_error["stage"] == "parse_capture_payload"
    assert pipeline_error["error_type"] == "MockImportError"
    assert "timeout=30s" in pipeline_error["message"]


def test_run_capture_pipeline_passes_parse_timeout_seconds_to_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-parse-timeout-wiring-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["pipeline"] = {"parse_timeout_seconds": 7}
    request_path.write_text(json.dumps(request_payload, ensure_ascii=False), encoding="utf-8")

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"\x89PNG\r\n\x1a\nfake"

    observed_timeouts: list[int | None] = []

    def fake_parse_capture_payload(payload, *, validate_snapshot_entries=True, parse_timeout_seconds=None):
        observed_timeouts.append(parse_timeout_seconds)
        raise capture_import.MockImportError(
            f"capture parse 단계가 시간 초과로 중단됐습니다. timeout={parse_timeout_seconds}s"
        )

    monkeypatch.setattr(capture_pipeline, "parse_capture_payload", fake_parse_capture_payload)

    output_dir = tmp_path / "capture-output"
    with pytest.raises(capture_import.MockImportError) as exc_info:
        run_capture_pipeline(
            request_path,
            base_url="http://localhost:8000",
            output_dir=str(output_dir),
            adb_client=FakeAdbClient(),
            api_client=SnapshotAwareApiClientMixin(),
        )

    assert observed_timeouts == [7]
    assert "timeout=7s" in str(exc_info.value)
    pipeline_error = json.loads(
        (output_dir / "pipeline-error.json").read_text(encoding="utf-8")
    )
    assert pipeline_error["stage"] == "parse_capture_payload"
    assert "timeout=7s" in pipeline_error["message"]


def test_run_capture_pipeline_writes_partial_result_on_parse_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-parse-partial-timeout-season",
        include_ocr=False,
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"\x89PNG\r\n\x1a\nfake"

    def fake_parse_capture_payload(
        payload,
        *,
        validate_snapshot_entries=True,
        parse_timeout_seconds=None,
    ):
        error = capture_import.MockImportError(
            f"capture parse 단계가 시간 초과로 중단됐습니다. timeout={parse_timeout_seconds}s, page_index=3"
        )
        error.capture_parse_progress = {
            "last_completed_page_index": 2,
            "timed_out_page_index": 3,
            "processed_page_count": 2,
            "page_summaries": [
                {"page_index": 1, "entry_count": 2},
                {"page_index": 2, "entry_count": 1},
            ],
        }
        raise error

    monkeypatch.setattr(capture_pipeline, "parse_capture_payload", fake_parse_capture_payload)

    output_dir = tmp_path / "capture-output"
    with pytest.raises(capture_import.MockImportError):
        run_capture_pipeline(
            request_path,
            base_url="http://localhost:8000",
            output_dir=str(output_dir),
            adb_client=FakeAdbClient(),
            api_client=SnapshotAwareApiClientMixin(),
        )

    pipeline_error = json.loads(
        (output_dir / "pipeline-error.json").read_text(encoding="utf-8")
    )
    assert pipeline_error["stage"] == "parse_capture_payload"
    assert pipeline_error["partial_result"] == {
        "last_completed_page_index": 2,
        "timed_out_page_index": 3,
        "processed_page_count": 2,
        "page_summaries": [
            {"page_index": 1, "entry_count": 2},
            {"page_index": 2, "entry_count": 1},
        ],
    }


def test_run_capture_pipeline_force_recapture_clears_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-force-recapture-season",
    )
    output_dir = tmp_path / "capture-output"
    output_dir.mkdir()
    (output_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (output_dir / "pipeline-error.json").write_text("{}", encoding="utf-8")

    class FakeAdbClient:
        def __init__(self):
            self.capture_calls = 0

        def capture_screenshot(self, *, device_serial):
            self.capture_calls += 1
            return b"\x89PNG\r\n\x1a\nfresh"

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 1}

    def fake_run(args, capture_output, text, check, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="1\tFresh OCR\t12345678\t0.99\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    adb_client = FakeAdbClient()
    result = run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(output_dir),
        adb_client=adb_client,
        api_client=FakeApiClient(),
        force_recapture=True,
    )

    assert adb_client.capture_calls == 1
    assert result.resumed_from_output is False
    assert (output_dir / "manifest.json").exists() is False


def test_run_capture_pipeline_reuses_existing_season_on_duplicate_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-existing-season",
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"\x89PNG\r\n\x1a\nfake"

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            raise ApiError(409, "Season label already exists")

        def list_seasons(self):
            return [
                {
                    "id": 909,
                    "event_type": "total_assault",
                    "server": "kr",
                    "boss_name": "Binah",
                    "armor_type": None,
                    "terrain": "outdoor",
                    "season_label": "pipeline-existing-season",
                    "started_at": None,
                    "ended_at": None,
                }
            ]

        def create_snapshot(self, season_id, payload):
            assert season_id == 909
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {
                "id": snapshot_id,
                "status": status,
                "total_rows_collected": 1,
            }

    def fake_run(args, capture_output, text, check, **kwargs):
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

    assert result.season_id == 909
    assert result.snapshot_id == 202


def test_run_capture_pipeline_persists_pipeline_stop_details_in_snapshot_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-note-details-season",
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"\x89PNG\r\n\x1a\nfake"

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def __init__(self):
            self.snapshot_payload: dict[str, object] | None = None

        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            self.snapshot_payload = {"season_id": season_id, **payload}
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {
                "id": snapshot_id,
                "status": status,
                "total_rows_collected": 1,
            }

    def fake_run(args, capture_output, text, check, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="RANK PLAYER SCORE\n1\tPlana\t12345678\t0.99\n",
            stderr="",
        )

    monkeypatch.setattr(capture_import.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(capture_import.subprocess, "run", fake_run)

    api_client = FakeApiClient()
    run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=api_client,
    )

    assert api_client.snapshot_payload is not None
    snapshot_note = api_client.snapshot_payload["note"]
    assert isinstance(snapshot_note, str)
    collector_summary_line = next(
        line for line in snapshot_note.splitlines() if line.startswith("collector:")
    )
    assert "ocr_stop=" not in collector_summary_line
    collector_json_line = next(
        line
        for line in snapshot_note.splitlines()
        if line.startswith("collector_json:")
    )
    collector_details = json.loads(collector_json_line.removeprefix("collector_json:").strip())
    assert collector_details["psr"] == {
        "s": False,
        "l": None,
        "src": None,
        "r": None,
    }
    assert collector_details["sp"] == {
        "m": 2,
        "t": 2,
    }


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

    class UnusedApiClient(SnapshotAwareApiClientMixin):
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

    class FailingApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            raise RuntimeError("unexpected import failure")

    def fake_run(args, capture_output, text, check, **kwargs):
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
    assert (tmp_path / "capture-output" / "manifest.json").exists() is False
    pipeline_error = json.loads(
        (tmp_path / "capture-output" / "pipeline-error.json").read_text(
            encoding="utf-8"
        )
    )
    assert pipeline_error["stage"] == "import"
    assert pipeline_error["error_type"] == "RuntimeError"
    assert pipeline_error["message"] == "unexpected import failure"
    assert pipeline_error["recovery"]["rerun_pipeline_command"].endswith(
        "--force-recapture --output-dir "
        f"{tmp_path / 'capture-output'} {request_path}"
    )


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

    class FakeApiClient(SnapshotAwareApiClientMixin):
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

    def fake_run(args, capture_output, text, check, **kwargs):
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

    class FakeApiClient(SnapshotAwareApiClientMixin):
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

    def fake_run(args, capture_output, text, check, **kwargs):
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
    assert result.ignored_line_reasons == [{"reason": "header_line", "count": 1}]
    assert result.ocr_stop_hints == [{"reason": "noisy_last_page", "page_index": 1, "ignored_line_count": 1, "entry_count": 1}]
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
    assert result.page_summaries == [
        {
            "page_index": 1,
            "image_path": capture_import._build_entry_image_path(
                (tmp_path / "capture-output" / "page-001.png").resolve()
            ),
            "entry_count": 1,
            "ignored_line_count": 1,
            "ignored_line_reasons": [{"reason": "header_line", "count": 1}],
            "first_rank": 1,
            "last_rank": 1,
            "overlap_with_previous_count": 0,
            "overlap_with_previous_ratio": 0.0,
            "overlap_with_previous_ranks": [],
            "new_rank_count": 1,
            "new_rank_ratio": 1.0,
            "absolute_rank_anchor": None,
            "absolute_rank_anchor_source": None,
            "absolute_rank_base": None,
            "absolute_rank_base_source": None,
            "detected_row_bands": [],
            "row_bands": [],
            "visible_row_count": 0,
            "row_debugs": [],
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

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 1}

    def fake_run(args, capture_output, text, check, **kwargs):
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

    assert result.import_skipped is False
    assert result.skip_reason is None
    pipeline_result = json.loads(
        (tmp_path / "capture-output" / "pipeline-result.json").read_text(
            encoding="utf-8"
        )
    )
    assert pipeline_result["import_skipped"] is False
    assert pipeline_result["skip_reason"] is None
    assert result.season_id == 101
    assert result.snapshot_id == 202
    assert result.entry_ids == [1]
    assert result.status == "completed"
    assert result.total_rows_collected == 1


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

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 1}

    def fake_run(args, capture_output, text, check, **kwargs):
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
        stop_on_recommendation=True,
    )

    assert result.import_skipped is False
    assert result.skip_reason is None


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

    class FakeApiClient(SnapshotAwareApiClientMixin):
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

    def fake_run(args, capture_output, text, check, **kwargs):
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

    class UnusedApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            raise AssertionError("import는 건너뛰어야 합니다")

    def fake_run(args, capture_output, text, check, **kwargs):
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

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 2}

    def fake_run(args, capture_output, text, check, **kwargs):
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

    assert result.captured_page_count == 3
    assert result.stopped_reason is None
    assert result.pipeline_stop_recommendation == {
        "should_stop": False,
        "level": None,
        "source": None,
        "primary_reason": None,
        "reasons": [],
    }
    assert result.import_skipped is False


def test_run_capture_pipeline_stops_capture_early_for_hard_recommendation_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-default-hard-stop-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
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

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 2}

    def fake_run(args, capture_output, text, check, **kwargs):
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

    assert result.captured_page_count == 3
    assert result.stopped_reason is None
    assert result.import_skipped is False


def test_run_capture_pipeline_does_not_stop_capture_early_when_explicitly_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-explicit-stop-off-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["pipeline"] = {"stop_capture_on_recommendation": False}
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

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 3}

    def fake_run(args, capture_output, text, check, **kwargs):
        image_name = Path(args[1]).name
        stdout_by_image = {
            "page-001.png": "1\tPlana\t12345678\t0.99\n10\tArona\t12000000\t0.98\n",
            "page-002.png": "header\n2\tSensei\t11000000\t0.98\nfooter\n",
            "page-003.png": "3\tMari\t10900000\t0.98\n",
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


def test_run_capture_pipeline_does_not_stop_capture_early_for_duplicate_last_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-duplicate-last-page-season",
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
            return [b"PNG-1", b"PNG-2", b"PNG-3", b"PNG-4"][self.capture_index - 1]

        def swipe(self, *, device_serial, swipe):
            return None

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 4}

    def fake_run(args, capture_output, text, check, **kwargs):
        image_name = Path(args[1]).name
        stdout_by_image = {
            "page-001.png": "1\tPlana\t12345678\t0.99\n2\tArona\t12000000\t0.98\n",
            "page-002.png": "3\tSensei\t11000000\t0.98\n4\tMari\t10900000\t0.97\n",
            "page-003.png": "3\tSensei\t11000000\t0.98\n4\tMari\t10900000\t0.97\n",
            "page-004.png": "5\tNoa\t10800000\t0.97\n",
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
    assert result.stopped_reason is None
    assert result.ocr_stop_hints == [
        {
            "reason": "sparse_last_page",
            "page_index": 4,
            "entry_count": 1,
        },
    ]
    assert result.pipeline_stop_recommendation == {
        "should_stop": False,
        "level": None,
        "source": None,
        "primary_reason": None,
        "reasons": [],
    }


def test_run_capture_pipeline_does_not_stop_capture_early_for_malformed_last_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-malformed-last-page-season",
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
            return [b"PNG-1", b"PNG-2", b"PNG-3", b"PNG-4"][self.capture_index - 1]

        def swipe(self, *, device_serial, swipe):
            return None

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 5}

    def fake_run(args, capture_output, text, check, **kwargs):
        image_name = Path(args[1]).name
        stdout_by_image = {
            "page-001.png": "1\tPlana\t12345678\t0.99\n2\tArona\t12000000\t0.98\n",
            "page-002.png": "3\tSensei\t11000000\t0.98\n4\tMari\t10900000\t0.97\n",
            "page-003.png": "junk line\nstill bad\n5\tNoa\t10800000\t0.97\n",
            "page-004.png": "6\tMika\t10700000\t0.97\n",
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
    assert result.stopped_reason is None
    assert result.import_skipped is False


def test_build_capture_stop_decision_supports_repeated_stale_last_page_soft_stop() -> None:
    stop_decision = capture_pipeline._build_capture_stop_decision(
        mode="any",
        ocr_stop_recommendation={
            "should_stop": True,
            "level": "soft",
            "primary_reason": "stale_last_page",
            "reasons": ["overlapping_last_page", "stale_last_page"],
        },
        stop_policy=PipelineStopPolicy(
            min_pages_before_ocr_stop=2,
            soft_stop_repeat_threshold=2,
            max_rank=None,
        ),
        captured_page_count=3,
        previous_soft_reason="stale_last_page",
        previous_soft_count=1,
    )

    assert stop_decision == capture_pipeline.AdbCaptureStopDecision(
        should_continue=False,
        reason="stale_last_page",
        source="ocr",
        level="soft",
        discard_last_page=False,
    )


def test_after_capture_page_uses_latest_page_only_for_max_rank_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-max-rank-latest-only-season",
        include_ocr=False,
    )
    request = capture_pipeline.load_adb_capture_request(request_path)
    parse_calls: list[str] = []

    monkeypatch.setattr(
        capture_pipeline,
        "parse_capture_payload",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("latest max-rank callback should not use parse_capture_payload")
        ),
    )
    monkeypatch.setattr(
        capture_pipeline,
        "_is_blue_archive_fixed_layout_image",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        capture_pipeline,
        "_parse_blue_archive_page_ranks_fast",
        lambda **kwargs: (
            parse_calls.append(kwargs["image_path"].name)
            or [3, 4]
        ),
    )

    callback = capture_pipeline._build_after_capture_page_callback(
        request=request,
        stop_policy=PipelineStopPolicy(
            min_pages_before_ocr_stop=2,
            soft_stop_repeat_threshold=2,
            max_rank=3,
        ),
        effective_ocr_provider="tesseract",
        ocr_command=None,
        ocr_language="eng",
        ocr_psm=6,
        stop_capture_on_recommendation_mode="off",
    )

    assert callback is not None

    first_decision = callback([Path("page-001.png"), Path("page-002.png")], None)
    second_decision = callback(
        [Path("page-001.png"), Path("page-002.png"), Path("page-003.png")],
        None,
    )

    assert parse_calls == ["page-002.png", "page-003.png"]
    assert first_decision == capture_pipeline.AdbCaptureStopDecision(should_continue=True)
    assert second_decision == capture_pipeline.AdbCaptureStopDecision(
        should_continue=False,
        reason="max_rank_reached",
        source="capture",
        level="hard",
        discard_last_page=False,
    )


def test_after_capture_page_requires_two_fast_max_rank_confirmations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-max-rank-two-confirm-season",
        include_ocr=False,
    )
    request = capture_pipeline.load_adb_capture_request(request_path)

    monkeypatch.setattr(
        capture_pipeline,
        "_is_blue_archive_fixed_layout_image",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        capture_pipeline,
        "_parse_blue_archive_page_ranks_fast",
        lambda **kwargs: [12001, 12002],
    )

    callback = capture_pipeline._build_after_capture_page_callback(
        request=request,
        stop_policy=PipelineStopPolicy(
            min_pages_before_ocr_stop=2,
            soft_stop_repeat_threshold=2,
            max_rank=7,
        ),
        effective_ocr_provider="tesseract",
        ocr_command=None,
        ocr_language="eng",
        ocr_psm=6,
        stop_capture_on_recommendation_mode="off",
    )

    assert callback is not None
    first_decision = callback([Path("page-001.png"), Path("page-002.png")], None)
    second_decision = callback(
        [Path("page-001.png"), Path("page-002.png"), Path("page-003.png")],
        None,
    )

    assert first_decision == capture_pipeline.AdbCaptureStopDecision(should_continue=True)
    assert second_decision == capture_pipeline.AdbCaptureStopDecision(
        should_continue=False,
        reason="max_rank_reached",
        source="capture",
        level="hard",
        discard_last_page=False,
    )


def test_after_capture_page_does_not_hard_stop_large_max_rank_from_fast_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-max-rank-large-fast-no-stop-season",
        include_ocr=False,
    )
    request = capture_pipeline.load_adb_capture_request(request_path)

    monkeypatch.setattr(
        capture_pipeline,
        "_is_blue_archive_fixed_layout_image",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        capture_pipeline,
        "_parse_blue_archive_page_ranks_fast",
        lambda **kwargs: [12001, 12002],
    )

    callback = capture_pipeline._build_after_capture_page_callback(
        request=request,
        stop_policy=PipelineStopPolicy(
            min_pages_before_ocr_stop=2,
            soft_stop_repeat_threshold=2,
            max_rank=12000,
        ),
        effective_ocr_provider="tesseract",
        ocr_command=None,
        ocr_language="eng",
        ocr_psm=6,
        stop_capture_on_recommendation_mode="off",
    )

    assert callback is not None
    first_decision = callback([Path("page-001.png"), Path("page-002.png")], None)
    second_decision = callback(
        [Path("page-001.png"), Path("page-002.png"), Path("page-003.png")],
        None,
    )

    assert first_decision == capture_pipeline.AdbCaptureStopDecision(should_continue=True)
    assert second_decision == capture_pipeline.AdbCaptureStopDecision(should_continue=True)


def test_after_capture_page_does_not_stop_when_rank_equals_max_rank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-max-rank-equals-season",
        include_ocr=False,
    )
    request = capture_pipeline.load_adb_capture_request(request_path)

    monkeypatch.setattr(
        capture_pipeline,
        "_is_blue_archive_fixed_layout_image",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        capture_pipeline,
        "_parse_blue_archive_page_ranks_fast",
        lambda **kwargs: [2, 3],
    )

    callback = capture_pipeline._build_after_capture_page_callback(
        request=request,
        stop_policy=PipelineStopPolicy(
            min_pages_before_ocr_stop=2,
            soft_stop_repeat_threshold=2,
            max_rank=3,
        ),
        effective_ocr_provider="tesseract",
        ocr_command=None,
        ocr_language="eng",
        ocr_psm=6,
        stop_capture_on_recommendation_mode="off",
    )

    assert callback is not None
    decision = callback([Path("page-001.png"), Path("page-002.png")], None)

    assert decision == capture_pipeline.AdbCaptureStopDecision(should_continue=True)


def test_after_capture_page_does_not_stop_for_single_sparse_high_rank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-max-rank-sparse-high-season",
        include_ocr=False,
    )
    request = capture_pipeline.load_adb_capture_request(request_path)

    monkeypatch.setattr(
        capture_pipeline,
        "_is_blue_archive_fixed_layout_image",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        capture_pipeline,
        "_parse_blue_archive_page_ranks_fast",
        lambda **kwargs: [12001],
    )

    callback = capture_pipeline._build_after_capture_page_callback(
        request=request,
        stop_policy=PipelineStopPolicy(
            min_pages_before_ocr_stop=2,
            soft_stop_repeat_threshold=2,
            max_rank=12000,
        ),
        effective_ocr_provider="tesseract",
        ocr_command=None,
        ocr_language="eng",
        ocr_psm=6,
        stop_capture_on_recommendation_mode="off",
    )

    assert callback is not None
    decision = callback([Path("page-001.png"), Path("page-002.png")], None)

    assert decision == capture_pipeline.AdbCaptureStopDecision(should_continue=True)


def test_after_capture_page_skips_large_max_rank_callback_on_non_interval_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-max-rank-interval-season",
        include_ocr=False,
    )
    request = capture_pipeline.load_adb_capture_request(request_path)

    monkeypatch.setattr(
        capture_pipeline,
        "parse_capture_payload",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("large max-rank cadence skip should not parse")
        ),
    )
    monkeypatch.setattr(
        capture_pipeline,
        "_is_blue_archive_fixed_layout_image",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("large max-rank cadence skip should not inspect OCR")
        ),
    )

    callback = capture_pipeline._build_after_capture_page_callback(
        request=request,
        stop_policy=PipelineStopPolicy(
            min_pages_before_ocr_stop=2,
            soft_stop_repeat_threshold=2,
            max_rank=12000,
        ),
        effective_ocr_provider="tesseract",
        ocr_command=None,
        ocr_language="eng",
        ocr_psm=6,
        stop_capture_on_recommendation_mode="off",
    )

    assert callback is not None
    decision = callback([Path("page-001.png"), Path("page-002.png")], None)

    assert decision == capture_pipeline.AdbCaptureStopDecision(should_continue=True)


def test_after_capture_page_checks_every_page_when_near_large_max_rank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-max-rank-near-threshold-season",
        include_ocr=False,
    )
    request = capture_pipeline.load_adb_capture_request(request_path)
    parse_calls: list[str] = []

    monkeypatch.setattr(
        capture_pipeline,
        "parse_capture_payload",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("near-threshold large max-rank callback should stay on fast path")
        ),
    )
    monkeypatch.setattr(
        capture_pipeline,
        "_is_blue_archive_fixed_layout_image",
        lambda **kwargs: True,
    )

    page_ranks = iter([[9999, 10000], [10001, 10002]])
    monkeypatch.setattr(
        capture_pipeline,
        "_parse_blue_archive_page_ranks_fast",
        lambda **kwargs: (
            parse_calls.append(kwargs["image_path"].name)
            or next(page_ranks)
        ),
    )

    callback = capture_pipeline._build_after_capture_page_callback(
        request=request,
        stop_policy=PipelineStopPolicy(
            min_pages_before_ocr_stop=2,
            soft_stop_repeat_threshold=2,
            max_rank=12000,
        ),
        effective_ocr_provider="tesseract",
        ocr_command=None,
        ocr_language="eng",
        ocr_psm=6,
        stop_capture_on_recommendation_mode="off",
    )

    assert callback is not None
    first_decision = callback([Path("page-001.png")], None)
    second_decision = callback([Path("page-001.png"), Path("page-002.png")], None)

    assert first_decision == capture_pipeline.AdbCaptureStopDecision(should_continue=True)
    assert second_decision == capture_pipeline.AdbCaptureStopDecision(should_continue=True)
    assert parse_calls == ["page-001.png", "page-002.png"]


def test_should_run_max_rank_callback_checks_small_threshold_every_page() -> None:
    assert capture_pipeline._should_run_max_rank_callback(
        captured_page_count=2,
        stop_policy=PipelineStopPolicy(
            min_pages_before_ocr_stop=2,
            soft_stop_repeat_threshold=2,
            max_rank=7,
        ),
    ) is True


def test_should_run_max_rank_callback_skips_large_threshold_until_interval() -> None:
    assert capture_pipeline._should_run_max_rank_callback(
        captured_page_count=2,
        stop_policy=PipelineStopPolicy(
            min_pages_before_ocr_stop=2,
            soft_stop_repeat_threshold=2,
            max_rank=12000,
        ),
        last_highest_rank_collected=None,
    ) is False
    assert capture_pipeline._should_run_max_rank_callback(
        captured_page_count=3,
        stop_policy=PipelineStopPolicy(
            min_pages_before_ocr_stop=2,
            soft_stop_repeat_threshold=2,
            max_rank=12000,
        ),
        last_highest_rank_collected=None,
    ) is True


def test_should_run_max_rank_callback_checks_every_page_near_threshold() -> None:
    assert capture_pipeline._should_run_max_rank_callback(
        captured_page_count=2,
        stop_policy=PipelineStopPolicy(
            min_pages_before_ocr_stop=2,
            soft_stop_repeat_threshold=2,
            max_rank=12000,
        ),
        last_highest_rank_collected=10000,
    ) is True


def test_should_run_max_rank_callback_checks_every_two_pages_mid_threshold() -> None:
    stop_policy = PipelineStopPolicy(
        min_pages_before_ocr_stop=2,
        soft_stop_repeat_threshold=2,
        max_rank=12000,
    )

    assert capture_pipeline._should_run_max_rank_callback(
        captured_page_count=2,
        stop_policy=stop_policy,
        last_highest_rank_collected=7000,
    ) is True
    assert capture_pipeline._should_run_max_rank_callback(
        captured_page_count=3,
        stop_policy=stop_policy,
        last_highest_rank_collected=7000,
    ) is False


def test_build_runtime_ocr_config_uses_fast_path_for_blue_archive_callback(
    tmp_path: Path,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-fast-runtime-ocr-season",
    )
    request = capture_pipeline.load_adb_capture_request(request_path)

    ocr = capture_pipeline._build_runtime_ocr_config(
        request=request,
        effective_ocr_provider="tesseract",
        ocr_command=None,
        ocr_language="eng",
        ocr_psm=11,
        blue_archive_fast_path=True,
    )

    assert ocr.blue_archive_fast_path is True
    assert ocr.upscale_ratio == 1.0
    assert ocr.persist_sidecar is False


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

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 4}

    def fake_run(args, capture_output, text, check, **kwargs):
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

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 3}

    def fake_run(args, capture_output, text, check, **kwargs):
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

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 4}

    def fake_run(args, capture_output, text, check, **kwargs):
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

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 4}

    def fake_run(args, capture_output, text, check, **kwargs):
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
        "max_rank": None,
    }


def test_run_capture_pipeline_stops_capture_when_max_rank_reached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-max-rank-season",
        include_ocr=False,
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["pipeline"] = {"max_rank": 3}
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

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": payload["rank"]}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status, "total_rows_collected": 3}

    def fake_run(args, capture_output, text, check, **kwargs):
        image_name = Path(args[1]).name
        stdout_by_image = {
            "page-001.png": "1\tPlana\t12345678\t0.99\n2\tArona\t12000000\t0.98\n",
            "page-002.png": "3\tSensei\t11000000\t0.98\n4\tMari\t10900000\t0.97\n",
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

    assert result.captured_page_count == 2
    assert result.stopped_reason == "max_rank_reached"
    assert result.highest_rank_collected == 4
    assert result.reached_max_rank is True
    assert result.entry_ids == [1, 2, 3]


def test_run_capture_pipeline_fresh_capture_uses_runtime_snapshot_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _write_request(
        tmp_path,
        season_label="pipeline-runtime-snapshot-season",
        include_ocr=False,
    )

    class FakeAdbClient:
        def capture_screenshot(self, *, device_serial):
            return b"\x89PNG\r\n\x1a\nfake"

    captured_snapshot_payloads: list[dict[str, object]] = []

    class FakeApiClient(SnapshotAwareApiClientMixin):
        def create_season(self, payload):
            return {"id": 101, **payload}

        def create_snapshot(self, season_id, payload):
            captured_snapshot_payloads.append(dict(payload))
            return {"id": 202, "season_id": season_id, **payload}

        def create_entry(self, snapshot_id, payload):
            return {"id": 1}

        def update_snapshot_status(self, snapshot_id, status):
            return {"id": snapshot_id, "status": status}

    monkeypatch.setattr(
        capture_pipeline,
        "parse_capture_payload",
        lambda *args, **kwargs: capture_import.ParsedCapturePayload(
            mock_payload=capture_import.MockImportPayload(
                season={
                    "event_type": "total_assault",
                    "server": "kr",
                    "boss_name": "Binah",
                    "terrain": "outdoor",
                    "season_label": "pipeline-runtime-snapshot-season",
                },
                snapshot={"captured_at": "ignored", "source_type": "image"},
                entries=[
                    {
                        "rank": 1,
                        "player_name": "Lunatic",
                        "score": 53404105,
                        "ocr_confidence": None,
                        "raw_text": "row",
                        "image_path": "page-001.png",
                        "is_valid": True,
                        "validation_issue": None,
                    }
                ],
            ),
            ignored_lines=[],
            page_summaries=[],
        ),
    )

    run_capture_pipeline(
        request_path,
        base_url="http://localhost:8000",
        output_dir=str(tmp_path / "capture-output"),
        adb_client=FakeAdbClient(),
        api_client=FakeApiClient(),
    )

    assert len(captured_snapshot_payloads) == 1
    assert captured_snapshot_payloads[0]["captured_at"] != "2026-04-16T12:00:00Z"


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
