"""Stage 03 support: how much of the chart survives an error in the birth time.

Prompt 03 checks the birth time against dated events and used to conclude
from 4–5 matches that D60 was admissible. That is not a matter of judgement
but of arithmetic, and the arithmetic must not be done in anyone's head: the
first full reading worked out «0.447° per minute» and «5.5 days per minute»
by hand, which is exactly the astronomical computation the methodology
forbids the model.

So the site does it. The chart is re-collected at the birth time shifted by
±1…N minutes and the outputs are compared: which vargas change their
ascendant sign at which offset, which planets move to another varga sign,
and how far the dasha boundaries slide per minute. Nothing here computes a
position; every number is a difference between two answers from the same
source.

The result is the interval, in minutes around the recorded time, within
which each varga is stable. For D60 that is the precision a rectification
must reach before conclusions from it — and Prompt 07 — are admissible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from vedic_parser import Chart

from .client import Client
from . import local as local_module
from .collect import Request, collect, from_cache, local_allowed
from .derive import SIGN_CODES, SIGNS_RU
from .text import counted, number

DATE_FORMAT = "%d.%m.%Y"
TIME_FORMAT = "%H:%M:%S"

#: The bodies whose varga sign is compared. The ascendant first: it is the
#: one that moves a degree every few minutes, and the one every varga hangs
#: on. The planets follow because the Moon, at half an arcminute per minute,
#: does cross a D60 boundary now and then.
BODIES = ("As", "Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "Ra", "Ke")

BODY_RU = {
    "As": "Лагна", "Su": "Солнце", "Mo": "Луна", "Ma": "Марс", "Me": "Меркурий",
    "Ju": "Юпитер", "Ve": "Венера", "Sa": "Сатурн", "Ra": "Раху", "Ke": "Кету",
}

DASHA_KEY = "show-dasha-vimshottari-1"


class NotCollected(RuntimeError):
    """The base chart (offset 0) is not on disk, so there is nothing to compare."""


# ---------------------------------------------------------------------------
# shifting the chart
# ---------------------------------------------------------------------------


def shifted_chart(chart: Chart, minutes: int) -> Chart:
    """The same chart with the birth moment moved by ``minutes``.

    Crossing midnight moves the date as well: a 23:59 birth shifted by +2
    minutes is the next day's 00:01, and the site must be asked for that.
    """
    moment = datetime.strptime(f"{chart.date} {chart.time}", f"{DATE_FORMAT} {TIME_FORMAT}")
    moment += timedelta(minutes=minutes)
    return replace(chart, date=moment.strftime(DATE_FORMAT), time=moment.strftime(TIME_FORMAT))


def offset_label(minutes: int) -> str:
    """``+02`` / ``-01``: sortable, and readable as a directory name."""
    return f"{minutes:+03d}"


def offset_client(client: Client, minutes: int) -> Client:
    """A client whose cache lives under ``sensitivity/<offset>/`` of the reading.

    Each offset is a different chart, so it gets its own cache with its own
    identity marker; the base reading's cache is never touched.
    """
    return replace(
        client,
        chart=shifted_chart(client.chart, minutes),
        root=client.root / "sensitivity" / offset_label(minutes),
    )


def offsets(window: int, step: int = 1) -> list[int]:
    """Every offset in the window except zero, which is the base collection."""
    if window < 1 or step < 1:
        raise ValueError("окно и шаг — целые минуты, не меньше 1")
    return [m for m in range(-window, window + 1, step) if m != 0]


def build_offset_plan(vargas: Sequence[str]) -> list[Request]:
    """What one shifted chart needs: the signs of every varga and the dashas.

    ``show-chart`` and not ``show-info``: in a varga other than D1 the
    latter's ``rasi`` column is still the natal sign (see vedic_parser.api),
    so it would report every varga as perfectly stable.
    """
    plan = [Request("show-chart", {"divisional": varga}) for varga in vargas]
    plan.append(Request("show-info", {"divisional": "D1"}))
    plan.append(Request("show-dasha", {"dasha": "vimshottari", "level": 1}))
    return plan


# ---------------------------------------------------------------------------
# reading the answers
# ---------------------------------------------------------------------------


def sign_of(data: Mapping[str, Any], varga: str, body: str) -> str | None:
    """The sign code ``body`` occupies in ``varga``, from its show-chart."""
    chart = data.get(f"show-chart-{varga}") or {}
    for house in chart.get("houses", []):
        if any(p.get("code") == body for p in house.get("planets", [])):
            return (house.get("sign") or {}).get("code")
    return None


def ascendant_degree(data: Mapping[str, Any]) -> float | None:
    """Degrees within the sign, as the site prints them."""
    info = data.get("show-info-D1") or {}
    for planet in info.get("planets", []):
        if planet.get("code") == "As":
            return planet.get("degrees_decimal")
    return None


def ascendant_longitude(data: Mapping[str, Any]) -> float | None:
    """Sidereal longitude 0–360°, so a rate across 30° does not come out negative.

    The first live run printed «−2.56° в минуту»: the ascendant went from
    29.91° Aries to 0.34° Taurus and the difference of the printed degrees
    was taken at face value.
    """
    degree = ascendant_degree(data)
    sign = sign_of(data, "D1", "As")
    if degree is None or sign not in SIGN_CODES:
        return None
    return SIGN_CODES.index(sign) * 30 + degree


def dasha_starts(data: Mapping[str, Any]) -> dict[str, datetime]:
    """Mahadasha lord → start moment, for every period the site listed."""
    starts: dict[str, datetime] = {}
    for period in (data.get(DASHA_KEY) or {}).get("periods", []):
        lords = period.get("lords") or []
        start = period.get("start")
        if lords and start:
            starts[lords[0]] = datetime.fromisoformat(start)
    return starts


def stable_span(series: Mapping[int, str | None], step: int = 1) -> tuple[int, int]:
    """The contiguous offsets around zero over which the value equals the base.

    Returns the lowest and highest offset still equal to the value at zero,
    walking outwards one ``step`` at a time. An offset that was not collected
    ends the span: unknown is not «stable».
    """
    base = series.get(0)
    low = high = 0
    for direction in (-1, 1):
        m = direction * step
        while series.get(m) is not None and series[m] == base:
            if direction < 0:
                low = m
            else:
                high = m
            m += direction * step
    return low, high


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    """One body leaving its base sign in one varga at one offset."""

    varga: str
    body: str
    minutes: int
    from_sign: str | None
    to_sign: str | None


@dataclass
class Report:
    client: Client
    window: int
    step: int
    vargas: tuple[str, ...]
    #: offset → what came back for it (0 is the base collection).
    runs: dict[int, Mapping[str, Any]]
    #: varga → body → offset → sign code.
    signs: dict[str, dict[str, dict[int, str | None]]] = field(default_factory=dict)
    changes: list[Change] = field(default_factory=list)
    #: varga → (low, high) offsets over which every body keeps its sign.
    stable: dict[str, tuple[int, int]] = field(default_factory=dict)
    ascendant: dict[int, float | None] = field(default_factory=dict)
    longitude: dict[int, float | None] = field(default_factory=dict)
    #: mahadasha lord → offset → start.
    dashas: dict[str, dict[int, datetime]] = field(default_factory=dict)
    #: Mean slide of the boundaries, days per minute of birth time; positive
    #: means a later birth moves the boundaries later.
    days_per_minute: float | None = None
    missing: list[str] = field(default_factory=list)
    #: ``site`` or ``local`` — what computed the shifted charts.
    source: str = "site"

    @property
    def collected_offsets(self) -> list[int]:
        return sorted(self.runs)

    def whole_window(self, varga: str) -> bool:
        low, high = self.stable.get(varga, (0, 0))
        return low == -self.window and high == self.window

    def ascendant_rate(self) -> float | None:
        """Degrees per minute across the window, from the site's own answers."""
        known = {m: lon for m, lon in self.longitude.items() if lon is not None}
        if len(known) < 2:
            return None
        first, last = min(known), max(known)
        travelled = (known[last] - known[first]) % 360
        return travelled / (last - first)


def analyse(client: Client, runs: Mapping[int, Mapping[str, Any]], vargas: Sequence[str],
            *, window: int, step: int = 1) -> Report:
    """Compare the shifted answers with the base one. Pure: no I/O."""
    if 0 not in runs:
        raise NotCollected("нет базовой карты (смещение 0) — сначала `jyotish collect`")
    report = Report(client=client, window=window, step=step, vargas=tuple(vargas),
                    runs=dict(runs))
    base = runs[0]

    for varga in vargas:
        if not base.get(f"show-chart-{varga}"):
            report.missing.append(f"show-chart-{varga}")
            continue
        per_body: dict[str, dict[int, str | None]] = {}
        spans = []
        for body in BODIES:
            series = {m: sign_of(data, varga, body) for m, data in runs.items()}
            if series[0] is None:
                continue
            per_body[body] = series
            spans.append(stable_span(series, step))
            for m in sorted(series):
                if m != 0 and series[m] is not None and series[m] != series[0]:
                    report.changes.append(Change(varga, body, m, series[0], series[m]))
        report.signs[varga] = per_body
        if spans:
            report.stable[varga] = (max(s[0] for s in spans), min(s[1] for s in spans))

    report.ascendant = {m: ascendant_degree(data) for m, data in runs.items()}
    report.longitude = {m: ascendant_longitude(data) for m, data in runs.items()}

    if not base.get(DASHA_KEY):
        report.missing.append(DASHA_KEY)
    else:
        base_starts = dasha_starts(base)
        for lord, start in base_starts.items():
            report.dashas[lord] = {0: start}
        slides = []
        for m, data in runs.items():
            if m == 0:
                continue
            for lord, start in dasha_starts(data).items():
                if lord in report.dashas:
                    report.dashas[lord][m] = start
                    delta = (start - base_starts[lord]).total_seconds() / 86400
                    slides.append(delta / m)
        if slides:
            report.days_per_minute = sum(slides) / len(slides)
    return report


# ---------------------------------------------------------------------------
# running it
# ---------------------------------------------------------------------------


def can_run_locally(client: Client, vargas: Sequence[str], verified: dict[str, str]) -> bool:
    """Whether every block the sweep reads has been verified for this chart.

    The sweep compares signs and dasha boundaries; those are exactly the
    blocks the cross-check settles. When all of them agree with the site, the
    sweep costs no requests and runs in a second.
    """
    keys = [r.key for r in build_offset_plan(vargas) if r.key != "show-info-D1"]
    return local_module.available() and all(local_allowed("auto", k, verified) for k in keys)


def run(
    client: Client,
    *,
    window: int = 3,
    step: int = 1,
    vargas: Sequence[str] | None = None,
    refresh: bool = False,
    source: str = "auto",
    verified: dict[str, str] | None = None,
    log: Callable[[str], None] = lambda message: None,
) -> Report:
    """Collect every offset (cached after the first time) and compare.

    ``source``: ``site`` asks the site for every offset; ``local`` computes
    every offset (and the base) with the local backend; ``auto`` computes
    locally when every block the sweep reads is verified for this chart,
    and asks the site otherwise.
    """
    chosen = tuple(vargas or client.collect.vargas)
    if verified is None:
        from .crosscheck import read_verified
        verified = read_verified(client)
    if source == "auto":
        source = "local" if can_run_locally(client, chosen, verified) else "site"

    plan = build_offset_plan(chosen)
    runs: dict[int, Mapping[str, Any]] = {}
    if source == "local":
        # The base too: comparing the site's chart with local offsets would
        # put a 0.01′ seam at zero, and a sign boundary can sit in it.
        for minutes in [0] + offsets(window, step):
            backend = local_module.Backend(offset_client(client, minutes))
            runs[minutes] = {r.key: backend.payload(r.key) for r in plan}
            log(f"смещение {offset_label(minutes)} мин — локально")
        report = analyse(client, runs, chosen, window=window, step=step)
        report.source = "local"
        return report

    base = from_cache(client)
    if not base.get("show-chart-D1"):
        raise NotCollected(
            f"базовая карта не собрана ({client.raw_dir / 'show-chart-D1.json'}) — "
            f"сначала `jyotish collect {client.root}`"
        )
    runs[0] = base.data
    for minutes in offsets(window, step):
        shifted = offset_client(client, minutes)
        log(f"смещение {offset_label(minutes)} мин → {shifted.chart.date} {shifted.chart.time}")
        result = collect(shifted, plan=plan, refresh=refresh, probe=False, source="site", log=log)
        runs[minutes] = result.data
    report = analyse(client, runs, chosen, window=window, step=step)
    report.source = "site"
    return report


def write(report: Report) -> tuple[Path, Path]:
    """``sensitivity.md`` for the reader and ``state/sensitivity.json`` for the checks."""
    client = report.client
    client.ensure_dirs()
    md = client.root / "sensitivity.md"
    md.write_text(render(report), encoding="utf-8")
    js = client.state_dir / "sensitivity.json"
    js.write_text(json.dumps(as_dict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return md, js


def as_dict(report: Report) -> dict[str, Any]:
    return {
        "time": report.client.chart.time,
        "window": report.window,
        "step": report.step,
        "offsets": report.collected_offsets,
        "source": report.source,
        "stable": {varga: list(span) for varga, span in report.stable.items()},
        "changes": [
            {"varga": c.varga, "body": c.body, "minutes": c.minutes,
             "from": c.from_sign, "to": c.to_sign}
            for c in report.changes
        ],
        "days_per_minute": report.days_per_minute,
        "missing": report.missing,
    }


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _sign_ru(code: str | None) -> str:
    if code is None:
        return "—"
    return SIGNS_RU[SIGN_CODES.index(code)] if code in SIGN_CODES else code


def _span_text(report: Report, varga: str) -> str:
    low, high = report.stable[varga]
    if report.whole_window(varga):
        return f"устойчива во всём окне ±{report.window} мин"
    return f"устойчива от {low:+d} до {high:+d} мин"


def _clock(client: Client, minutes: int) -> str:
    return shifted_chart(client.chart, minutes).time[:5]


def _minutes_ru(count: int) -> str:
    return counted(count, "минута", "минуты", "минут")


def _minutes_acc(count: int) -> str:
    """Accusative: «на 1 минуту», «на 2 минуты», «на 5 минут»."""
    return counted(count, "минуту", "минуты", "минут")


def _days_ru(days: float) -> str:
    """«5,5 дня», but «1 день» and «3 дня»: a fraction always takes the genitive."""
    if float(days).is_integer():
        return counted(int(days), "день", "дня", "дней")
    return f"{number(days, 1)} дня"


def _d60_verdict(report: Report, low: int, high: int) -> str:
    """The one sentence the whole report exists for.

    The span is what was *observed* stable, at the step of the sweep: a span
    of (0, 0) at step 1 does not mean «zero minutes», it means the sign is
    already different one minute either way, and the true tolerance is
    somewhere under a minute.
    """
    client, step = report.client, report.step
    width = high - low
    edges = []
    if low > -report.window:
        edges.append(f"{_clock(client, low - step)}")
    if high < report.window:
        edges.append(f"{_clock(client, high + step)}")
    at = " и при ".join(edges)
    if width == 0:
        return (f"**D60 меняет знак уже при смещении на {_minutes_acc(step)}** — "
                f"при {at} шаштьямша другая. Время должно быть известно с точностью "
                f"лучше {counted(step, 'минуты', 'минут', 'минут')}, чтобы выводы по D60 "
                "и Промпт 07 были "
                "допустимы; шаг проверки этого не разрешает, а события, датированные "
                "днём, — тем более.")
    return (f"**D60 сохраняет знак от {_clock(client, low)} до {_clock(client, high)}** "
            f"({_minutes_ru(width)}, смещения {low:+d}…{high:+d}); при {at} шаштьямша уже "
            f"другая. Именно с такой точностью время должно быть известно, чтобы выводы "
            "по D60 и Промпт 07 были допустимы.")


def render(report: Report) -> str:
    """The Markdown the reader gets: tables of signs, the slide, the verdict."""
    client = report.client
    cols = report.collected_offsets
    out = [
        "# Чувствительность карты ко времени рождения",
        "",
        f"Записанное время: **{client.chart.time}** ({client.chart.date}). "
        f"Карта пересобрана {'локально (PyJHora, сверено с сайтом по этим блокам)' if report.source == 'local' else 'на сайте'} "
        f"со смещением от {-report.window:+d} до {report.window:+d} мин с шагом {report.step}; "
        "ниже — сравнение выдач одного и того же расчёта, а не рассуждение.",
        "",
    ]
    if report.missing:
        out += [
            "**Не сравнивалось** (нет в базовой карте): " + ", ".join(report.missing) + ".",
            "",
        ]

    # 1. The ascendant, degree by degree, as the site reports it.
    degrees = {m: d for m, d in report.ascendant.items() if d is not None}
    if len(degrees) >= 2:
        out += ["## Градус Лагны в D1", "", "| Смещение | Время | Лагна |", "|---|---|---|"]
        for m in cols:
            if m in degrees:
                sign = _sign_ru(sign_of(report.runs[m], "D1", "As"))
                out.append(f"| {m:+d} | {_clock(client, m)} | {number(degrees[m], 2)}° {sign} |")
        rate = report.ascendant_rate()
        if rate:
            out += ["", f"Лагна проходит около **{number(rate, 2)}° в минуту** "
                        "(по выдачам сайта на краях окна).", ""]

    # 2. Ascendant sign per varga across the window.
    out += ["## Знак Лагны по варгам", "",
            "| Варга | " + " | ".join(f"{m:+d}" for m in cols) + " | Итог |",
            "|---|" + "---|" * len(cols) + "---|"]
    for varga in report.vargas:
        per_body = report.signs.get(varga)
        if not per_body or "As" not in per_body:
            continue
        series = per_body["As"]
        cells = [_sign_ru(series.get(m)) for m in cols]
        out.append(f"| {varga} | " + " | ".join(cells) + f" | {_span_text(report, varga)} |")
    out.append("")

    # 3. Every body that leaves its sign somewhere in the window.
    out += ["## Что меняет знак в окне", ""]
    if not report.changes:
        out += ["Ни одна планета и ни одна Лагна не меняет знак ни в одной из "
                f"проверенных варг в пределах ±{report.window} мин.", ""]
    else:
        out += ["| Варга | Кто | Смещение | Было | Стало |", "|---|---|---|---|---|"]
        seen = set()
        for change in report.changes:
            # One line per crossing: the first offset at which the sign differs,
            # in each direction, is the boundary; later offsets repeat it.
            key = (change.varga, change.body, change.minutes > 0)
            if key in seen:
                continue
            seen.add(key)
            out.append(f"| {change.varga} | {BODY_RU.get(change.body, change.body)} | "
                       f"{change.minutes:+d} мин ({_clock(client, change.minutes)}) | "
                       f"{_sign_ru(change.from_sign)} | {_sign_ru(change.to_sign)} |")
        out.append("")

    # 4. Dasha boundaries.
    if report.dashas:
        out += ["## Границы махадаш (Вимшоттари)", "",
                "| Махадаша | " + " | ".join(f"{m:+d}" for m in cols) + " |",
                "|---|" + "---|" * len(cols)]
        for lord, starts in report.dashas.items():
            if len(starts) < 2:
                continue
            cells = [starts[m].strftime("%d.%m.%Y %H:%M") if m in starts else "—" for m in cols]
            out.append(f"| {BODY_RU.get(lord, lord)} | " + " | ".join(cells) + " |")
        out.append("")
        if report.days_per_minute is not None:
            days = report.days_per_minute
            direction = ("позже" if days > 0 else "раньше")
            out += [f"Границы всех периодов сдвигаются в среднем на **{_days_ru(abs(days))} "
                    f"за минуту** времени рождения: при более позднем рождении — {direction}. "
                    "Это масштаб, в котором даты этапа 05 зависят от точности времени.", ""]

    # 5. The verdict.
    out += ["## Вывод", ""]
    if "D60" in report.stable:
        low, high = report.stable["D60"]
        if report.whole_window("D60"):
            out.append(
                f"**D60 устойчива во всём окне ±{report.window} мин**: ни Лагна, ни планеты не "
                f"меняют шаштьямшу от {_clock(client, low)} до {_clock(client, high)}. "
                "Чтобы судить о запасе за пределами окна, увеличьте его.")
        else:
            out.append(_d60_verdict(report, low, high))
        out.append("")
    unstable = [v for v in report.vargas if v in report.stable and not report.whole_window(v)]
    if unstable:
        out.append("Меняются в окне: " + ", ".join(
            f"{v} ({report.stable[v][0]:+d}…{report.stable[v][1]:+d})" for v in unstable) + ".")
    else:
        out.append(f"Все проверенные варги устойчивы во всём окне ±{report.window} мин.")
    out.append("")

    birth = client.birth_time
    if birth.confirmed:
        out.append(
            f"Статус времени: {birth.short}. Проверьте, что события ректификации дают "
            "точность не хуже интервала устойчивости D60 — иначе ректификация есть, а "
            "допуска к D60 по существу нет.")
    else:
        out.append(
            f"Статус времени: {birth.short}. Гейт Промпта 07 закрыт; интервал выше — "
            "то, чего должна достичь ректификация, чтобы его открыть. Таблица проверки "
            "по дашам (Промпт 03) этого не даёт: события, датированные месяцем, "
            "подтверждают час, а не минуту.")
    out.append("")
    return "\n".join(out)
