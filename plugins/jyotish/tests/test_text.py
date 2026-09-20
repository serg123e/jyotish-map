"""The numeral agreement, including the teens the naive rule gets wrong."""

from __future__ import annotations

import pytest

from jyotish.text import counted, number, plural, superscript

FORMS = ("период", "периода", "периодов")


@pytest.mark.parametrize("count, expected", [
    (1, "период"), (2, "периода"), (4, "периода"), (5, "периодов"),
    (11, "периодов"), (12, "периодов"), (14, "периодов"), (15, "периодов"),
    (21, "период"), (22, "периода"), (25, "периодов"),
    (81, "период"), (101, "период"), (111, "периодов"), (112, "периодов"),
    (128, "периодов"), (192, "периода"), (288, "периодов"),
    (729, "периодов"), (731, "период"), (737, "периодов"),
    (0, "периодов"),
])
def test_numeral_agreement(count: int, expected: str) -> None:
    assert plural(count, *FORMS) == expected


def test_the_teens_are_not_treated_as_ending_in_one() -> None:
    """The naive «ends in 1» rule gives «11 период», which is the usual bug."""
    assert plural(11, *FORMS) == "периодов"
    assert plural(111, *FORMS) == "периодов"
    assert plural(1011, *FORMS) == "периодов"


def test_counted_puts_the_number_and_the_noun_together() -> None:
    assert counted(81, *FORMS) == "81 период"
    assert counted(192, *FORMS) == "192 периода"
    assert counted(128, *FORMS) == "128 периодов"


def test_superscript_renders_the_exponent() -> None:
    assert superscript(3) == "³"
    assert superscript(10) == "¹⁰"


# ---- one number, printed the same way everywhere ---------------------------


@pytest.mark.parametrize("value, expected", [
    (70.0, "70"), (62.5, "62.5"), (62.45, "62.5"), (62.44, "62.4"),
    (0.0, "0"), (100.0, "100"), (99.95, "100"), (-0.04, "0"),
])
def test_number_drops_a_trailing_zero_and_rounds_half_up(value, expected) -> None:
    assert number(value) == expected


def test_the_headline_and_the_table_total_cannot_disagree() -> None:
    """62.5 used to print as «62%» over a table whose total said 62.5."""
    assert number(62.5) == number(62.5)
    assert format(62.5, ".0f") == "62"      # чего быть не должно
    assert number(62.5) == "62.5"
