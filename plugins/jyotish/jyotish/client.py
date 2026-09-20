"""One client's reading: its birth data, its settings and where its state lives.

A reading is a directory under ``clients/`` holding everything the ten stages
produce. ``chart.yaml`` is its only hand-written file; the rest is generated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from vedic_parser import Chart

#: Birth-time statuses, as Prompt 01 §1 requires them to be recorded.
BIRTH_TIME_STATUSES = {
    "documented": "документально подтверждено (свидетельство)",
    "rectified": "ректифицировано",
    "relatives": "со слов родственников, ректификация не проводилась",
    "unverified": "не установлен",
}

#: Statuses that open the gate to Prompt 07 (the soul-path calculation) and to
#: conclusions drawn from D60. Prompt 07 refuses to run without one of them.
BIRTH_TIME_CONFIRMED = frozenset({"documented", "rectified"})

#: Vargas Prompt 01 §3 asks for. The "minimal working set" it names as
#: load-bearing is a subset of this, marked in VARGA_PURPOSE below.
DEFAULT_VARGAS = (
    "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10",
    "D11", "D12", "D16", "D20", "D24", "D27", "D30", "D40", "D45", "D60",
)

#: Vargas worth the extra round trips for strengths and yogas.
DEFAULT_DEEP_VARGAS = ("D1", "D9", "D10", "D60")

#: What each varga is read for — Prompt 01 §3. Used to explain, in
#: MISSING_DATA.md, which life area a missing varga leaves unsupported.
VARGA_PURPOSE = {
    "D1": "личность, основа карты",
    "D2": "деньги",
    "D3": "смелость, братья и сёстры",
    "D4": "недвижимость",
    "D6": "здоровье",
    "D7": "дети",
    "D8": "кризисы",
    "D9": "брак, глубина",
    "D10": "карьера",
    "D12": "родители",
    "D16": "комфорт",
    "D20": "духовные практики",
    "D24": "образование",
    "D30": "трудные паттерны",
    "D60": "глубинная карма",
}


class ConfigError(RuntimeError):
    """chart.yaml is missing, unreadable or incomplete."""


@dataclass(frozen=True)
class BirthTime:
    """How much the birth time can be trusted, and why.

    This single field decides whether Prompt 07 runs at all and whether D60
    conclusions are allowed, so it is recorded explicitly rather than assumed.

    ``rectified`` is the one status that is a claim rather than a document,
    so it carries its evidence: who rectified (``by``) and on which events
    (``events``). Prompt 01 has always asked for both; the first full reading
    showed why they must be fields and not a courtesy — the gate to Prompt 07
    was opened on the single word «ректифицировано», with the events never
    named and the person himself saying the time was a family recollection.
    Without the evidence the word does not count.
    """

    status: str = "unverified"
    note: str = ""
    #: Who performed the rectification. Meaningful for ``rectified`` only.
    by: str = ""
    #: The dated events the rectification rests on, one string each.
    events: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in BIRTH_TIME_STATUSES:
            raise ConfigError(
                f"birth_time.status: ожидалось одно из {sorted(BIRTH_TIME_STATUSES)}, "
                f"получено {self.status!r}"
            )

    @property
    def evidence_missing(self) -> tuple[str, ...]:
        """Which parts of a rectification claim are absent.

        Empty for every status but ``rectified``: a document is its own
        evidence, and the unconfirmed statuses claim nothing.
        """
        if self.status != "rectified":
            return ()
        missing = []
        if not self.by.strip():
            missing.append("кем (birth_time.by)")
        if not [event for event in self.events if event.strip()]:
            missing.append("по каким событиям (birth_time.events)")
        return tuple(missing)

    @property
    def confirmed(self) -> bool:
        """Whether the soul-path stage and D60 conclusions are allowed.

        A rectification without its evidence is not a rectification for the
        gate's purposes: the status stays in the file as written, but it
        opens nothing until ``by`` and ``events`` are filled in.
        """
        return self.status in BIRTH_TIME_CONFIRMED and not self.evidence_missing

    @property
    def label(self) -> str:
        text = BIRTH_TIME_STATUSES[self.status]
        if self.status == "rectified":
            if self.evidence_missing:
                text += (" — НЕ ЗАСЧИТАНО: не указано, "
                         + " и ".join(self.evidence_missing)
                         + "; гейт Промпта 07 закрыт")
            else:
                text += f" ({self.by}; по событиям: {'; '.join(self.events)})"
        return f"{text} — {self.note}" if self.note else text

    @property
    def short(self) -> str:
        """The status plus the first sentence of the note, for a table cell.

        ``label`` carries the whole note, which is the right thing in prose and
        the wrong thing in a checklist row: the note is a YAML block that can
        run to a dozen lines, and it made one cell longer than the rest of the
        table put together. The full text lives in chart.yaml.
        """
        text = BIRTH_TIME_STATUSES[self.status]
        if self.evidence_missing:
            # The gate is shut for a reason the reader must not miss, and
            # the note is the wrong place to look for it.
            return f"{text} — НЕ ЗАСЧИТАНО, не указано {' и '.join(self.evidence_missing)}"
        first = " ".join(self.note.split()).split(". ")[0].rstrip(".")
        if not first:
            return text
        if len(first) > 120:
            first = first[:117].rstrip() + "…"
        return f"{text} — {first}"


@dataclass(frozen=True)
class CollectSettings:
    """What stage 01 fetches and how politely."""

    lang: str = "en"
    vargas: tuple[str, ...] = DEFAULT_VARGAS
    deep_vargas: tuple[str, ...] = DEFAULT_DEEP_VARGAS
    #: Seconds to wait between network calls. Every call makes the site
    #: compute a chart, so this is a courtesy, not a tuning knob.
    throttle: float = 2.0
    #: Vimshottari depth to fetch in full. Level 3 is ~700 rows already, so
    #: deeper levels are fetched only around the current moment.
    dasha_level: int = 2
    #: Seconds to wait for one response. The heavier dasha tables can take the
    #: site the better part of a minute to compute, well past the parser's own
    #: 30-second default.
    timeout: int = 90


@dataclass(frozen=True)
class Client:
    """A reading in progress."""

    slug: str
    chart: Chart
    place: str
    birth_time: BirthTime
    collect: CollectSettings
    root: Path
    #: Which node the site computes, ``mean`` or ``true`` — the site does not
    #: say, the cross-check can tell, and once known it is recorded here so
    #: the difference from the other type stops being reported as a question.
    nodes: str = ""

    # ---- paths -----------------------------------------------------------

    @property
    def raw_dir(self) -> Path:
        """Cached site responses, one JSON file per action and parameters."""
        return self.root / "raw"

    @property
    def state_dir(self) -> Path:
        """Machine-readable state carried between stages."""
        return self.root / "state"

    @property
    def stages_dir(self) -> Path:
        """Full prose of each stage."""
        return self.root / "stages"

    @property
    def summaries_dir(self) -> Path:
        """The per-stage summaries the next stage reads instead of copypaste."""
        return self.state_dir / "summaries"

    @property
    def raw_data_md(self) -> Path:
        return self.root / "01_RAW_DATA.md"

    @property
    def missing_data_md(self) -> Path:
        return self.root / "01_MISSING_DATA.md"

    @property
    def biography_md(self) -> Path:
        """Written by a human. Absent means the Prompt 03 gate is shut."""
        return self.root / "biography.md"

    def ensure_dirs(self) -> None:
        for path in (self.raw_dir, self.state_dir, self.stages_dir, self.summaries_dir):
            path.mkdir(parents=True, exist_ok=True)

    # ---- loading ---------------------------------------------------------

    @classmethod
    def load(cls, root: str | Path) -> "Client":
        """Read ``<root>/chart.yaml``."""
        root = Path(root)
        config_path = root / "chart.yaml"
        if not config_path.exists():
            raise ConfigError(f"нет файла {config_path}")
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as error:
            raise ConfigError(f"{config_path}: {error}") from error
        if not isinstance(data, dict):
            raise ConfigError(f"{config_path}: ожидался словарь верхнего уровня")
        return cls.from_dict(data, root)

    @classmethod
    def from_dict(cls, data: dict[str, Any], root: str | Path) -> "Client":
        root = Path(root)
        missing = [key for key in ("date", "time", "timezone", "latitude", "longitude")
                   if data.get(key) in (None, "")]
        if missing:
            raise ConfigError(f"в chart.yaml не заполнено: {', '.join(missing)}")

        chart = Chart(
            name=str(data.get("name") or root.name),
            date=str(data["date"]),
            time=str(data["time"]),
            timezone=str(data["timezone"]),
            latitude=str(data["latitude"]),
            longitude=str(data["longitude"]),
        )

        birth_raw = data.get("birth_time") or {}
        if not isinstance(birth_raw, dict):
            raise ConfigError("birth_time должен быть словарём со status и note")
        birth_time = BirthTime(
            status=str(birth_raw.get("status", "unverified")),
            note=str(birth_raw.get("note", "") or ""),
            by=str(birth_raw.get("by", "") or ""),
            events=_events(birth_raw.get("events")),
        )

        collect_raw = data.get("collect") or {}
        if not isinstance(collect_raw, dict):
            raise ConfigError("collect должен быть словарём")
        # Defaults live on CollectSettings alone, so chart.yaml omitting a key
        # and the dataclass can never drift apart.
        defaults = CollectSettings()
        collect = CollectSettings(
            lang=str(collect_raw.get("lang", defaults.lang)),
            vargas=tuple(collect_raw.get("vargas") or defaults.vargas),
            deep_vargas=tuple(collect_raw.get("deep_vargas") or defaults.deep_vargas),
            throttle=float(collect_raw.get("throttle", defaults.throttle)),
            dasha_level=int(collect_raw.get("dasha_level", defaults.dasha_level)),
            timeout=int(collect_raw.get("timeout", defaults.timeout)),
        )

        nodes = str(data.get("nodes", "") or "")
        if nodes not in ("", "mean", "true"):
            raise ConfigError(f"nodes: ожидалось mean или true, получено {nodes!r}")

        return cls(
            slug=str(data.get("slug") or root.name),
            chart=chart,
            place=str(data.get("place", "") or ""),
            birth_time=birth_time,
            collect=collect,
            root=root,
            nodes=nodes,
        )


def _events(raw: Any) -> tuple[str, ...]:
    """``birth_time.events`` as written by a person: strings, or date/what pairs.

    Both spellings are accepted because both are natural in YAML::

        events:
          - "06.2013 — переезд в Москву"
          - {date: "09.2016", what: "рождение сына"}
    """
    if raw in (None, ""):
        return ()
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise ConfigError("birth_time.events должен быть списком событий")
    events = []
    for item in raw:
        if isinstance(item, dict):
            date, what = str(item.get("date", "") or ""), str(item.get("what", "") or "")
            if not (date and what):
                raise ConfigError("у события в birth_time.events нужны date и what")
            events.append(f"{date} — {what}")
        else:
            events.append(str(item))
    return tuple(events)


TEMPLATE = """\
# Описание карты. Заполняется человеком, всё остальное генерируется.
slug: {slug}
name: {slug}
place: ""

# Ровно то, что принимает форма сайта.
# Координаты — градусы.минуты, НЕ десятичные: 55.45 значит 55°45'.
# Отрицательные — для южной широты и западной долготы.
date: "01.01.1990"      # ДД.ММ.ГГГГ
time: "12:00:00"        # ЧЧ:ММ:СС
timezone: "+3"          # часы смещения
latitude: "55.45"
longitude: "37.37"

# От этого зависит допуск к Промпту 07 и выводам по D60.
# documented | rectified | relatives | unverified
# Для rectified обязательны by и events — без них статус не засчитывается:
#   by: "имя или описание астролога"
#   events:
#     - "06.2013 — переезд в Москву"
#     - "09.2016 — рождение сына"
birth_time:
  status: unverified
  note: ""

# Какой узел считает сайт: mean или true. Сайт этого не показывает; сверка
# (jyotish crosscheck) покажет, какой из двух совпадает. Пусто — не установлено.
nodes: ""

collect:
  lang: en              # en — vedic-horo.com, стабильнее; .ru роняет сессию
  throttle: 2.0         # секунд между запросами; сайт отвечает 429 при более частых
  timeout: 90           # секунд на ответ; тяжёлые таблицы даш сайт считает долго
  dasha_level: 2
"""


def scaffold(root: str | Path, slug: str) -> Path:
    """Create a client directory with a chart.yaml to fill in."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "chart.yaml"
    if config_path.exists():
        raise ConfigError(f"{config_path} уже существует")
    config_path.write_text(TEMPLATE.format(slug=slug), encoding="utf-8")
    return config_path
