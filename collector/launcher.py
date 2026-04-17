from __future__ import annotations

import argparse
from collections.abc import Callable

import collector.adb_capture as adb_capture
import collector.capture_import as capture_import
import collector.mock_import as mock_import
import collector.run_capture_pipeline as run_capture_pipeline

CommandHandler = Callable[[list[str] | None], int]

COMMAND_HANDLERS: dict[str, tuple[str, CommandHandler]] = {
    "mock": (
        "JSON mock 데이터를 backend에 주입합니다.",
        mock_import.main,
    ),
    "capture": (
        "이미 준비된 capture 디렉터리/manifest를 OCR 후 backend에 적재합니다.",
        capture_import.main,
    ),
    "adb": (
        "ADB로 screenshot capture 디렉터리를 생성합니다.",
        adb_capture.main,
    ),
    "pipeline": (
        "ADB capture부터 OCR import까지 한 번에 수행합니다.",
        run_capture_pipeline.main,
    ),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plana-collector",
        description="Plana AI collector 통합 실행기",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )
    for command_name, (help_text, _) in COMMAND_HANDLERS.items():
        subparser = subparsers.add_parser(
            command_name,
            add_help=False,
            help=help_text,
            description=help_text,
        )
        subparser.add_argument(
            "args",
            nargs=argparse.REMAINDER,
            help="하위 명령에 그대로 전달할 인자",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _, handler = COMMAND_HANDLERS[args.command]
    forwarded_args = list(args.args)
    if forwarded_args and forwarded_args[0] == "--":
        forwarded_args = forwarded_args[1:]
    return handler(forwarded_args)


if __name__ == "__main__":
    raise SystemExit(main())
