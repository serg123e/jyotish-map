"""A second, independent computation of the same chart, and what it disagrees with.

vedic-horo is one source. A reading built on one source can only be as right as
that source, and nothing in the pipeline would notice if it drifted. This module
recomputes the chart locally with `jyotishganit` (MIT, NASA JPL ephemeris via
skyfield) and reports every disagreement instead of picking a winner.

Both sources publish sidereal positions, so those are compared directly. The
ayanamsa is checked separately and differently: each source's declared value is
weighed against the one its own positions imply, worked out from an independent
ephemeris. That split is what caught vedic-horo declaring an ayanamsa 14′ away
from the one its own numbers are computed with — a source can be right about
the sky and wrong about what it says it did.

One disagreement is expected and is not a defect: **node type**. Mean and true
Rahu differ by up to ~2°, enough to change the sign and the house. The report
names it rather than averaging it away.

The module is optional. Without `jyotishganit` installed, everything else in the
pipeline works unchanged and the cross-check reports itself as unavailable.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .client import Client
from .derive import SIGNS_EN

#: How jyotishganit names the bodies, mapped to the site's codes.
BODY_CODES = {
    "Sun": "Su", "Moon": "Mo", "Mars": "Ma", "Mercury": "Me", "Jupiter": "Ju",
    "Venus": "Ve", "Saturn": "Sa", "Rahu": "Ra", "Ketu": "Ke",
    "North Node": "Ra", "South Node": "Ke",
}

#: The seven bodies whose positions both sources compute the same way. The nodes
#: are excluded: mean and true node are different points, not a disagreement.
CLASSICAL = ("Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa")

#: Skyfield keys for an independent tropical longitude, used to work out which
#: ayanamsa a source's own positions actually imply.
EPHEMERIS_KEYS = {
    "Su": "sun", "Mo": "moon", "Ma": "mars barycenter", "Me": "mercury barycenter",
    "Ju": "jupiter barycenter", "Ve": "venus barycenter", "Sa": "saturn barycenter",
}

#: Arcminutes of disagreement that count as noise, a warning, and a real conflict.
TOLERANCE_OK = 2.0
TOLERANCE_WARN = 30.0

OK = "совпало"
WARN = "внимание"
CONFLICT = "расхождение"
ADDED = "только локально"


class CrossCheckUnavailable(RuntimeError):
    """`jyotishganit` is not installed, so there is no second source."""


@dataclass
class Finding:
    subject: str
    status: str
    site: str = ""
    local: str = ""
    note: str = ""

    @property
    def conflicting(self) -> bool:
        return self.status == CONFLICT


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    site_ayanamsa: float | None = None
    local_ayanamsa: float | None = None
    implied_ayanamsa: float | None = None
    bhava_bala: dict[int, float] = field(default_factory=dict)

    @property
    def conflicts(self) -> list[Finding]:
        return [f for f in self.findings if f.conflicting]


def available() -> bool:
    try:
        import jyotishganit  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------


def _dms(text: str) -> float | None:
    """``21°05'41''`` -> 21.0947"""
    match = re.match(r"(\d+)°(?:(\d+)')?(?:(\d+)'')?", text or "")
    if not match:
        return None
    deg, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return deg + minutes / 60 + seconds / 3600


def _arcmin(first: float, second: float) -> float:
    """Signed difference in arcminutes, shortest way round the circle."""
    return ((first - second + 180) % 360 - 180) * 60


def _ephemeris_cache() -> Path:
    """Where the downloaded ephemeris lives — never the working directory."""
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.environ.get("XDG_CACHE_HOME") \
        or str(Path.home() / ".cache")
    path = Path(base) / "jyotish-ephemeris"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _place(position: dict[str, Any]) -> str:
    """`Cancer 21.095° (дом 4)`, with no house for the Ascendant."""
    house = position.get("house")
    suffix = f" (дом {house})" if house else ""
    return f"{position['sign']} {position['in_sign']:.3f}°{suffix}"


def _normalise(name: str) -> str:
    """Nakshatra names differ only in transliteration between the sources."""
    return re.sub(r"[^a-z]", "", (name or "").lower()).replace("sh", "s").replace("v", "w")


def _same_nakshatra(first: str, second: str) -> bool:
    """Whether two spellings name the same nakshatra.

    Beyond transliteration the sources also differ in how much of the name
    they keep: vedic-horo writes "Uttarabhadra" where the full name is
    "Uttara Bhadrapada". One being a prefix of the other is the same
    nakshatra, not a disagreement — and a checker that flags matching data
    teaches people to ignore it.
    """
    a, b = _normalise(first), _normalise(second)
    if not a or not b:
        return False
    shorter, longer = sorted((a, b), key=len)
    return longer.startswith(shorter) and len(shorter) >= 5


def _site_positions(collection: dict[str, Any]) -> tuple[float | None, dict[str, dict[str, Any]]]:
    info = collection.get("show-info-D1") or {}
    other = collection.get("show-other-D1") or {}
    ayanamsa = _dms(((other.get("points") or {}).get("ayanamsa") or {}).get("value") or "")
    positions: dict[str, dict[str, Any]] = {}
    for planet in info.get("planets", []):
        sign = (planet.get("rasi") or {}).get("name")
        degrees = _dms(planet.get("degrees") or "")
        if sign not in SIGNS_EN or degrees is None:
            continue
        nakshatra = planet.get("nakshatra") or {}
        positions[planet["code"]] = {
            "sign": sign,
            "sidereal": SIGNS_EN.index(sign) * 30 + degrees,
            "in_sign": degrees,
            "house": planet.get("house"),
            "nakshatra": nakshatra.get("name"),
            "pada": nakshatra.get("pada"),
        }
    return ayanamsa, positions


def _local_chart(client: Client) -> dict[str, Any]:
    try:
        from jyotishganit import calculate_birth_chart
    except ImportError as error:
        raise CrossCheckUnavailable(
            "нет пакета jyotishganit — второй источник недоступен. "
            "Поставьте: pip install 'jyotish-map[crosscheck]'"
        ) from error

    chart = client.chart
    day, month, year = (int(part) for part in chart.date.split("."))
    hour, minute, second = (int(part) for part in chart.time.split(":"))
    # jyotishganit builds its own skyfield loader with no configurable path, so
    # it downloads the ephemeris into the current directory. Run it from the
    # cache directory instead, or the first cross-check drops 68 MB of data
    # files into the user's repository.
    previous = os.getcwd()
    os.chdir(_ephemeris_cache())
    try:
        return calculate_birth_chart(
            datetime(year, month, day, hour, minute, second),
            latitude=_coord(chart.latitude),
            longitude=_coord(chart.longitude),
            timezone_offset=float(chart.timezone),
            name=chart.name,
        ).to_dict()
    finally:
        os.chdir(previous)


def _coord(value: str) -> float:
    """The site's degrees.minutes form to decimal degrees: 55.45 -> 55.75."""
    degrees, _, minutes = str(value).partition(".")
    sign = -1 if degrees.strip().startswith("-") else 1
    whole = abs(int(degrees))
    return sign * (whole + int((minutes or "0").ljust(2, "0")[:2]) / 60)


def _local_positions(chart: dict[str, Any]) -> tuple[float, dict[str, dict[str, Any]], dict[int, float]]:
    ayanamsa = chart["ayanamsa"]
    ayanamsa = ayanamsa["value"] if isinstance(ayanamsa, dict) else ayanamsa
    positions: dict[str, dict[str, Any]] = {}
    bhava: dict[int, float] = {}
    for house in chart["d1Chart"]["houses"]:
        number = house["number"]
        if house.get("bhavaBala") is not None:
            bhava[number] = float(house["bhavaBala"])
        if number == 1:
            positions["As"] = {
                "sign": house["sign"],
                "sidereal": SIGNS_EN.index(house["sign"]) * 30 + house["signDegrees"],
                "in_sign": house["signDegrees"], "house": None,
                "nakshatra": house.get("nakshatra"), "pada": house.get("pada"),
            }
        for body in house.get("occupants", []):
            code = BODY_CODES.get(body.get("celestialBody") or "")
            if not code:
                continue
            degrees = body.get("signDegrees")
            positions[code] = {
                "sign": house["sign"],
                "sidereal": SIGNS_EN.index(house["sign"]) * 30 + degrees,
                "in_sign": degrees, "house": number,
                "nakshatra": body.get("nakshatra"), "pada": body.get("pada"),
            }
    return float(ayanamsa), positions, bhava


def implied_ayanamsa(client: Client, positions: dict[str, dict[str, Any]]) -> float | None:
    """The ayanamsa a set of sidereal positions actually implies.

    Computed as (true tropical longitude − reported sidereal longitude), averaged
    over the classical bodies. This is what catches a source whose stated
    ayanamsa disagrees with its own numbers — which is not hypothetical.
    """
    try:
        from skyfield.api import Loader
    except ImportError:
        return None

    chart = client.chart
    day, month, year = (int(part) for part in chart.date.split("."))
    hour, minute, second = (int(part) for part in chart.time.split(":"))
    offset = float(chart.timezone)
    # Skyfield downloads ~68 MB of ephemeris data on first use. Give it a cache
    # directory of its own: the default is the current working directory, which
    # drops de421.bsp and hip_main.dat into whatever repository you happen to
    # be standing in.
    loader = Loader(str(_ephemeris_cache()), verbose=False)
    timescale = loader.timescale()
    ephemeris = loader("de421.bsp")
    moment = timescale.utc(year, month, day, hour - offset, minute, second)

    values = []
    for code, key in EPHEMERIS_KEYS.items():
        if code not in positions:
            continue
        _, longitude, _ = (
            ephemeris["earth"].at(moment).observe(ephemeris[key]).apparent().ecliptic_latlon()
        )
        values.append((longitude.degrees - positions[code]["sidereal"]) % 360)
    return sum(values) / len(values) if values else None


# ---------------------------------------------------------------------------


def compare(client: Client, collection: dict[str, Any]) -> Report:
    """Recompute the chart locally and report every disagreement."""
    site_ayanamsa, site = _site_positions(collection)
    if not site:
        raise CrossCheckUnavailable("нет данных этапа 01: сначала выполните сбор")

    chart = _local_chart(client)
    local_ayanamsa, local, bhava = _local_positions(chart)
    report = Report(site_ayanamsa=site_ayanamsa, local_ayanamsa=local_ayanamsa,
                    bhava_bala=bhava)

    # Both sources publish sidereal positions, so those are compared directly.
    # The ayanamsa is then checked separately, against the true ephemeris — a
    # source can publish correct positions and still declare the wrong
    # ayanamsa, and only this split tells the two apart.
    for code in ("As",) + CLASSICAL:
        here, there = site.get(code), local.get(code)
        if not here or not there:
            continue
        delta = _arcmin(there["sidereal"], here["sidereal"])
        status = (OK if abs(delta) < TOLERANCE_OK
                  else WARN if abs(delta) < TOLERANCE_WARN else CONFLICT)
        report.findings.append(Finding(
            subject=f"{code}: сидерическая долгота",
            status=status,
            site=_place(here), local=_place(there),
            note=f"{delta:+.2f}′"
                 + ("" if here["sign"] == there["sign"] else "; **знаки разные**"),
        ))

    report.implied_ayanamsa = implied_ayanamsa(client, site)
    for label, declared, positions in (("vedic-horo", site_ayanamsa, site),
                                       ("jyotishganit", local_ayanamsa, local)):
        actual = implied_ayanamsa(client, positions)
        if declared is None or actual is None:
            continue
        drift = abs(actual - declared) * 60
        report.findings.append(Finding(
            subject=f"Айанамша {label}: заявленная против фактической",
            status=OK if drift < TOLERANCE_OK else CONFLICT,
            site=f"{declared:.4f}° заявлено",
            local=f"{actual:.4f}° следует из положений",
            note="сходится" if drift < TOLERANCE_OK else
                 f"**расхождение {drift:.1f}′**: по заявленной айанамше положения "
                 "этого источника не воспроизводятся. Заявленное значение нельзя "
                 "переносить в отчёт как параметр расчёта",
        ))

    for code in ("Ra", "Ke"):
        here, there = site.get(code), local.get(code)
        if not here or not there:
            continue
        delta = _arcmin(there["sidereal"], here["sidereal"])
        report.findings.append(Finding(
            subject=f"{code}: тип узла",
            status=OK if abs(delta) < TOLERANCE_OK else WARN,
            site=_place(here), local=_place(there),
            note=f"{delta:+.1f}′ — средний против истинного узла, это разные точки, "
                 "а не ошибка. Выберите один и зафиксируйте."
                 if abs(delta) >= TOLERANCE_OK else "совпало",
        ))

    for code in ("As",) + CLASSICAL:
        here, there = site.get(code), local.get(code)
        if not here or not there or not here["nakshatra"] or not there["nakshatra"]:
            continue
        same = (_same_nakshatra(here["nakshatra"], there["nakshatra"])
                and here["pada"] == there["pada"])
        report.findings.append(Finding(
            subject=f"{code}: накшатра и пада",
            status=OK if same else CONFLICT,
            site=f"{here['nakshatra']} {here['pada']}",
            local=f"{there['nakshatra']} {there['pada']}",
            note="" if same else "**разные** — проверьте границу пады",
        ))

    site_sav = ((collection.get("show-info-D1") or {}).get("ashtakavarga") or {}).get("sav") or []
    local_sav_raw = (chart.get("ashtakavarga") or {}).get("sav") or {}
    if site_sav and local_sav_raw:
        first = ((collection.get("show-info-D1") or {})
                 .get("ashtakavarga") or {}).get("first_house_sign") or 1
        # The site indexes SAV by house; jyotishganit keys it by sign.
        local_sav = [local_sav_raw.get(SIGNS_EN[(first - 1 + house) % 12])
                     for house in range(12)]
        same = list(site_sav) == local_sav
        report.findings.append(Finding(
            subject="Аштакаварга: САВ по домам",
            status=OK if same else CONFLICT,
            site=", ".join(str(v) for v in site_sav),
            local=", ".join(str(v) for v in local_sav),
            note="" if same else "**расходится** — сравните с учётом того, что сайт "
                                 "индексирует по домам, а библиотека по знакам",
        ))

    if bhava:
        report.findings.append(Finding(
            subject="Бхава-бала",
            status=ADDED,
            site="сайт не считает",
            local=", ".join(f"{house}: {value / 60:.2f}" for house, value in
                            sorted(bhava.items())),
            note="в рупах. Сверить не с чем: реализации расходятся, "
                 "у PyJHora на этом расчёте открытый TODO",
        ))
    return report


def render(report: Report) -> str:
    """The comparison as a document for the reading's folder."""
    conflicts = report.conflicts
    lines = [
        "# Сверка с независимым расчётом",
        "",
        f"Источники: vedic-horo и jyotishganit (NASA JPL через skyfield). "
        f"Расхождений: **{len(conflicts)}**.",
        "",
        "Сравнение не выбирает победителя. Совпадение двух независимых расчётов "
        "поднимает доверие к числу; расхождение означает, что одному из них "
        "верить нельзя, и это надо выяснить, а не усреднить.",
        "",
        "| Что сверялось | Статус | vedic-horo | локальный расчёт | Комментарий |",
        "|---|---|---|---|---|",
    ]
    for finding in report.findings:
        lines.append(
            f"| {finding.subject} | {finding.status} | {finding.site} | "
            f"{finding.local} | {finding.note} |"
        )
    if conflicts:
        lines += ["", "## Требуют разбирательства", ""]
        lines += [f"- **{f.subject}**: {f.note or 'источники не сходятся'}"
                  for f in conflicts]
    return "\n".join(lines).rstrip() + "\n"
