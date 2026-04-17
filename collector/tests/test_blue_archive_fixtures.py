from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import collector.capture_import as capture_import
from collector.capture_import import OcrConfig, OcrCrop


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "blue_archive"


def _fixture_cases() -> list[tuple[Path, Path]]:
    cases: list[tuple[Path, Path]] = []
    for image_path in sorted(FIXTURE_DIR.glob("*.png")):
        expected_path = image_path.with_suffix(".expected.json")
        if expected_path.exists():
            cases.append((image_path, expected_path))
    return cases


@pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="tesseract가 없는 환경에서는 실제 fixture OCR 회귀를 실행하지 않습니다.",
)
@pytest.mark.parametrize(("image_path", "expected_path"), _fixture_cases())
def test_blue_archive_fixture_ocr_regression(
    image_path: Path,
    expected_path: Path,
) -> None:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    ocr = OcrConfig(
        provider="tesseract",
        command="tesseract",
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
    assert actual == expected
