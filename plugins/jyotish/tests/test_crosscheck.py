"""The comparison logic, without either source.

The astronomy belongs to skyfield and the site; what is tested here is the part
that can be wrong on its own — parsing, the arcminute difference across 0°, the
house-versus-sign reindexing of Ashtakavarga, and the rule that a disagreement
is reported rather than resolved.
"""

from __future__ import annotations

import pytest

from jyotish.crosscheck import (
    CONFLICT,
    OK,
    WARN,
    Finding,
    Report,
    _arcmin,
    _coord,
    _dms,
    _normalise,
    _place,
    _site_positions,
    render,
)


@pytest.mark.parametrize("text, expected", [
    ("21°05'41''", 21.094722),
    ("00°33'53''", 0.564722),
    ("5°", 5.0),
    ("", None),
    ("—", None),
])
def test_degrees_parsing(text, expected) -> None:
    got = _dms(text)
    assert got is None if expected is None else got == pytest.approx(expected, abs=1e-5)


@pytest.mark.parametrize("value, expected", [
    ("55.45", 55.75),      # 55°45′
    ("37.37", 37 + 37 / 60),
    ("-33.52", -(33 + 52 / 60)),   # южная широта
    ("10", 10.0),
])
def test_coordinates_are_degrees_and_minutes_not_decimal(value, expected) -> None:
    """55.45 means 55°45′, exactly as the site's own form submits it."""
    assert _coord(value) == pytest.approx(expected, abs=1e-9)


def test_arcmin_takes_the_short_way_round_zero() -> None:
    """359.9° and 0.1° are 12′ apart, not 21588′."""
    assert _arcmin(0.1, 359.9) == pytest.approx(12.0)
    assert _arcmin(359.9, 0.1) == pytest.approx(-12.0)
    assert _arcmin(10.0, 10.0) == 0.0


def test_transliteration_differences_are_not_disagreements() -> None:
    for a, b in (("Ashvini", "Ashwini"), ("Aslesha", "Ashlesha"),
                 ("Purvaphalguni", "Purva Phalguni")):
        assert _normalise(a) == _normalise(b), (a, b)


def test_different_nakshatras_still_differ() -> None:
    assert _normalise("Pushya") != _normalise("Ashlesha")


def test_ascendant_is_shown_without_a_house() -> None:
    assert _place({"sign": "Aries", "in_sign": 0.5647, "house": None}) == "Aries 0.565°"
    assert "(дом 4)" in _place({"sign": "Cancer", "in_sign": 21.1, "house": 4})


def test_site_positions_read_sign_degree_and_house() -> None:
    collection = {
        "show-info-D1": {
            "planets": [
                {"code": "Su", "rasi": {"name": "Cancer"}, "degrees": "21°05'41''",
                 "house": 4, "nakshatra": {"name": "Aslesha", "pada": 2}},
                {"code": "As", "rasi": {"name": "Aries"}, "degrees": "00°33'53''",
                 "house": None, "nakshatra": {"name": "Ashvini", "pada": 1}},
            ]
        },
        "show-other-D1": {"points": {"ayanamsa": {"value": "23°36'22''"}}},
    }
    ayanamsa, positions = _site_positions(collection)
    assert ayanamsa == pytest.approx(23.606111, abs=1e-5)
    assert positions["Su"]["sidereal"] == pytest.approx(90 + 21.094722, abs=1e-5)
    assert positions["As"]["sidereal"] == pytest.approx(0.564722, abs=1e-5)


def test_a_planet_the_site_did_not_place_is_skipped() -> None:
    collection = {"show-info-D1": {"planets": [
        {"code": "Ra", "rasi": {"name": None}, "degrees": "—"},
    ]}}
    _, positions = _site_positions(collection)
    assert positions == {}


# ---- the report ------------------------------------------------------------


def test_only_conflicts_count_as_conflicts() -> None:
    report = Report(findings=[
        Finding("а", OK), Finding("б", WARN), Finding("в", CONFLICT),
    ])
    assert [f.subject for f in report.conflicts] == ["в"]


def test_render_lists_every_finding_and_repeats_the_conflicts() -> None:
    report = Report(findings=[
        Finding("Su: сидерическая долгота", OK, "Cancer 21.095°", "Cancer 21.095°", "+0.00′"),
        Finding("Айанамша", CONFLICT, "23.6061°", "23.8394°", "расхождение 14.0′"),
    ])
    text = render(report)
    assert "Su: сидерическая долгота" in text
    assert "Расхождений: **1**" in text
    assert "## Требуют разбирательства" in text
    assert text.count("Айанамша") >= 2      # в таблице и в списке разбирательств


def test_render_says_nothing_to_investigate_when_all_agree() -> None:
    text = render(Report(findings=[Finding("Su", OK)]))
    assert "Расхождений: **0**" in text
    assert "## Требуют разбирательства" not in text


def test_report_never_picks_a_winner() -> None:
    """The point of the check is to surface disagreement, not resolve it."""
    text = render(Report(findings=[Finding("Айанамша", CONFLICT, "23.61", "23.84")]))
    assert "не выбирает победителя" in text


def test_a_truncated_name_is_the_same_nakshatra() -> None:
    """vedic-horo writes "Uttarabhadra"; the full name is "Uttara Bhadrapada"."""
    from jyotish.crosscheck import _same_nakshatra

    for a, b in (("Uttarabhadra", "Uttara Bhadrapada"),
                 ("Uttaraphalguni", "Uttara Phalguni"),
                 ("Satabhisha", "Shatabhisha"),
                 ("Ashvini", "Ashwini")):
        assert _same_nakshatra(a, b), (a, b)


def test_different_nakshatras_are_still_different() -> None:
    from jyotish.crosscheck import _same_nakshatra

    assert not _same_nakshatra("Purvaphalguni", "Uttara Phalguni")
    assert not _same_nakshatra("Pushya", "Ashlesha")
    assert not _same_nakshatra("Magha", "")
