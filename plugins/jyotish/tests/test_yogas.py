"""A yoga is a condition; here the condition is checked, not the site's list."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jyotish.yogas import (
    Body, as_rows, bodies, check_all, combustion, kala_sarpa, kendradhipati, neecha_bhanga,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _b(code: str, sign: int, degree: float, **kw) -> Body:
    return Body(code, sign, degree, **kw)


def _positions(*items: Body) -> dict[str, Body]:
    return {b.code: b for b in items}


# ---- Kala Sarpa ------------------------------------------------------------


def test_kala_sarpa_holds_when_all_seven_lie_in_one_arc() -> None:
    fixture = json.loads((FIXTURES / "show-info-D1.json").read_text(encoding="utf-8"))
    verdict = kala_sarpa(bodies(fixture))
    assert verdict.holds is True
    assert "Раху → Кету" in verdict.facts[0]


def test_kala_sarpa_fails_by_degree_when_a_planet_is_past_rahu() -> None:
    """The first reading: Jupiter and Saturn in Rahu's sign but beyond it."""
    positions = _positions(
        _b("Ra", 5, 5.349), _b("Ke", 11, 5.349),
        _b("Su", 12, 6.17), _b("Mo", 1, 23.92), _b("Ma", 5, 4.18), _b("Me", 11, 13.86),
        _b("Ju", 5, 8.73), _b("Ve", 1, 21.24), _b("Sa", 5, 29.60),
    )
    verdict = kala_sarpa(positions)
    assert verdict.holds is False
    assert "Ju, Sa" in verdict.facts[0]
    assert "по знакам сайт может объявлять йогу" in verdict.facts[0]


def test_kala_sarpa_without_nodes_is_not_applicable() -> None:
    assert kala_sarpa(_positions(_b("Su", 1, 1))).holds is None


# ---- combustion ------------------------------------------------------------


def test_combustion_uses_the_orb_of_each_planet() -> None:
    positions = _positions(_b("Su", 4, 21.09), _b("Me", 4, 28.0), _b("Mo", 4, 6.64),
                           _b("Ju", 5, 1.0))
    verdicts = {v.planet: v for v in combustion(positions)}
    assert verdicts["Me"].holds is True            # 6.9° < 14°
    assert verdicts["Mo"].holds is False           # 14.45° > 12°
    assert verdicts["Ju"].holds is True            # 9.9° < 11°, across the sign boundary


def test_a_retrograde_mercury_needs_a_tighter_orb() -> None:
    direct = _positions(_b("Su", 4, 10.0), _b("Me", 4, 23.0))
    retro = _positions(_b("Su", 4, 10.0), _b("Me", 4, 23.0, retrograde=True))
    assert combustion(direct)[0].holds is True     # 13° < 14°
    assert combustion(retro)[0].holds is False     # 13° > 12°
    assert "ретроградный" in combustion(retro)[0].facts[0]


def test_combustion_measures_the_short_way_round() -> None:
    positions = _positions(_b("Su", 1, 2.0), _b("Ve", 12, 25.0))
    assert combustion(positions)[0].holds is True  # 7° apart across 0°


# ---- Kendradhipati -----------------------------------------------------------


@pytest.mark.parametrize("lagna, strong, owner", [
    (3, True, "Ju"),     # Gemini: Jupiter owns 7 and 10
    (6, True, "Ju"),     # Virgo: Jupiter owns 4 and 7
    (9, True, "Me"),     # Sagittarius: Mercury owns 7 and 10
    (12, True, "Me"),    # Pisces: Mercury owns 4 and 7
    (1, False, "Ve"),    # Aries: Venus owns the 7th only
])
def test_kendradhipati_is_the_dosha_of_the_dual_signs(lagna: int, strong: bool, owner: str) -> None:
    verdict = kendradhipati(lagna)
    assert verdict.holds is strong
    assert any(owner in fact for fact in verdict.facts)


def test_a_lagna_whose_kendras_have_no_benefic_lord_says_so() -> None:
    # Cancer: kendras Cn(Mo) Li(Ve)… — Venus owns the 4th; Scorpio: Sc(Ma) Aq(Sa) Ta(Ve) Le(Su)
    verdict = kendradhipati(8)
    assert verdict.holds is False and any("Ve" in f for f in verdict.facts)


# ---- Neecha Bhanga -----------------------------------------------------------


def test_debilitation_cancelled_by_the_sign_lord_in_a_kendra_from_lagna() -> None:
    """Mars in Cancer, Moon (lord of Cancer) in Cancer = 4th from Aries."""
    positions = _positions(_b("As", 1, 0.5), _b("Ma", 4, 2.5, dignity="Debilitation"),
                           _b("Mo", 4, 6.6))
    verdict = neecha_bhanga(positions, lagna_sign=1)[0]
    assert verdict.planet == "Ma" and verdict.holds is True
    assert "управитель знака падения (Mo) в кендре от Лагны" in verdict.facts


def test_debilitation_cancelled_by_the_exalted_planet_in_a_kendra_from_the_moon() -> None:
    """Saturn in Aries; Sun (exalted in Aries) in a kendra from the Moon."""
    positions = _positions(_b("As", 2, 5.0), _b("Sa", 1, 10.0), _b("Mo", 3, 1.0), _b("Su", 6, 1.0))
    verdict = neecha_bhanga(positions, lagna_sign=2)[0]
    assert verdict.holds is True
    assert any("Su) в кендре от Луны" in f for f in verdict.facts)


def test_debilitation_cancelled_by_exaltation_in_navamsa() -> None:
    positions = _positions(_b("As", 5, 1.0), _b("Ju", 10, 3.0, navamsa_sign=4), _b("Sa", 2, 1.0))
    verdict = neecha_bhanga(positions, lagna_sign=5)[0]
    assert verdict.holds is True
    assert any("экзальтирована в навамше" in fact for fact in verdict.facts)


def test_uncancelled_debilitation_says_which_conditions_were_checked() -> None:
    # Venus in Virgo; Mercury (its lord, and exalted there) in Gemini — the 11th
    # from Leo, not a kendra; no Moon to reckon from.
    positions = _positions(_b("As", 5, 1.0), _b("Ve", 6, 3.0), _b("Me", 3, 1.0), _b("Ju", 3, 1.0))
    verdict = neecha_bhanga(positions, lagna_sign=5)[0]
    assert verdict.holds is False
    assert "ни одно из позиционных условий" in verdict.facts[0]


def test_a_planet_not_in_its_debilitation_sign_is_not_reported() -> None:
    assert neecha_bhanga(_positions(_b("As", 1, 0), _b("Ma", 10, 5)), 1) == []


# ---- the whole set on the fixture ------------------------------------------


def test_check_all_on_the_fixture_reads_every_rule() -> None:
    fixture = json.loads((FIXTURES / "show-info-D1.json").read_text(encoding="utf-8"))
    verdicts = check_all(fixture)
    names = {(v.name, v.planet) for v in verdicts}
    assert ("Кала-сарпа", "") in names
    assert ("Кендрадхипати-доша", "") in names
    assert ("Нича-бханга", "Ma") in names            # Mars in Cancer in the fixture
    assert ("Сожжение", "Me") in names
    rows = as_rows(verdicts)
    assert all(len(row) == 3 for row in rows)
    assert any(row[0] == "Нича-бханга — Ma" and row[1] == "**выполнено**" for row in rows)
