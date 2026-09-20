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

Two local sources take part when installed. **PyJHora** (Swiss Ephemeris) is
the one that can replace the site block by block: with the conventions pinned
in :mod:`jyotish.local` it reproduces the site's positions to 0.01′, every
varga's signs, the Ashtakavarga and the Vimshottari lords, so the report says
per block whether it agrees to tolerance, and ``state/crosscheck.json`` records
that verdict for ``collect --source auto``. **jyotishganit** stays as the
third, independent ephemeris for the ayanamsa check. Without either installed
the cross-check reports itself as unavailable and nothing else changes.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .client import Client
from . import local as local_module
from .derive import SIGNS_EN

#: How jyotishganit names the bodies, mapped to the site's codes.
BODY_CODES = {
    "Sun": "Su", "Moon": "Mo", "Mars": "Ma", "Mercury": "Me", "Jupiter": "Ju",
    "Venus": "Ve", "Saturn": "Sa", "Rahu": "Ra", "Ketu": "Ke",
    "North Node": "Ra", "South Node": "Ke",
}

NODE_NAMES = {"mean": "средний", "true": "истинный"}

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

#: Hours a dasha boundary may differ and still count as the same boundary. The
#: Vimshottari start is absurdly sensitive to the Moon: 3″ of longitude move
#: it by twelve hours, while one minute of birth time moves it by five days.
#: A boundary that agrees to a day agrees as well as the birth time allows.
DASHA_TOLERANCE_HOURS = 24.0

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
    #: Which local sources took part, for the heading.
    sources: list[str] = field(default_factory=list)
    #: Collection keys the PyJHora backend reproduced, and how well:
    #: OK means ``collect --source auto`` may take that block locally.
    verified: dict[str, str] = field(default_factory=dict)

    @property
    def conflicts(self) -> list[Finding]:
        return [f for f in self.findings if f.conflicting]

    @property
    def replaceable(self) -> list[str]:
        return sorted(key for key, status in self.verified.items() if status == OK)


def available() -> bool:
    """Whether any local source is installed."""
    return local_module.available() or _jyotishganit_available()


def _jyotishganit_available() -> bool:
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


def tropical_longitudes(ephemeris: Any, moment: Any) -> dict[str, float]:
    """True tropical longitudes of the classical bodies, **in the ecliptic of date**.

    The epoch is the whole point. Skyfield's ``ecliptic_latlon()`` defaults to
    the J2000 ecliptic, while an ayanamsa is by definition measured from the
    equinox *of date*. Omitting the epoch therefore adds the precession
    accumulated between the chart and J2000 — 0.2765° for a 1980 chart, 16.6′,
    which is squarely inside the range of a real ayanamsa dispute.

    That is not a hypothetical: this module was written without the epoch and
    duly reported that vedic-horo declared an ayanamsa 16.7′ away from its own
    positions. The site was right and the checker was wrong. A cross-check that
    manufactures conflicts is worse than no cross-check, so the epoch is passed
    explicitly here and asserted in the tests.
    """
    observer = ephemeris["earth"].at(moment)
    longitudes: dict[str, float] = {}
    for code, key in EPHEMERIS_KEYS.items():
        _, longitude, _ = (
            observer.observe(ephemeris[key]).apparent().ecliptic_latlon(epoch=moment)
        )
        longitudes[code] = longitude.degrees
    return longitudes


def _ephemeris_for(client: Client) -> tuple[Any, Any] | None:
    """Skyfield's ephemeris and the chart's moment, or None when unavailable."""
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
    ephemeris = loader("de421.bsp")
    moment = loader.timescale().utc(year, month, day, hour - offset, minute, second)
    return ephemeris, moment


def ayanamsa_from(
    longitudes: dict[str, float], positions: dict[str, dict[str, Any]]
) -> float | None:
    """The ayanamsa a set of sidereal positions implies, given true longitudes.

    (tropical of date − reported sidereal), averaged over the bodies both
    sides have. Split out from the ephemeris lookup so it can be tested
    without downloading 68 MB.
    """
    values = [
        (longitudes[code] - positions[code]["sidereal"]) % 360
        for code in longitudes
        if code in positions
    ]
    return sum(values) / len(values) if values else None


def implied_ayanamsa(client: Client, positions: dict[str, dict[str, Any]]) -> float | None:
    """The ayanamsa a set of sidereal positions actually implies.

    This is what would catch a source whose stated ayanamsa disagrees with its
    own numbers.
    """
    loaded = _ephemeris_for(client)
    if loaded is None:
        return None
    return ayanamsa_from(tropical_longitudes(*loaded), positions)


# ---------------------------------------------------------------------------


def compare(client: Client, collection: dict[str, Any]) -> Report:
    """Recompute the chart locally and report every disagreement."""
    site_ayanamsa, site = _site_positions(collection)
    if not site:
        raise CrossCheckUnavailable("нет данных этапа 01: сначала выполните сбор")
    if not available():
        raise CrossCheckUnavailable(
            "нет ни PyJHora, ни jyotishganit — второй источник недоступен. "
            "Поставьте: pip install 'jyotish-map[local]' (или [crosscheck])")

    report = Report(site_ayanamsa=site_ayanamsa)
    if local_module.available():
        report.sources.append("PyJHora (Swiss Ephemeris)")
        _compare_pyjhora(report, client, collection, site)
    if _jyotishganit_available():
        report.sources.append("jyotishganit (NASA JPL через skyfield)")
        _compare_jyotishganit(report, client, collection, site)
    return report


def _compare_jyotishganit(report: Report, client: Client, collection: dict[str, Any],
                          site: dict[str, dict[str, Any]]) -> None:
    """The original check: positions, nakshatras, SAV, and the ayanamsa test."""
    site_ayanamsa = report.site_ayanamsa
    chart = _local_chart(client)
    local_ayanamsa, local, bhava = _local_positions(chart)
    report.local_ayanamsa, report.bhava_bala = local_ayanamsa, bhava

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

    # One ephemeris load for both sources: opening de421.bsp and observing
    # seven bodies three times over gives the same answer three times slower.
    loaded = _ephemeris_for(client)
    true_longitudes = tropical_longitudes(*loaded) if loaded else {}
    report.implied_ayanamsa = ayanamsa_from(true_longitudes, site)
    for label, declared, positions in (("vedic-horo", site_ayanamsa, site),
                                       ("jyotishganit", local_ayanamsa, local)):
        actual = ayanamsa_from(true_longitudes, positions)
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

    _explain_ascendant(report, site, local, true_longitudes)

    for code in ("Ra", "Ke"):
        here, there = site.get(code), local.get(code)
        if not here or not there:
            continue
        delta = _arcmin(there["sidereal"], here["sidereal"])
        if abs(delta) < TOLERANCE_OK:
            status, note = OK, "совпало"
        elif client.nodes:
            # Two node types are two points; once chart.yaml says which one
            # the site uses, the difference is a setting, not a question.
            status = OK
            note = (f"{delta:+.1f}′ — сайт считает {NODE_NAMES[client.nodes]} узел "
                    "(зафиксировано в chart.yaml: nodes), библиотека — другой тип. "
                    "Разные точки, не ошибка.")
        else:
            status = WARN
            note = (f"{delta:+.1f}′ — средний против истинного узла, это разные точки, "
                    "а не ошибка. Определите, какой считает сайт, и запишите в "
                    "chart.yaml: `nodes: mean` или `nodes: true`.")
        report.findings.append(Finding(
            subject=f"{code}: тип узла", status=status,
            site=_place(here), local=_place(there), note=note,
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


# ---------------------------------------------------------------------------
# PyJHora: block by block, so a block can be taken locally once it agrees
# ---------------------------------------------------------------------------


def _compare_pyjhora(report: Report, client: Client, collection: dict[str, Any],
                     site: dict[str, dict[str, Any]]) -> None:
    backend = local_module.Backend(client)
    _pyjhora_ayanamsa(report, backend)
    _pyjhora_positions(report, backend, site)
    _pyjhora_vargas(report, backend, collection)
    _pyjhora_ashtakavarga(report, backend, collection)
    _pyjhora_dashas(report, backend, collection)
    _pyjhora_shadbala(report, backend, collection)


def _pyjhora_ayanamsa(report: Report, backend: Any) -> None:
    if report.site_ayanamsa is None:
        return
    drift = abs(backend.ayanamsa - report.site_ayanamsa) * 60
    report.findings.append(Finding(
        subject="Айанамша: заявленная сайтом против True Chitra",
        status=OK if drift < TOLERANCE_OK else CONFLICT,
        site=f"{report.site_ayanamsa:.4f}°", local=f"{backend.ayanamsa:.4f}° (PyJHora, True Chitra)",
        note=f"{drift:.2f}′" + ("" if drift < TOLERANCE_OK else
                                " — **не тот вариант айанамши**; см. jyotish.local"),
    ))


def _pyjhora_positions(report: Report, backend: Any, site: dict[str, dict[str, Any]]) -> None:
    local = {p.code: p for p in backend.positions(1)}
    worst = 0.0
    for code in ("As",) + CLASSICAL + ("Ra", "Ke"):
        here, there = site.get(code), local.get(code)
        if not here or not there:
            continue
        delta = _arcmin(there.longitude, here["sidereal"])
        worst = max(worst, abs(delta))
        report.findings.append(Finding(
            subject=f"{code}: долгота (PyJHora)",
            status=OK if abs(delta) < TOLERANCE_OK else WARN if abs(delta) < TOLERANCE_WARN else CONFLICT,
            site=_place(here),
            local=f"{SIGNS_EN[there.sign]} {there.degree:.3f}°",
            note=f"{delta:+.2f}′" + ("" if SIGNS_EN[there.sign] == here["sign"] else "; **знаки разные**"),
        ))
    report.verified["show-info-D1:positions"] = OK if worst < TOLERANCE_OK else CONFLICT


def _pyjhora_vargas(report: Report, backend: Any, collection: dict[str, Any]) -> None:
    for key in sorted(k for k in collection if k.startswith("show-chart-D")):
        varga = key.removeprefix("show-chart-")
        site_signs = {p["code"]: p["sign"] for p in (collection[key] or {}).get("planets", [])}
        if not site_signs:
            continue
        local_signs = {p["code"]: p["sign"] for p in backend.show_chart(varga)["planets"]}
        differ = {c: (site_signs[c], local_signs.get(c)) for c in site_signs
                  if site_signs[c] != local_signs.get(c)}
        status = OK if not differ else CONFLICT
        report.verified[key] = status
        report.findings.append(Finding(
            subject=f"{varga}: знаки всех тел",
            status=status,
            site="совпали все десять" if not differ else ", ".join(f"{c} {s}" for c, (s, _) in differ.items()),
            local="" if not differ else ", ".join(f"{c} {l}" for c, (_, l) in differ.items()),
            note="" if not differ else "**расходится** — другой способ деления варги; "
                                      "см. CHART_METHODS в jyotish.local",
        ))


def _pyjhora_ashtakavarga(report: Report, backend: Any, collection: dict[str, Any]) -> None:
    site_av = (collection.get("show-info-D1") or {}).get("ashtakavarga") or {}
    if not site_av.get("sav"):
        return
    bav, sav = backend.ashtakavarga()
    sav_same = list(site_av["sav"]) == sav
    bav_differ = [code for code, rows in (site_av.get("bav") or {}).items()
                  if code in bav and list(rows) != bav[code]]
    status = OK if sav_same and not bav_differ else CONFLICT
    report.verified["ashtakavarga"] = status
    report.findings.append(Finding(
        subject="Аштакаварга: САВ и все БАВ (PyJHora, таблица BPHS)",
        status=status,
        site=", ".join(str(v) for v in site_av["sav"]),
        local=", ".join(str(v) for v in sav),
        note="совпали САВ и восемь БАВ" if status == OK else
             f"**расходится**: БАВ {', '.join(bav_differ) or 'сходятся'}, "
             f"САВ {'сходится' if sav_same else 'нет'}",
    ))


def _pyjhora_dashas(report: Report, backend: Any, collection: dict[str, Any]) -> None:
    for level in (1, 2):
        key = f"show-dasha-vimshottari-{level}"
        site_periods = (collection.get(key) or {}).get("periods") or []
        if not site_periods:
            continue
        local_periods = backend.vimshottari(level)["periods"]
        same_lords = [p["lords"] for p in site_periods] == [p["lords"] for p in local_periods]
        worst = 0.0
        for here, there in zip(site_periods, local_periods):
            delta = (datetime.fromisoformat(there["start"]) - datetime.fromisoformat(here["start"]))
            worst = max(worst, abs(delta.total_seconds()) / 3600)
        status = OK if same_lords and worst <= DASHA_TOLERANCE_HOURS else CONFLICT
        report.verified[key] = status
        report.findings.append(Finding(
            subject=f"Вимшоттари, уровень {level}: границы {len(site_periods)} периодов",
            status=status,
            site=site_periods[0]["start"], local=local_periods[0]["start"],
            note=(f"порядок управителей {'совпал' if same_lords else '**разный**'}; "
                  f"границы расходятся не больше чем на {worst:.1f} ч"
                  + ("" if worst <= DASHA_TOLERANCE_HOURS else " — **больше суток**")
                  + ". Двенадцать часов здесь — три угловые секунды Луны; минута "
                    "времени рождения сдвигает те же границы на пять суток."),
        ))


def _pyjhora_shadbala(report: Report, backend: Any, collection: dict[str, Any]) -> None:
    site_rows = (collection.get("show-bala-D1") or {}).get("shad_bala") or []
    if not site_rows:
        return
    local = backend.shadbala()
    for row in site_rows:
        code = row.get("code")
        if code not in local:
            continue
        components = row.get("components") or {}
        parts = []
        worst_pct = 0.0
        for name in ("sthana_bala", "kala_bala", "dig_bala", "cheshta_bala", "drik_bala", "shad_bala"):
            here = (components.get(name) or {}).get("virupas")
            there = local[code].get(name)
            if here is None or there is None:
                continue
            gap = there - here
            if name == "shad_bala" and here:
                worst_pct = abs(gap) / abs(here) * 100
            parts.append(f"{name.removesuffix('_bala')} {here:.0f}/{there:.0f}")
        report.findings.append(Finding(
            subject=f"Шадбала {code}: сайт/PyJHora, вирупы",
            status=OK if worst_pct < 5 else WARN,
            site=f"{(components.get('shad_bala') or {}).get('virupas')}",
            local=f"{local[code].get('shad_bala'):.2f}",
            note="; ".join(parts) + (
                "" if worst_pct < 5 else
                f" — итог расходится на {worst_pct:.0f}%: **соглашения расчёта не сведены**, "
                "локальная Шадбала не подставляется"),
        ))
    report.verified["show-bala-D1"] = WARN


def verified_path(client: Client) -> Path:
    return client.state_dir / "crosscheck.json"


def write_verified(client: Client, report: Report) -> Path:
    """Record, per block, whether the local computation may stand in for the site."""
    client.ensure_dirs()
    path = verified_path(client)
    path.write_text(json.dumps({
        "checked": datetime.now().isoformat(timespec="minutes"),
        "sources": report.sources,
        "local": report.verified,
        "replaceable": report.replaceable,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_verified(client: Client) -> dict[str, str]:
    path = verified_path(client)
    if not path.exists():
        return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")).get("local") or {})
    except (json.JSONDecodeError, AttributeError):
        return {}


def _explain_ascendant(report: Report, site: dict[str, Any], local: dict[str, Any],
                       true_longitudes: dict[str, float]) -> None:
    """Attribute a lagna disagreement to the library's ayanamsa slip when it fits.

    jyotishganit declares an ayanamsa that does not reproduce its own planets
    (a J2000-versus-date slip of the kind our own check once made), and its
    ascendant is offset from the site's by that same amount: the tropical
    lagna is reduced by the declared value, the planets by the actual one.
    When the two numbers agree to within the noise, the finding says so —
    otherwise every reading re-opens the same question.
    """
    finding = next((f for f in report.findings if f.subject == "As: сидерическая долгота"), None)
    if finding is None or finding.status == OK:
        return
    declared, actual = report.local_ayanamsa, ayanamsa_from(true_longitudes, local)
    if declared is None or actual is None:
        return
    slip = (declared - actual) * 60
    delta = _arcmin(local["As"]["sidereal"], site["As"]["sidereal"])
    if abs(delta + slip) < TOLERANCE_OK:
        finding.status = OK
        finding.note += (f" — объяснено: равно ошибке заявленной айанамши jyotishganit "
                         f"({slip:+.1f}′); библиотека вычитает из тропической Лагны "
                         "заявленное значение, а из планет — фактическое. Лагна сайта верна.")


def render(report: Report) -> str:
    """The comparison as a document for the reading's folder."""
    conflicts = report.conflicts
    lines = [
        "# Сверка с независимым расчётом",
        "",
        f"Источники: vedic-horo и {', '.join(report.sources) or 'локальный расчёт'}. "
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
    if report.verified:
        lines += ["", "## Что можно считать локально для этой карты", ""]
        for key, status in sorted(report.verified.items()):
            verdict = ("совпало с сайтом — `collect --source auto` возьмёт локально"
                       if status == OK else
                       "остаётся за сайтом" + (" (соглашения не сведены)" if status == WARN else " (расходится)"))
            lines.append(f"- `{key}`: {verdict}")
    return "\n".join(lines).rstrip() + "\n"
