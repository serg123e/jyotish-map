"""Yogas and doshas whose condition is arithmetic, checked rather than believed.

Prompt 01 §11 records the site's yoga list as data; Prompt 10 §3 asks whether
each yoga was judged «по фактическому выполнению условий». On the first full
reading that judgement was done by hand: Kala Sarpa turned out *not* to hold
by degree (Jupiter and Saturn lay beyond Rahu), while the site had declared
it by sign. The rules below are the ones with one right answer from the
positions alone — no aspect strengths, no judgement — so they belong to code.

Everything here takes the planet rows of ``show-info-D1`` and returns a
verdict with the facts it rests on, in the same «условие → выполнено / нет»
form the reading has to show. Anything that needs an interpretive choice
(which orb for a yoga, whether an aspect is strong enough) is not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .derive import SIGN_CODES, SIGN_LORDS, distance

CLASSICAL = ("Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa")

#: Combustion orbs in degrees from the Sun, the common Parashari values; a
#: retrograde Mercury or Venus is combust only closer in.
COMBUSTION_ORBS = {"Mo": 12.0, "Ma": 17.0, "Me": 14.0, "Ju": 11.0, "Ve": 10.0, "Sa": 15.0}
COMBUSTION_ORBS_RETRO = {"Me": 12.0, "Ve": 8.0}

#: Debilitation sign of each planet, and the planet exalted in that sign
#: (whose presence in a kendra is one of the classical cancellations).
DEBILITATION = {"Su": 7, "Mo": 8, "Ma": 4, "Me": 12, "Ju": 10, "Ve": 6, "Sa": 1}
EXALTATION = {"Su": 1, "Mo": 2, "Ma": 10, "Me": 6, "Ju": 4, "Ve": 12, "Sa": 7}

#: Natural benefics for the purpose of Kendradhipati: the Moon and Mercury
#: are conditional in the texts, so only the three unconditional ones count
#: for a dosha here, and the conditional ones are listed without a verdict.
BENEFICS = ("Ju", "Ve", "Me")
KENDRAS = (1, 4, 7, 10)


@dataclass(frozen=True)
class Verdict:
    """One rule, one answer, and the facts it rests on."""

    name: str
    holds: bool | None          # None: not applicable to this chart
    facts: tuple[str, ...] = ()
    #: Which planet the verdict is about, for rules checked per planet.
    planet: str = ""


@dataclass
class Body:
    code: str
    sign: int                   # 1–12
    degree: float               # within the sign
    retrograde: bool = False
    dignity: str = ""
    navamsa_sign: int | None = None

    @property
    def longitude(self) -> float:
        return (self.sign - 1) * 30 + self.degree


def bodies(show_info: dict[str, Any]) -> dict[str, Body]:
    """The planet rows of show-info-D1 as positions, keyed by code."""
    out: dict[str, Body] = {}
    for planet in show_info.get("planets", []):
        code = planet.get("code")
        rasi = (planet.get("rasi") or {}).get("code")
        degree = planet.get("degrees_decimal")
        if not code or rasi not in SIGN_CODES or degree is None:
            continue
        navamsa = planet.get("navamsa")
        out[code] = Body(
            code=code, sign=SIGN_CODES.index(rasi) + 1, degree=float(degree),
            retrograde=bool(planet.get("retrograde")),
            dignity=(planet.get("rasi") or {}).get("dignity") or "",
            navamsa_sign=_sign_number(navamsa) if navamsa else None,
        )
    return out


def _sign_number(name: str) -> int | None:
    from .derive import SIGNS_EN

    return SIGNS_EN.index(name) + 1 if name in SIGNS_EN else None


def _arc(start: float, end: float, point: float) -> bool:
    """Whether ``point`` lies on the arc from ``start`` forward to ``end``."""
    return (point - start) % 360 <= (end - start) % 360


# ---------------------------------------------------------------------------


def kala_sarpa(positions: dict[str, Body]) -> Verdict:
    """All seven classical planets within one half of the Rahu–Ketu axis.

    Checked by longitude, not by sign: a planet in Rahu's sign but past its
    degree is outside the axis, and that is exactly the case the first
    reading found the site's list ignoring.
    """
    if "Ra" not in positions or "Ke" not in positions:
        return Verdict("Кала-сарпа", None, ("нет положений узлов",))
    rahu, ketu = positions["Ra"].longitude, positions["Ke"].longitude
    present = [positions[c] for c in CLASSICAL if c in positions]
    outside_ra_ke = [b.code for b in present if not _arc(rahu, ketu, b.longitude)]
    outside_ke_ra = [b.code for b in present if not _arc(ketu, rahu, b.longitude)]
    if not outside_ra_ke or not outside_ke_ra:
        side = "Раху → Кету" if not outside_ra_ke else "Кету → Раху"
        return Verdict("Кала-сарпа", True, (
            f"все семь планет в дуге {side} по градусам "
            f"(Раху {rahu:.3f}°, Кету {ketu:.3f}°)",))
    fewer = min((outside_ra_ke, "Раху → Кету"), (outside_ke_ra, "Кету → Раху"), key=lambda x: len(x[0]))
    return Verdict("Кала-сарпа", False, (
        f"вне дуги {fewer[1]} по градусам: {', '.join(fewer[0])} "
        f"(Раху {rahu:.3f}°, Кету {ketu:.3f}°); по знакам сайт может объявлять йогу — "
        "по долготам условие не выполнено",))


def combustion(positions: dict[str, Body]) -> list[Verdict]:
    """Which planets are within their orb of the Sun."""
    if "Su" not in positions:
        return []
    sun = positions["Su"].longitude
    out = []
    for code, orb in COMBUSTION_ORBS.items():
        body = positions.get(code)
        if body is None:
            continue
        limit = COMBUSTION_ORBS_RETRO.get(code, orb) if body.retrograde else orb
        gap = abs((body.longitude - sun + 180) % 360 - 180)
        out.append(Verdict(
            "Сожжение", gap <= limit,
            (f"{gap:.2f}° от Солнца при орбисе {limit:g}°"
             + (" (ретроградный)" if body.retrograde else ""),),
            planet=code,
        ))
    return out


def kendradhipati(lagna_sign: int) -> Verdict:
    """A natural benefic owning kendras — the dosha of the dual-sign lagnas.

    Strongest when one benefic owns two kendras (Jupiter for Gemini and Virgo,
    Mercury for Sagittarius and Pisces). One kendra alone is listed, not
    called a dosha.
    """
    owners: dict[str, list[int]] = {}
    for house in KENDRAS:
        sign = (lagna_sign - 1 + house - 1) % 12 + 1
        lord = SIGN_LORDS[sign]
        if lord in BENEFICS:
            owners.setdefault(lord, []).append(house)
    strong = {lord: houses for lord, houses in owners.items() if len(houses) >= 2}
    facts = tuple(f"{lord} управляет кендрами {', '.join(map(str, houses))}"
                  for lord, houses in owners.items()) or ("благодетели кендрами не управляют",)
    return Verdict("Кендрадхипати-доша", bool(strong), facts)


def neecha_bhanga(positions: dict[str, Body], lagna_sign: int) -> list[Verdict]:
    """Cancellation of debilitation, by the three conditions that are positional.

    (a) the lord of the debilitation sign is in a kendra from the lagna or
    the Moon; (b) the planet exalted in that sign is in such a kendra; (c) the
    debilitated planet is exalted in the navamsa. Other conditions in the
    texts need aspects or strengths and are left to the reading.
    """
    moon = positions.get("Mo")
    out = []
    for code, sign in DEBILITATION.items():
        body = positions.get(code)
        if body is None or body.sign != sign:
            continue
        met = []
        lord = SIGN_LORDS[sign]
        exalted_here = next((p for p, s in EXALTATION.items() if s == sign), None)
        for label, helper in (("управитель знака падения", lord),
                              ("планета, экзальтирующая в этом знаке", exalted_here)):
            other = positions.get(helper or "")
            if other is None or other.code == code:
                continue
            if distance(lagna_sign, other.sign) in KENDRAS:
                met.append(f"{label} ({helper}) в кендре от Лагны")
            elif moon is not None and distance(moon.sign, other.sign) in KENDRAS:
                met.append(f"{label} ({helper}) в кендре от Луны")
        if body.navamsa_sign == EXALTATION[code]:
            met.append("планета экзальтирована в навамше")
        out.append(Verdict(
            "Нича-бханга", bool(met),
            tuple(met) or ("ни одно из позиционных условий отмены не выполнено",),
            planet=code,
        ))
    return out


def check_all(show_info: dict[str, Any]) -> list[Verdict]:
    """Every rule, for the raw export and the reading."""
    positions = bodies(show_info)
    lagna = positions.get("As")
    verdicts = [kala_sarpa(positions)] + combustion(positions)
    if lagna is not None:
        verdicts.append(kendradhipati(lagna.sign))
        verdicts += neecha_bhanga(positions, lagna.sign)
    return verdicts


def as_rows(verdicts: Iterable[Verdict]) -> list[tuple[str, str, str]]:
    """(rule, verdict, facts) rows for a Markdown table."""
    rows = []
    for v in verdicts:
        name = f"{v.name} — {v.planet}" if v.planet else v.name
        state = "не применимо" if v.holds is None else ("**выполнено**" if v.holds else "не выполнено")
        rows.append((name, state, "; ".join(v.facts)))
    return rows
