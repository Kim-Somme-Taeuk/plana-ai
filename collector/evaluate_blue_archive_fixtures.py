from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from collector.capture_import import OcrConfig, OcrCrop
import collector.capture_import as capture_import


FIXTURE_DIR = Path(__file__).resolve().parent / "tests" / "fixtures" / "blue_archive"


def build_fixture_ocr_config(
    *,
    command: str | None = None,
) -> OcrConfig:
    return OcrConfig(
        provider="tesseract",
        command=command or "tesseract",
        language="eng",
        psm=11,
        extra_args=("-c", "preserve_interword_spaces=1"),
        crop=OcrCrop(
            left_ratio=0.39,
            top_ratio=0.34,
            right_ratio=0.56,
            bottom_ratio=0.94,
        ),
        upscale_ratio=2.0,
        reuse_cached_sidecar=False,
        persist_sidecar=False,
    )


def collect_fixture_cases(fixture_dir: Path) -> list[tuple[Path, Path]]:
    cases: list[tuple[Path, Path]] = []
    for image_path in sorted(fixture_dir.glob("*.png")):
        expected_path = image_path.with_suffix(".expected.json")
        if expected_path.exists():
            cases.append((image_path, expected_path))
    return cases


def compare_expected_and_actual(
    *,
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
) -> dict[str, Any]:
    field_names = ("rank", "difficulty", "score")
    row_count = max(len(expected), len(actual))
    exact_rows = 0
    matched_fields = 0
    total_fields = row_count * len(field_names)
    row_results: list[dict[str, Any]] = []

    for index in range(row_count):
        expected_row = expected[index] if index < len(expected) else None
        actual_row = actual[index] if index < len(actual) else None
        field_matches: dict[str, bool] = {}
        for field_name in field_names:
            field_matches[field_name] = (
                expected_row is not None
                and actual_row is not None
                and expected_row.get(field_name) == actual_row.get(field_name)
            )
        matched_fields += sum(field_matches.values())
        if all(field_matches.values()):
            exact_rows += 1
        row_results.append(
            {
                "index": index + 1,
                "expected": expected_row,
                "actual": actual_row,
                "field_matches": field_matches,
            }
        )

    exact_match = expected == actual
    field_accuracy = (matched_fields / total_fields) if total_fields else 1.0
    row_accuracy = (exact_rows / row_count) if row_count else 1.0
    return {
        "expected_count": len(expected),
        "actual_count": len(actual),
        "exact_match": exact_match,
        "row_accuracy": round(row_accuracy, 4),
        "field_accuracy": round(field_accuracy, 4),
        "rows": row_results,
    }


def evaluate_fixture_cases(
    *,
    fixture_dir: Path,
    ocr_command: str | None = None,
) -> dict[str, Any]:
    cases = collect_fixture_cases(fixture_dir)
    ocr = build_fixture_ocr_config(command=ocr_command)
    case_results: list[dict[str, Any]] = []

    for image_path, expected_path in cases:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        entries = capture_import._parse_tesseract_layout_entries(
            image_path=image_path,
            ocr=ocr,
            default_ocr_confidence=None,
            page_index=1,
        )
        actual = [
            {
                "rank": entry["rank"],
                "difficulty": entry["player_name"],
                "score": entry["score"],
            }
            for entry in entries
        ]
        comparison = compare_expected_and_actual(expected=expected, actual=actual)
        case_results.append(
            {
                "image": image_path.name,
                "expected_path": expected_path.name,
                **comparison,
            }
        )

    exact_match_cases = sum(1 for result in case_results if result["exact_match"])
    average_row_accuracy = (
        sum(result["row_accuracy"] for result in case_results) / len(case_results)
        if case_results
        else 1.0
    )
    average_field_accuracy = (
        sum(result["field_accuracy"] for result in case_results) / len(case_results)
        if case_results
        else 1.0
    )
    return {
        "case_count": len(case_results),
        "exact_match_cases": exact_match_cases,
        "average_row_accuracy": round(average_row_accuracy, 4),
        "average_field_accuracy": round(average_field_accuracy, 4),
        "cases": case_results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Blue Archive OCR fixture 정확도를 평가합니다.",
    )
    parser.add_argument(
        "--fixture-dir",
        default=str(FIXTURE_DIR),
        help="fixture 이미지와 expected.json이 있는 디렉터리",
    )
    parser.add_argument(
        "--ocr-command",
        default="tesseract",
        help="tesseract 실행 경로 또는 명령 이름",
    )
    parser.add_argument(
        "--min-field-accuracy",
        type=float,
        default=0.9,
        help="이 값 미만이면 exit code 1로 종료합니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if shutil.which(args.ocr_command) is None:
        print(
            json.dumps(
                {
                    "error": "tesseract_not_found",
                    "ocr_command": args.ocr_command,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    result = evaluate_fixture_cases(
        fixture_dir=Path(args.fixture_dir),
        ocr_command=args.ocr_command,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["average_field_accuracy"] < args.min_field_accuracy:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
