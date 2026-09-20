"""The local backend, in the site's shapes — run where PyJHora is installed.

Without PyJHora these skip; the source policy and the cross-check wiring are
tested with a fake backend in the other files, so they run everywhere.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from jyotish import local
from jyotish.client import Client
from jyotish.local import _coord, _dms

needs_pyjhora = pytest.mark.skipif(not local.available(), reason="нет PyJHora")

CHART = {
    "slug": "t", "name": "T", "date": "20.03.1980", "time": "07:45:00",
    "timezone": "+3", "latitude": "54.25", "longitude": "42.50",
}


def test_site_coordinates_are_degrees_and_minutes() -> None:
    assert _coord("54.25") == pytest.approx(54 + 25 / 60)
    assert _coord("-33.52") == pytest.approx(-(33 + 52 / 60))


def test_dms_matches_the_sites_spelling() -> None:
    assert _dms(28.161667) == "28°09'42''"
    assert _dms(0.5) == "00°30'00''"


@needs_pyjhora
def test_positions_reproduce_the_first_charts_lagna(tmp_path: Path) -> None:
    """Aries 28°09′42″ on the site; the conventions in the module pin it."""
    backend = local.Backend(Client.from_dict(dict(CHART), tmp_path))
    lagna = next(p for p in backend.positions(1) if p.code == "As")
    assert lagna.sign == 0 and lagna.degree == pytest.approx(28.1617, abs=0.002)
    assert backend.ayanamsa == pytest.approx(23.5704, abs=0.001)


@needs_pyjhora
def test_hora_is_the_traditional_cancer_and_leo(tmp_path: Path) -> None:
    backend = local.Backend(Client.from_dict(dict(CHART), tmp_path))
    signs = {p["code"]: p["sign"] for p in backend.show_chart("D2")["planets"]}
    assert set(signs.values()) <= {"Cn", "Le"}


@needs_pyjhora
def test_show_chart_has_the_sites_shape(tmp_path: Path) -> None:
    backend = local.Backend(Client.from_dict(dict(CHART), tmp_path))
    chart = backend.show_chart("D9")
    assert chart["divisional"] == "D9" and chart["source"] == "local"
    assert [h["house"] for h in chart["houses"]] == list(range(1, 13))
    assert {p["code"] for p in chart["planets"]} == {"As", "Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "Ra", "Ke"}
    lagna = chart["houses"][0]
    assert any(p["code"] == "As" for p in lagna["planets"])


@needs_pyjhora
def test_ashtakavarga_is_indexed_by_house_and_sums_to_337(tmp_path: Path) -> None:
    backend = local.Backend(Client.from_dict(dict(CHART), tmp_path))
    bav, sav = backend.ashtakavarga()
    assert sum(sav) == 337 and len(sav) == 12
    assert set(bav) == {"Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "As"}
    assert sav == [27, 28, 42, 25, 21, 29, 23, 25, 30, 32, 34, 21]   # the site's row for this chart


@needs_pyjhora
def test_vimshottari_periods_are_contiguous_and_aged_like_the_site(tmp_path: Path) -> None:
    backend = local.Backend(Client.from_dict(dict(CHART), tmp_path))
    periods = backend.vimshottari(1)["periods"]
    assert [p["lords"] for p in periods] == [["Ve"], ["Su"], ["Mo"], ["Ma"], ["Ra"], ["Ju"], ["Sa"], ["Me"], ["Ke"]]
    for a, b in zip(periods, periods[1:]):
        assert a["end"] == b["start"]
    assert periods[0]["age"] is None and periods[1]["age"] == 4
    venus = datetime.fromisoformat(periods[1]["start"]) - datetime.fromisoformat(periods[0]["start"])
    assert venus.days == 7305                       # twenty sidereal years


@needs_pyjhora
def test_payload_covers_charts_and_dashas_only(tmp_path: Path) -> None:
    backend = local.Backend(Client.from_dict(dict(CHART), tmp_path))
    assert backend.payload("show-chart-D60")["divisional"] == "D60"
    assert backend.payload("show-dasha-vimshottari-2")["level"] == 2
    assert backend.payload("show-info-D1")["planets"][0]["code"] == "As"
    assert backend.payload("show-bala-D1") is None
    assert backend.payload("show-yogas-D1") is None
