"""Sensitivity to the birth time is read off the site's answers, never computed.

The fake site below is deterministic: the D60 ascendant changes sign at +2
minutes, the Moon changes its D60 sign at -3, D1 never moves, and every
dasha boundary slides 5.5 days earlier per minute of later birth.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from jyotish import collect as collect_module
from jyotish import sensitivity
from jyotish.client import Client
from jyotish.sensitivity import (
    Change,
    NotCollected,
    analyse,
    build_offset_plan,
    offset_client,
    offset_label,
    offsets,
    render,
    run,
    shifted_chart,
    stable_span,
)
from vedic_parser import Chart

CHART = {
    "slug": "t", "date": "07.08.1983", "time": "23:00:00", "timezone": "+4",
    "latitude": "55.45", "longitude": "37.37",
    "collect": {"vargas": ["D1", "D9", "D60"]},
}
BASE = datetime(1983, 8, 7, 23, 0)
DAYS_PER_MINUTE = -5.5


def _minutes(chart: Chart) -> int:
    moment = datetime.strptime(f"{chart.date} {chart.time}", "%d.%m.%Y %H:%M:%S")
    return round((moment - BASE).total_seconds() / 60)


def _house(number: int, sign: str, *planets: str) -> dict:
    return {"house": number, "sign": {"code": sign}, "planets": [{"code": p} for p in planets]}


def fake_show_chart(session, chart, divisional="D1", **_):
    m = _minutes(chart)
    if divisional == "D1":
        asc = "Ta" if 28.16 + 0.45 * m >= 30 else "Ar"
        return {"houses": [_house(1, asc, "As", "Mo"), _house(5, "Le", "Su")]}
    if divisional == "D9":
        return {"houses": [_house(1, "Sg", "As"), _house(12, "Sc", "Mo"), _house(9, "Le", "Su")]}
    # D60: the ascendant crosses into Capricorn at +2, the Moon into Aries at -3.
    asc = "Cp" if m >= 2 else "Sg"
    moon = "Ar" if m <= -3 else "Pi"
    return {"houses": [_house(1, asc, "As"), _house(4, moon, "Mo"), _house(9, "Le", "Su")]}


def fake_show_info(session, chart, divisional="D1", **_):
    # 28.16° Aries at the base; +5 minutes carries it into Taurus at 0.41°.
    longitude = 28.16 + 0.45 * _minutes(chart)
    return {"planets": [{"code": "As", "degrees_decimal": round(longitude % 30, 2)}]}


def fake_show_dasha(session, chart, dasha="vimshottari", level=1, **_):
    slide = timedelta(days=DAYS_PER_MINUTE * _minutes(chart))
    starts = {"Ve": datetime(1964, 5, 2, 5, 27), "Su": datetime(1984, 5, 2, 8, 31),
              "Mo": datetime(1990, 5, 2, 21, 27)}
    return {"periods": [
        {"lords": [lord], "start": (start + slide).isoformat(timespec="minutes")}
        for lord, start in starts.items()
    ]}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch) -> Client:
    client = Client.from_dict(dict(CHART), tmp_path)
    client.ensure_dirs()
    # The base collection is what `jyotish collect` would have left behind.
    base = Chart("t", CHART["date"], CHART["time"], "+4", "55.45", "37.37")
    for varga in ("D1", "D9", "D60"):
        (client.raw_dir / f"show-chart-{varga}.json").write_text(
            json.dumps(fake_show_chart(None, base, varga)), encoding="utf-8")
    (client.raw_dir / "show-info-D1.json").write_text(
        json.dumps(fake_show_info(None, base)), encoding="utf-8")
    (client.raw_dir / "show-dasha-vimshottari-1.json").write_text(
        json.dumps(fake_show_dasha(None, base)), encoding="utf-8")
    monkeypatch.setattr(collect_module, "_load_api", lambda: {
        "show_chart": fake_show_chart, "show_info": fake_show_info,
        "show_dasha": fake_show_dasha,
    })
    monkeypatch.setattr(collect_module, "_ensure_session", lambda c, s, t: (object(), 0.0))
    return client


# ---- shifting the chart -----------------------------------------------------


def test_shift_moves_the_time_and_keeps_everything_else() -> None:
    chart = Chart("t", "07.08.1983", "23:00:00", "+4", "55.45", "37.37")
    moved = shifted_chart(chart, -3)
    assert (moved.date, moved.time) == ("07.08.1983", "22:57:00")
    assert (moved.timezone, moved.latitude, moved.longitude) == ("+4", "55.45", "37.37")


def test_shift_across_midnight_moves_the_date() -> None:
    chart = Chart("t", "07.08.1983", "23:59:00", "+4", "55.45", "37.37")
    assert shifted_chart(chart, 2).date == "08.08.1983"
    assert shifted_chart(chart, 2).time == "00:01:00"
    early = Chart("t", "01.01.1990", "00:00:30", "+3", "55.45", "37.37")
    assert (shifted_chart(early, -1).date, shifted_chart(early, -1).time) == \
        ("31.12.1989", "23:59:30")


def test_offsets_skip_zero_and_honour_the_step() -> None:
    assert offsets(3) == [-3, -2, -1, 1, 2, 3]
    assert offsets(4, 2) == [-4, -2, 2, 4]
    with pytest.raises(ValueError):
        offsets(0)


def test_offset_labels_sort_as_numbers_and_read_as_signs() -> None:
    assert [offset_label(m) for m in (-10, -1, 1, 10)] == ["-10", "-01", "+01", "+10"]


def test_each_offset_has_its_own_cache(tmp_path: Path) -> None:
    client = Client.from_dict(dict(CHART), tmp_path)
    shifted = offset_client(client, 2)
    assert shifted.raw_dir == tmp_path / "sensitivity" / "+02" / "raw"
    assert shifted.chart.time == "23:02:00"
    assert client.chart.time == "23:00:00"          # the original is untouched


def test_the_plan_reads_signs_from_show_chart_not_show_info() -> None:
    """show-info's rasi column is the natal sign in every varga."""
    keys = [r.key for r in build_offset_plan(("D1", "D60"))]
    assert "show-chart-D60" in keys and "show-info-D60" not in keys
    assert "show-info-D1" in keys and "show-dasha-vimshottari-1" in keys


# ---- the arithmetic on the answers -----------------------------------------


def test_stable_span_is_contiguous_around_zero() -> None:
    assert stable_span({-3: "Sg", -2: "Sg", -1: "Sg", 0: "Sg", 1: "Sg", 2: "Cp", 3: "Cp"}) == (-3, 1)
    assert stable_span({-2: "Ar", -1: "Ta", 0: "Ta", 1: "Ta", 2: "Ta"}) == (-1, 2)
    assert stable_span({0: "Ta"}) == (0, 0)


def test_an_uncollected_offset_does_not_count_as_stable() -> None:
    assert stable_span({-2: "Sg", 0: "Sg", 1: "Sg", 3: "Sg"}) == (0, 1)
    assert stable_span({-1: None, 0: "Sg", 1: "Sg"}) == (0, 1)


def test_a_missing_base_refuses(tmp_path: Path) -> None:
    client = Client.from_dict(dict(CHART), tmp_path)
    with pytest.raises(NotCollected):
        analyse(client, {1: {}}, ("D1",), window=1)
    with pytest.raises(NotCollected, match="jyotish collect"):
        run(client, window=1)


# ---- the whole thing, against the fake site --------------------------------


def test_the_report_finds_the_d60_boundaries(client: Client) -> None:
    report = run(client, window=3)
    assert report.collected_offsets == [-3, -2, -1, 0, 1, 2, 3]
    assert report.stable["D1"] == (-3, 3) and report.whole_window("D1")
    assert report.ascendant_rate() == pytest.approx(0.45, abs=0.01)
    assert report.stable["D9"] == (-3, 3)
    # Ascendant holds until +1, the Moon until -2: the intersection is (-2, 1).
    assert report.stable["D60"] == (-2, 1)
    assert Change("D60", "As", 2, "Sg", "Cp") in report.changes
    assert Change("D60", "Mo", -3, "Pi", "Ar") in report.changes
    assert not any(c.varga == "D1" for c in report.changes)


def test_the_slide_of_dasha_boundaries_is_read_off_the_answers(client: Client) -> None:
    report = run(client, window=3)
    assert report.days_per_minute == pytest.approx(DAYS_PER_MINUTE)
    assert report.dashas["Su"][2] == datetime(1984, 5, 2, 8, 31) + timedelta(days=-11)


def test_shifted_charts_are_cached_and_reused(client: Client, monkeypatch) -> None:
    run(client, window=1)
    assert (client.root / "sensitivity" / "+01" / "raw" / "show-chart-D60.json").exists()
    assert not (client.root / "sensitivity" / "+01" / "stages").exists(), \
        "черновая карта не должна заводить каталоги разбора"

    def never(*args, **kwargs):
        raise AssertionError("сеть не должна была понадобиться")

    monkeypatch.setattr(collect_module, "_ensure_session", never)
    assert run(client, window=1).stable["D60"] == (-1, 1)


def test_the_text_names_the_interval_in_clock_time(client: Client) -> None:
    text = render(run(client, window=3))
    assert "D60 сохраняет знак от 22:58 до 23:01" in text
    assert "3 минуты" in text
    assert "при 22:57 и при 23:02 шаштьямша уже другая" in text
    assert "| D60 | Луна | -3 мин (22:57) | Рыбы | Овен |" in text
    assert "| D60 | Лагна | +2 мин (23:02) | Стрелец | Козерог |" in text
    assert "5.5 дня за минуту" in text and "раньше" in text
    assert "0.45° в минуту" in text


def test_a_varga_stable_everywhere_says_so_and_the_verdict_names_the_gate(client: Client) -> None:
    text = render(run(client, window=2, vargas=("D1", "D9")))
    assert "Все проверенные варги устойчивы во всём окне ±2 мин" in text
    assert "Гейт Промпта 07 закрыт" in text          # status is unverified


def test_write_leaves_markdown_and_json(client: Client) -> None:
    md, js = sensitivity.write(run(client, window=2))
    assert md == client.root / "sensitivity.md"
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["stable"]["D60"] == [-2, 1]
    assert payload["days_per_minute"] == pytest.approx(DAYS_PER_MINUTE)
    assert {"varga": "D60", "body": "As", "minutes": 2, "from": "Sg", "to": "Cp"} \
        in payload["changes"]


def test_the_rate_survives_the_ascendant_crossing_thirty_degrees(client: Client) -> None:
    """29.91° Aries → 0.34° Taurus is +0.43°, not −29.6°."""
    report = run(client, window=5)
    assert report.longitude[5] == pytest.approx(30.41, abs=0.01)
    assert report.ascendant_rate() == pytest.approx(0.45, abs=0.01)
    assert "0.45° в минуту" in render(report)
    assert "| +5 | 23:05 | 0.41° Телец |" in render(report)


def test_a_sign_that_changes_at_one_minute_is_not_reported_as_zero_minutes(client: Client, monkeypatch) -> None:
    """The first live run printed «устойчива от +0 до +0 мин, всего 0 минут»."""
    def d60_every_minute(session, chart, divisional="D1", **_):
        if divisional != "D60":
            return fake_show_chart(session, chart, divisional)
        signs = ["Cn", "Le", "Vi", "Li", "Sc", "Sg", "Cp", "Aq", "Pi", "Ar", "Ta"]
        return {"houses": [_house(1, signs[_minutes(chart) + 5], "As")]}

    monkeypatch.setattr(collect_module, "_load_api", lambda: {
        "show_chart": d60_every_minute, "show_info": fake_show_info, "show_dasha": fake_show_dasha})
    report = run(client, window=2)
    assert report.stable["D60"] == (0, 0)
    text = render(report)
    assert "D60 меняет знак уже при смещении на 1 минуту" in text
    assert "при 22:59 и при 23:01 шаштьямша другая" in text
    assert "всего 0 минут" not in text
    assert "с точностью лучше 1 минуты" in text


# ---- a local sweep needs neither the cache nor the network -------------------


class FakeLocal:
    """The fake site as a backend: the same answers, computed for a shifted client."""

    def __init__(self, client):
        self.chart = client.chart

    def payload(self, key):
        if key.startswith("show-chart-"):
            return fake_show_chart(None, self.chart, key.removeprefix("show-chart-"))
        if key == "show-info-D1":
            return fake_show_info(None, self.chart)
        if key.startswith("show-dasha-vimshottari-"):
            return fake_show_dasha(None, self.chart)
        return None


def test_a_local_sweep_gives_the_same_report_with_no_cache(tmp_path: Path, monkeypatch) -> None:
    client = Client.from_dict(dict(CHART), tmp_path)          # nothing collected at all
    monkeypatch.setattr(sensitivity.local_module, "Backend", FakeLocal)
    monkeypatch.setattr(sensitivity.local_module, "available", lambda: True)
    monkeypatch.setattr(collect_module, "_ensure_session",
                        lambda *a: (_ for _ in ()).throw(AssertionError("сеть не нужна")))
    report = run(client, window=3, source="local")
    assert report.source == "local"
    assert report.stable["D60"] == (-2, 1)
    assert not (client.root / "sensitivity").exists()
    assert "локально" in render(report)


def test_auto_runs_locally_only_when_every_block_is_verified(tmp_path: Path, monkeypatch) -> None:
    client = Client.from_dict(dict(CHART), tmp_path)
    monkeypatch.setattr(sensitivity.local_module, "Backend", FakeLocal)
    monkeypatch.setattr(sensitivity.local_module, "available", lambda: True)
    every = {k: "совпало" for k in ("show-chart-D1", "show-chart-D9", "show-chart-D60",
                                    "show-dasha-vimshottari-1")}
    assert sensitivity.can_run_locally(client, ("D1", "D9", "D60"), every)
    assert not sensitivity.can_run_locally(client, ("D1", "D9", "D60"), {**every, "show-chart-D60": "расходится"})
    assert run(client, window=1, source="auto", verified=every).source == "local"
    with pytest.raises(NotCollected):                 # not verified → the site → nothing cached
        run(client, window=1, source="auto", verified={})
