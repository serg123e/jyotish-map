"""Local computation with PyJHora, shaped like the site's answers.

The pipeline reads one shape of data — the JSON ``vedic_parser`` makes of
vedic-horo's pages. This module produces the same shape from an ephemeris on
disk, so a block can come from either source and nothing downstream has to
know. Which source is *trusted* for which block is decided elsewhere, by the
cross-check, chart by chart.

Every convention that made the two sources disagree on the first chart is
pinned here, with the number it moved:

* **Ayanamsa: True Chitra.** Lahiri as swisseph defines it is 0.78′ off the
  site; True Chitrapaksha reproduces the site's own declared value to 0.16′
  and its planets to 0.01′. PyJHora cannot compute the true node under that
  mode (swisseph throws), so the value is taken at birth and applied as a
  user ayanamsa anchored there — identical for the natal chart, and for the
  minutes around it that ``sensitivity`` looks at.
* **Apparent positions.** PyJHora asks swisseph for geometric («true»)
  positions; the site reports apparent ones. The difference is 0.33′ on the
  Sun and Venus, and it is the site's convention that the reading was built
  on.
* **True nodes.** The site's Rahu is the true node (0.34′ from ours; the mean
  node is 89′ away).
* **Hora (D2): traditional Parashari** — Cancer and Leo only — which is
  PyJHora's method 2, not its default.
* **Ashtakavarga: the BPHS table.** PyJHora's table for the Moon and Venus
  departs from the classical one in four cells; the site (and jyotishganit)
  use the classical rows, which are restored here.

Shadbala is *not* reconciled: PyJHora and the site disagree on most
components by tens of virupas, and until the conventions are understood it
is reported by the cross-check and never substituted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .client import Client
from .derive import SIGN_CODES, SIGNS_EN

#: Bump whenever anything below changes how a number comes out — the
#: ayanamsa, the position flags, the node type, a chart method, the
#: Ashtakavarga table, the dasha year. The ledger of cross-check verdicts
#: is keyed by this: observations made by other arithmetic are not
#: evidence about this one.
CONVENTIONS_VERSION = 1

PLANET_CODES = ("Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "Ra", "Ke")
PLANET_NAMES = {
    "Su": "Sun", "Mo": "Moon", "Ma": "Mars", "Me": "Mercury", "Ju": "Jupiter",
    "Ve": "Venus", "Sa": "Saturn", "Ra": "Rahu", "Ke": "Ketu",
}

NAKSHATRAS = (
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu",
    "Pushya", "Ashlesha", "Magha", "Purvaphalguni", "Uttaraphalguni", "Hasta",
    "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purvashadha",
    "Uttarashadha", "Shravana", "Dhanishta", "Satabhisha", "Purvabhadra",
    "Uttarabhadra", "Revati",
)
NAKSHATRA_LORDS = ("Ke", "Ve", "Su", "Mo", "Ma", "Ra", "Ju", "Sa", "Me")

#: The site's day count for one dasha year — its 20 Venus years span exactly
#: 7305 days plus 3h04m, which is the sidereal year, not 365.25.
SIDEREAL_YEAR = 365.256364

#: PyJHora chart methods that reproduce the site. Everything else is its
#: default (1), which matched for D3…D60 on the first chart.
CHART_METHODS = {2: 2}

#: Brihat Parashara's Ashtakavarga rows for the Moon and Venus (contributor
#: order Sun…Saturn, Lagna); PyJHora ships four cells that differ.
BPHS_MOON = [[3, 6, 7, 8, 10, 11], [1, 3, 6, 7, 10, 11], [2, 3, 5, 6, 9, 10, 11],
             [1, 3, 4, 5, 7, 8, 10, 11], [1, 4, 7, 8, 10, 11, 12],
             [3, 4, 5, 7, 9, 10, 11], [3, 5, 6, 11], [3, 6, 10, 11]]
BPHS_VENUS = [[8, 11, 12], [1, 2, 3, 4, 5, 8, 9, 11, 12], [3, 5, 6, 9, 11, 12],
              [3, 5, 6, 9, 11], [5, 8, 9, 10, 11], [1, 2, 3, 4, 5, 8, 9, 10, 11],
              [3, 4, 5, 8, 9, 10, 11], [1, 2, 3, 4, 5, 8, 9, 11]]


class LocalUnavailable(RuntimeError):
    """PyJHora (and its Swiss Ephemeris) is not installed."""


def available() -> bool:
    try:
        import jhora  # noqa: F401
        import swisseph  # noqa: F401
    except ImportError:
        return False
    return True


def _coord(value: str) -> float:
    """The site's degrees.minutes form to decimal degrees: 55.45 -> 55.75."""
    degrees, _, minutes = str(value).partition(".")
    sign = -1 if degrees.strip().startswith("-") else 1
    return sign * (abs(int(degrees)) + int((minutes or "0").ljust(2, "0")[:2]) / 60)


@dataclass(frozen=True)
class Position:
    code: str
    sign: int            # 0–11
    degree: float        # within the sign

    @property
    def longitude(self) -> float:
        return self.sign * 30 + self.degree


class Backend:
    """One chart, computed locally, with the conventions above applied."""

    def __init__(self, client: Client) -> None:
        if not available():
            raise LocalUnavailable(
                "нет PyJHora — локальный расчёт недоступен. "
                "Поставьте: pip install 'jyotish-map[local]'")
        import swisseph as swe
        from jhora import const, utils
        from jhora.panchanga import drik

        self._swe, self._const, self._utils, self._drik = swe, const, utils, drik
        chart = client.chart
        day, month, year = (int(p) for p in chart.date.split("."))
        hour, minute, second = (int(p) for p in chart.time.split(":"))
        self.timezone = float(chart.timezone)
        self.place = drik.Place(chart.name or client.slug, _coord(chart.latitude),
                                _coord(chart.longitude), self.timezone)
        self.jd = utils.julian_day_number((year, month, day), (hour, minute, second))
        self.jd_utc = self.jd - self.timezone / 24
        self.birth = datetime(year, month, day, hour, minute, second)
        self.true_nodes = client.nodes != "mean"
        self._configure()

    # ---- conventions -------------------------------------------------------

    def _configure(self) -> None:
        """Pin every global PyJHora reads. Called before each computation:
        the library keeps its settings in module state, and another Backend
        may have changed them in between."""
        swe, const, drik = self._swe, self._const, self._drik
        swe.set_ephe_path(os.path.join(os.path.dirname(const.__file__), "data", "ephe"))
        # True Chitra, anchored at birth as a user ayanamsa (see module doc).
        swe.set_sid_mode(swe.SIDM_TRUE_CITRA)
        self.ayanamsa = swe.get_ayanamsa_ut(self.jd_utc)
        drik.set_ayanamsa_mode("SIDM_USER", ayanamsa_value=self.ayanamsa, jd=self.jd_utc)
        # Apparent positions, as the site reports them.
        drik.PLANET_FLAGS = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED
        drik.set_planet_list(set_rahu_ketu_as_true_nodes=self.true_nodes)
        table = dict(const.ashtaka_varga_dict)
        table["1"], table["5"] = BPHS_MOON, BPHS_VENUS
        const.ashtaka_varga_dict = table

    # ---- positions ---------------------------------------------------------

    def positions(self, varga: int = 1) -> list[Position]:
        """Ascendant first, then the nine bodies, in the given varga."""
        from jhora.horoscope.chart import charts

        self._configure()
        rows = charts.divisional_chart(self.jd, self.place, divisional_chart_factor=varga,
                                       chart_method=CHART_METHODS.get(varga, 1))
        out = []
        for planet, (sign, degree) in rows:
            code = "As" if planet == "L" else PLANET_CODES[planet]
            out.append(Position(code, int(sign), float(degree)))
        return out

    def retrograde(self) -> set[str]:
        self._configure()
        return {PLANET_CODES[p] for p in self._drik.planets_in_retrograde(self.jd, self.place)}

    def ascendant_longitude(self) -> float:
        self._configure()
        sign, degree, _, _ = self._drik.ascendant(self.jd, self.place)
        return sign * 30 + degree

    # ---- the site's shapes -------------------------------------------------

    def show_chart(self, varga: str) -> dict[str, Any]:
        """``show-chart-<varga>`` as vedic_parser returns it."""
        factor = int(varga[1:])
        positions = self.positions(factor)
        retro = self.retrograde()
        lagna = next(p for p in positions if p.code == "As")
        houses = []
        for house in range(1, 13):
            sign = (lagna.sign + house - 1) % 12
            houses.append({
                "house": house,
                "sign": {"number": sign + 1, "code": SIGN_CODES[sign], "name": SIGNS_EN[sign]},
                "planets": [
                    {"code": p.code, "degree": int(p.degree), "degree_label": f"{int(p.degree)}°",
                     "retrograde": p.code in retro}
                    for p in positions if p.sign == sign
                ],
                "aspects": [],
            })
        planets = [
            {"code": p.code, "house": (p.sign - lagna.sign) % 12 + 1, "sign": SIGN_CODES[p.sign],
             "sign_number": p.sign + 1, "degree": int(p.degree), "retrograde": p.code in retro}
            for p in positions
        ]
        return {"style": "north", "divisional": varga, "source": "local",
                "houses": houses, "planets": planets}

    def show_info_d1(self) -> dict[str, Any]:
        """``show-info-D1`` — the positional columns only.

        Dignities, functional status, strengths, aspects and the site's
        special marks are not computed here; the keys are present and empty
        so a reader sees a gap, not a different table.
        """
        positions = self.positions(1)
        navamsa = {p.code: p for p in self.positions(9)}
        retro = self.retrograde()
        lagna = next(p for p in positions if p.code == "As")
        bav, sav = self.ashtakavarga()
        planets = []
        for p in positions:
            nak, pada, _ = self._drik.nakshatra_pada(p.longitude)
            house = None if p.code == "As" else (p.sign - lagna.sign) % 12 + 1
            planets.append({
                "code": p.code, "name": "Ascendant" if p.code == "As" else PLANET_NAMES[p.code],
                "retrograde": p.code in retro, "karaka": None,
                "degrees": _dms(p.degree), "degrees_decimal": round(p.degree, 6),
                "rasi": {"code": SIGN_CODES[p.sign], "name": SIGNS_EN[p.sign], "dignity": None},
                "navamsa": SIGNS_EN[navamsa[p.code].sign],
                "nakshatra": {"code": None, "name": NAKSHATRAS[nak - 1], "pada": pada,
                              "lord": NAKSHATRA_LORDS[(nak - 1) % 9]},
                "relationship": None, "house": house, "lords": [],
                "functional_beneficence": None, "natural_beneficence": None,
                "shad_bala": None,
                "bindu": {"sav": sav[(p.sign - lagna.sign) % 12] if sav else None,
                          "bav": bav.get(p.code, [None] * 12)[(p.sign - lagna.sign) % 12] if bav else None},
                "position": [], "planetary_war": None,
            })
        return {
            "divisional": "D1", "from": None, "source": "local", "planets": planets,
            "ashtakavarga": {"first_house_sign": lagna.sign + 1, "sav": sav, "bav": bav},
        }

    def ashtakavarga(self) -> tuple[dict[str, list[int]], list[int]]:
        """BAV per planet (and the lagna) and SAV, both **by house from the
        lagna** as the site indexes them, not by sign."""
        from jhora.horoscope.chart import ashtakavarga, charts

        self._configure()
        rasi = charts.rasi_chart(self.jd, self.place)
        lagna_sign = int(rasi[0][1][0])
        h2p = self._utils.get_house_planet_list_from_planet_positions(rasi)
        bav_by_sign, sav_by_sign, _ = ashtakavarga.get_ashtaka_varga(h2p)

        def by_house(values: list[int]) -> list[int]:
            return [int(values[(lagna_sign + house) % 12]) for house in range(12)]

        bav = {code: by_house(bav_by_sign[i]) for i, code in enumerate(PLANET_CODES[:7])}
        bav["As"] = by_house(bav_by_sign[7])
        return bav, by_house(sav_by_sign)

    def vimshottari(self, level: int = 1) -> dict[str, Any]:
        """``show-dasha-vimshottari-<level>`` as vedic_parser returns it."""
        from jhora.horoscope.dhasa.graha import vimsottari

        self._configure()
        _, rows = vimsottari.get_vimsottari_dhasa_bhukthi(
            self.jd, self.place, dhasa_level_index=level,
            dhasa_duration_type=self._const.DHASA_YEAR_DURATION.MEAN_SIDEREAL_YEAR)
        starts = []
        for lords, (year, month, day, hours), duration in rows:
            start = datetime(year, month, day) + timedelta(hours=hours)
            starts.append((tuple(PLANET_CODES[l] for l in lords), start, float(duration)))
        periods = []
        for index, (lords, start, duration) in enumerate(starts):
            end = (starts[index + 1][1] if index + 1 < len(starts)
                   else start + timedelta(days=duration * SIDEREAL_YEAR))
            # The site prints no age for a period that starts in the first
            # year of life, not «0».
            years = (start - self.birth).days / 365.25 if start >= self.birth else -1
            age = int(years) if years >= 1 else None
            periods.append({
                "start": start.strftime("%Y-%m-%dT%H:%M"), "end": end.strftime("%Y-%m-%dT%H:%M"),
                "lords": list(lords), "labels": [PLANET_NAMES[l] for l in lords],
                "start_label": start.strftime("%d %b %Y"), "start_time": start.strftime("%H:%M"),
                "age": age,
            })
        return {"kind": "planet", "level": level, "periods": periods,
                "dasha": "vimshottari", "divisional": "D1", "source": "local"}

    def shadbala(self) -> dict[str, dict[str, float]]:
        """Virupas per component, for the cross-check only (see module doc)."""
        from jhora.horoscope.chart import strength

        self._configure()
        parts = strength.shad_bala(self.jd, self.place)
        names = ("sthana_bala", "kala_bala", "dig_bala", "cheshta_bala",
                 "naisargika_bala", "drik_bala", "shad_bala")
        return {code: {name: float(parts[i][p]) for i, name in enumerate(names)}
                for p, code in enumerate(PLANET_CODES[:7])}

    def payload(self, key: str) -> dict[str, Any] | None:
        """The block for a collection key, or None if this backend has no
        local equivalent for it."""
        if key.startswith("show-chart-D"):
            return self.show_chart(key.removeprefix("show-chart-"))
        if key == "show-info-D1":
            return self.show_info_d1()
        if key.startswith("show-dasha-vimshottari-"):
            level = key.removeprefix("show-dasha-vimshottari-").split("-")[0]
            if level.isdigit():
                return self.vimshottari(int(level))
        return None


def _dms(degree: float) -> str:
    total = round(degree * 3600)
    d, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{d:02d}°{m:02d}'{s:02d}''"


#: Keys this backend can produce. The cross-check decides, per chart, which
#: of them it may *replace* the site for.
LOCAL_KEYS = ("show-chart-", "show-info-D1", "show-dasha-vimshottari-")
