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


# ---- the ayanamsa is measured from the equinox OF DATE ----------------------

#: Precession between a 1980 chart and J2000 — the size of the bug guarded here.
PRECESSION = 0.2765

#: True tropical longitude of date, per skyfield key.
OF_DATE = {"sun": 30.0, "moon": 60.0, "mars barycenter": 90.0,
           "mercury barycenter": 120.0, "jupiter barycenter": 150.0,
           "venus barycenter": 180.0, "saturn barycenter": 210.0}


class _FakeEphemeris:
    """Just enough of skyfield to see which ecliptic the code asks for.

    A body's J2000 longitude is its of-date longitude plus the precession
    since then, exactly as the real sky behaves for a chart before 2000.
    """

    def __init__(self) -> None:
        self.epochs: list = []

    def __getitem__(self, key):
        return _Earth(self) if key == "earth" else key

    # skyfield spells it ephemeris["earth"].at(t).observe(body).apparent()


class _Earth:
    def __init__(self, ephemeris: _FakeEphemeris) -> None:
        self.ephemeris = ephemeris

    def at(self, moment):
        return _Observer(self.ephemeris)


class _Observer:
    def __init__(self, ephemeris: _FakeEphemeris) -> None:
        self.ephemeris = ephemeris

    def observe(self, key):
        return _Observation(self.ephemeris, key)


class _Observation:
    def __init__(self, ephemeris: _FakeEphemeris, key: str) -> None:
        self.ephemeris, self.key = ephemeris, key

    def apparent(self):
        return self

    def ecliptic_latlon(self, epoch=None):
        self.ephemeris.epochs.append(epoch)
        degrees = OF_DATE[self.key] + (PRECESSION if epoch is None else 0.0)
        return None, _Longitude(degrees), None


class _Longitude:
    def __init__(self, degrees: float) -> None:
        self.degrees = degrees


def test_tropical_longitudes_ask_for_the_ecliptic_of_date() -> None:
    """Without an epoch skyfield answers in J2000 — 16.6′ off for a 1980 chart.

    That omission once made this module accuse vedic-horo of declaring an
    ayanamsa 16.7′ away from its own positions. The site was right.
    """
    from jyotish.crosscheck import tropical_longitudes

    ephemeris = _FakeEphemeris()
    moment = object()
    longitudes = tropical_longitudes(ephemeris, moment)

    assert ephemeris.epochs, "ecliptic_latlon не вызывался"
    assert all(epoch is moment for epoch in ephemeris.epochs), (
        "эклиптика должна браться на дату карты, а не на J2000"
    )
    assert longitudes["Su"] == pytest.approx(30.0)
    assert set(longitudes) == set(CLASSICAL_CODES)


CLASSICAL_CODES = ("Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa")


def test_the_missing_epoch_would_shift_the_answer_by_the_precession() -> None:
    """The guard above is worth having only if the mistake actually moves the number."""
    from jyotish.crosscheck import ayanamsa_from, tropical_longitudes

    positions = {code: {"sidereal": OF_DATE[key] - 23.5679}
                 for code, key in zip(CLASSICAL_CODES, OF_DATE)}
    correct = ayanamsa_from(tropical_longitudes(_FakeEphemeris(), object()), positions)
    assert correct == pytest.approx(23.5679, abs=1e-6)
    assert (correct + PRECESSION - 23.5679) * 60 == pytest.approx(16.6, abs=0.1)


def test_implied_ayanamsa_is_the_mean_offset_from_the_sidereal_positions() -> None:
    from jyotish.crosscheck import ayanamsa_from

    assert ayanamsa_from({"Su": 30.0, "Mo": 60.0},
                         {"Su": {"sidereal": 6.4}, "Mo": {"sidereal": 36.4}}) \
        == pytest.approx(23.6)


def test_a_body_only_one_side_has_is_skipped_not_counted_as_zero() -> None:
    from jyotish.crosscheck import ayanamsa_from

    longitudes = {"Su": 30.0, "Mo": 60.0}
    assert ayanamsa_from(longitudes, {"Su": {"sidereal": 6.4}}) == pytest.approx(23.6)
    assert ayanamsa_from(longitudes, {}) is None


# ---- an explained disagreement stops being a question ------------------------


def test_the_lagna_offset_equal_to_the_librarys_ayanamsa_slip_is_explained() -> None:
    from jyotish.crosscheck import _explain_ascendant

    # The library declares 23.8467° but its planets imply 23.5677°: a slip of
    # +16.7′. Its lagna is 16.7′ *behind* the site's — the same amount.
    report = Report(local_ayanamsa=23.8467)
    report.findings.append(Finding("As: сидерическая долгота", WARN, "Aries 28.162°",
                                   "Aries 27.896°", "-15.95′"))
    site = {"As": {"sidereal": 28.162}}
    local = {"As": {"sidereal": 27.896}, "Su": {"sidereal": 336.167}}
    # tropical Sun such that the implied ayanamsa is 23.5677°
    _explain_ascendant(report, site, local, {"Su": 336.167 + 23.5677})
    assert report.findings[0].status == OK
    assert "ошибке заявленной айанамши" in report.findings[0].note


def test_a_lagna_offset_of_another_size_stays_open() -> None:
    from jyotish.crosscheck import _explain_ascendant

    report = Report(local_ayanamsa=23.8467)
    report.findings.append(Finding("As: сидерическая долгота", WARN, "", "", "-40.0′"))
    site = {"As": {"sidereal": 28.162}}
    local = {"As": {"sidereal": 28.162 - 40 / 60}, "Su": {"sidereal": 336.167}}
    _explain_ascendant(report, site, local, {"Su": 336.167 + 23.5677})
    assert report.findings[0].status == WARN


def test_the_node_type_is_a_setting_once_recorded(tmp_path) -> None:
    from jyotish.client import Client, ConfigError

    chart = {"slug": "t", "date": "07.08.1983", "time": "23:00:00", "timezone": "+4",
             "latitude": "55.45", "longitude": "37.37"}
    assert Client.from_dict(chart, tmp_path).nodes == ""
    assert Client.from_dict({**chart, "nodes": "mean"}, tmp_path).nodes == "mean"
    with pytest.raises(ConfigError, match="nodes"):
        Client.from_dict({**chart, "nodes": "sometimes"}, tmp_path)
