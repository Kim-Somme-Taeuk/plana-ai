from __future__ import annotations

import pytest

import collector.launcher as launcher


@pytest.mark.parametrize(
    ("command_name", "forwarded_args"),
    [
        ("mock", ["sample.json", "--base-url", "http://localhost:8000"]),
        ("capture", ["capture-dir", "--ocr-provider", "tesseract"]),
        ("adb", ["request.json", "--device-serial", "emulator-5554"]),
        ("pipeline", ["request.json", "--resume-only"]),
    ],
)
def test_launcher_forwards_args_to_subcommand(
    monkeypatch: pytest.MonkeyPatch,
    command_name: str,
    forwarded_args: list[str],
) -> None:
    captured: dict[str, list[str]] = {}

    def fake_handler(argv: list[str] | None) -> int:
        captured["argv"] = [] if argv is None else list(argv)
        return 17

    help_text, _ = launcher.COMMAND_HANDLERS[command_name]
    monkeypatch.setitem(
        launcher.COMMAND_HANDLERS,
        command_name,
        (help_text, fake_handler),
    )

    exit_code = launcher.main([command_name, *forwarded_args])

    assert exit_code == 17
    assert captured["argv"] == forwarded_args


def test_launcher_strips_optional_double_dash(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_handler(argv: list[str] | None) -> int:
        captured["argv"] = [] if argv is None else list(argv)
        return 0

    help_text, _ = launcher.COMMAND_HANDLERS["pipeline"]
    monkeypatch.setitem(
        launcher.COMMAND_HANDLERS,
        "pipeline",
        (help_text, fake_handler),
    )

    exit_code = launcher.main(["pipeline", "--", "request.json", "--resume-only"])

    assert exit_code == 0
    assert captured["argv"] == ["request.json", "--resume-only"]
