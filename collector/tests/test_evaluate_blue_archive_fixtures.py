from __future__ import annotations

from collector.evaluate_blue_archive_fixtures import compare_expected_and_actual


def test_compare_expected_and_actual_reports_exact_match() -> None:
    expected = [
        {"rank": 1, "difficulty": "Lunatic", "score": 53404105},
        {"rank": 2, "difficulty": "Lunatic", "score": 53393930},
    ]
    actual = [
        {"rank": 1, "difficulty": "Lunatic", "score": 53404105},
        {"rank": 2, "difficulty": "Lunatic", "score": 53393930},
    ]

    result = compare_expected_and_actual(expected=expected, actual=actual)

    assert result["exact_match"] is True
    assert result["row_accuracy"] == 1.0
    assert result["field_accuracy"] == 1.0


def test_compare_expected_and_actual_counts_partial_field_matches() -> None:
    expected = [
        {"rank": 12001, "difficulty": "Torment", "score": 40040720},
        {"rank": 12002, "difficulty": "Torment", "score": 40040720},
    ]
    actual = [
        {"rank": 12001, "difficulty": "Torment", "score": 40040720},
        {"rank": 12003, "difficulty": "Torment", "score": 40050000},
    ]

    result = compare_expected_and_actual(expected=expected, actual=actual)

    assert result["exact_match"] is False
    assert result["row_accuracy"] == 0.5
    assert result["field_accuracy"] == 0.6667
