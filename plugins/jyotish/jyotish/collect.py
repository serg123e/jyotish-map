"""Stage 01: fetch everything Prompt 01 asks for, once, and cache it.

The plan is built as data (:func:`build_plan`) and then executed
(:func:`collect`). Two properties matter more than speed:

* **Politeness.** Every call makes the site compute a chart from scratch, so
  responses are cached on disk and a pause separates network calls. Re-running
  a completed collection costs nothing.
* **Tolerance of a moving parser.** Actions whose parser does not exist yet in
  ``vedic_parser`` are detected at runtime, reported honestly as missing, and
  picked up automatically once the parser lands — no edit here. While probing
  is on, their raw HTML is saved too, which is exactly the fixture the missing
  parser needs.
"""

from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from vedic_parser import Chart, Session
from vedic_parser.session import AccessDenied, VedicHoroError

from .client import Client


class RateLimited(VedicHoroError):
    """The site is throttling us.

    Kept apart from every other failure on purpose: being throttled says
    nothing about whether the data exists, so it must never be recorded as a
    gap in MISSING_DATA.md. The sweep stops instead, and the cache lets the
    next run continue where this one left off.
    """

# Prompt 01 spells its unavailability markers out; they go into MISSING_DATA.md
# verbatim rather than paraphrased.
UNAVAILABLE = "НЕДОСТУПНО В ТЕКУЩЕМ ДОСТУПЕ"
PAID = "ТРЕБУЕТ ПЛАТНОГО ДОСТУПА"
AUTH = "ТРЕБУЕТ АВТОРИЗАЦИИ"
NOT_SUPPLIED = "НЕ ПРИСЛАНО ПОЛЬЗОВАТЕЛЕМ"

#: Site action -> the name ``vedic_parser.api`` uses (or would use) for it.
#: Actions absent from the installed parser are handled, not assumed away.
API_NAMES = {
    "show-info": "show_info",
    "show-chart": "show_chart",
    "show-other": "show_other",
    "show-bala": "show_bala",
    "show-dasha": "show_dasha",
    # Endpoints that are open and reconnoitred but may have no parser yet.
    "show-bhava": "show_bhava",
    "show-yogas": "show_yogas",
    "show-avasthas": "show_avasthas",
    "show-sade-sati": "show_sade_sati",
    "show-current-periods": "show_current_periods",
    "get-aspects": "get_aspects",
    "get-argala": "get_argala",
}

#: Which section of Prompt 01 each action feeds. Used by the MISSING_DATA
#: report to say what a gap actually costs.
SECTIONS = {
    "show-info": "§2 D1, §3 варги, §4 накшатры, §10 аштакаварга",
    "show-chart": "§2 D1, §3 варги (знаки варги), §17 аспекты",
    "show-other": "§7 спец. лагны и точки, §18 панчанга",
    "show-bala": "§8 сила планет, §9 дрик-бала на дома",
    "show-dasha": "§14 даши",
    "show-bhava": "§17 бхава-чалита (бхава-балы сайт не отдаёт)",
    "show-yogas": "§11 йоги",
    "show-avasthas": "§12 авастхи",
    "show-sade-sati": "§16 транзиты (саде-сати)",
    "show-current-periods": "§14 текущий период",
    "get-aspects": "§5 раши-дришти, §17 аспекты",
    "get-argala": "§17 аргала и виродха-аргала",
}


@dataclass(frozen=True)
class Request:
    """One planned call: what to ask for and where to cache it."""

    action: str
    params: dict[str, Any] = field(default_factory=dict)
    #: Cache file stem, and the key this response gets in the collected data.
    key: str = ""
    #: A missing parser for this action is expected, not an error.
    optional: bool = False

    def __post_init__(self) -> None:
        if not self.key:
            suffix = "-".join(str(v) for v in self.params.values() if v not in ("", None))
            object.__setattr__(self, "key", f"{self.action}-{suffix}" if suffix else self.action)


@dataclass
class Gap:
    """Something Prompt 01 asks for that this collection did not get."""

    key: str
    marker: str
    reason: str
    section: str = ""
    html_saved: Path | None = None


@dataclass
class Collection:
    """The result of a sweep: the data, and an honest account of the holes."""

    data: dict[str, Any] = field(default_factory=dict)
    gaps: list[Gap] = field(default_factory=list)
    fetched: list[str] = field(default_factory=list)
    cached: list[str] = field(default_factory=list)

    def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    @property
    def vargas_present(self) -> list[str]:
        """Vargas for which both the table and the chart came back, D1…D60.

        Sorted by division, not as text: D2 belongs before D10.
        """
        found = [
            key.removeprefix("show-chart-")
            for key in self.data
            if key.startswith("show-chart-")
            and f"show-info-{key.removeprefix('show-chart-')}" in self.data
        ]
        return sorted(found, key=lambda varga: (int(varga[1:]) if varga[1:].isdigit() else 999,
                                                varga))


def build_plan(client: Client) -> list[Request]:
    """Everything to request for one chart, in the order it will be asked.

    Kept deliberately narrow where the site charges us for breadth:
    ``show-other`` and ``show-bala`` run only for the deep vargas, because the
    parts of them that vary by varga are the parts few stages read.
    """
    settings = client.collect
    plan: list[Request] = []

    for varga in settings.vargas:
        plan.append(Request("show-info", {"divisional": varga}))
        plan.append(Request("show-chart", {"divisional": varga}))

    for varga in settings.deep_vargas:
        plan.append(Request("show-other", {"divisional": varga}))
        plan.append(Request("show-bala", {"divisional": varga}))
        plan.append(Request("show-yogas", {"divisional": varga}))
        plan.append(Request("show-avasthas", {"divisional": varga}))
        plan.append(Request("show-bhava", {"divisional": varga}))

    # Reckoned from the Moon and from the Arudha Lagna: Prompt 01 §5 and §6
    # read the chart from those points as well as from the Ascendant.
    plan.append(Request("show-info", {"divisional": "D1", "from_": "2"}, key="show-info-D1-from-moon"))
    plan.append(Request("show-info", {"divisional": "D1", "from_": "AL"}, key="show-info-D1-from-al"))

    # Vimshottari in full to antardasha; deeper levels only around today,
    # which is the stretch Prompt 05 actually reads.
    # dict.fromkeys and not a set: the order of the plan is part of its meaning,
    # and dasha_level = 1 would otherwise queue level 1 twice under one key.
    for level in dict.fromkeys((1, settings.dasha_level)):
        plan.append(Request("show-dasha", {"dasha": "vimshottari", "level": level}))
    for level in (3, 4):
        plan.append(Request("show-dasha", {"dasha": "vimshottari", "level": level},
                            key=f"show-dasha-vimshottari-{level}-current"))
    for system in ("ashtottari", "yogini", "chara_rao", "narayana", "navamsa"):
        plan.append(Request("show-dasha", {"dasha": system, "level": 2}))

    plan.append(Request("show-sade-sati"))

    # Rasi drishti (Prompt 01 §5) and argala (§17) are asked per sign, so a
    # full picture is twelve calls each. Argala type=1 is the classical set;
    # type=2 is a second, rarely-read one and is left out by default.
    for sign in range(1, 13):
        plan.append(Request("get-aspects", {"sign": sign, "divisional": "D1"}))
    for sign in range(1, 13):
        plan.append(Request("get-argala", {"sign": sign, "type": 1, "divisional": "D1"},
                            key=f"get-argala-{sign}"))

    # Reconnoitred but not yet wrapped by a parser. Listed so the gap is
    # reported rather than silently absent; picked up automatically if added.
    plan.append(Request("show-current-periods", optional=True))

    return plan


def from_cache(client: Client, *, plan: Iterable[Request] | None = None) -> Collection:
    """Everything already on disk, with no network access at all.

    Lets the export be re-rendered after a change to the renderer, and lets a
    partly-collected reading be inspected without asking the site again.
    """
    planned = list(plan if plan is not None else build_plan(client))
    result = Collection()
    for request in planned:
        cache_path = client.raw_dir / f"{request.key}.json"
        if cache_path.exists():
            result.data[request.key] = json.loads(cache_path.read_text(encoding="utf-8"))
            result.cached.append(request.key)
        else:
            result.gaps.append(Gap(
                key=request.key,
                marker=UNAVAILABLE,
                reason="ещё не собрано (нет в кэше)",
                section=SECTIONS.get(request.action, ""),
            ))
    return result


def collect(
    client: Client,
    *,
    plan: Iterable[Request] | None = None,
    refresh: bool = False,
    probe: bool = True,
    session: Session | None = None,
    log: Callable[[str], None] = lambda message: None,
) -> Collection:
    """Run the plan, using the cache for anything already fetched.

    ``refresh`` re-fetches everything. ``probe`` saves the raw HTML of actions
    whose parser is missing, so the response can be parsed later without
    asking the site again.
    """
    client.ensure_dirs()
    planned = list(plan if plan is not None else build_plan(client))
    _check_cache_identity(client, refresh=refresh)

    result = Collection()
    api = _load_api()
    opened: Session | None = session
    last_call = 0.0

    for request in planned:
        cache_path = client.raw_dir / f"{request.key}.json"
        if cache_path.exists():
            if not refresh:
                result.data[request.key] = json.loads(cache_path.read_text(encoding="utf-8"))
                result.cached.append(request.key)
                continue
            # --refresh means the old answer is void — most often because the
            # birth time was rectified. Delete it before asking again: if this
            # request then fails (403, 500, network), leaving the file would
            # hand the previous chart's numbers to every later command, which
            # reads the cache and has no way to know they are stale.
            cache_path.unlink()

        func = api.get(API_NAMES.get(request.action, ""))
        section = SECTIONS.get(request.action, "")

        if func is None:
            html_path = None
            if probe:
                opened, last_call = _ensure_session(client, opened, last_call)
                html_path = _probe_html(client, opened, request, log=log)
                last_call = time.monotonic()
            result.gaps.append(Gap(
                key=request.key,
                marker=UNAVAILABLE,
                reason=(
                    f"парсер `{API_NAMES.get(request.action, request.action)}` "
                    f"ещё не реализован в vedic-parser"
                    + (f"; сырой HTML сохранён в {html_path.relative_to(client.root)}"
                       if html_path else "")
                ),
                section=section,
                html_saved=html_path,
            ))
            continue

        opened, last_call = _ensure_session(client, opened, last_call)
        log(f"  → {request.key}")
        try:
            payload = _call(func, opened, client.chart, request.params)
        except AccessDenied:
            result.gaps.append(Gap(request.key, PAID, "сайт отвечает 403: платный доступ", section))
            last_call = time.monotonic()
            continue
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 429:
                _write_cache_identity(client)
                raise RateLimited(
                    f"сайт ограничил частоту запросов на {request.key}. "
                    f"Собрано {len(result.fetched) + len(result.cached)} из {len(planned)}; "
                    "всё уже полученное закэшировано — повторите запуск позже, "
                    "он продолжит с этого места. Увеличьте collect.throttle в chart.yaml."
                ) from error
            result.gaps.append(Gap(request.key, UNAVAILABLE, f"HTTP {status}", section))
            last_call = time.monotonic()
            continue
        except requests.RequestException as error:
            result.gaps.append(Gap(request.key, UNAVAILABLE, f"сеть: {error}", section))
            last_call = time.monotonic()
            continue
        except VedicHoroError as error:
            result.gaps.append(Gap(request.key, UNAVAILABLE, f"ошибка запроса: {error}", section))
            last_call = time.monotonic()
            continue
        last_call = time.monotonic()

        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result.data[request.key] = payload
        result.fetched.append(request.key)

    _write_cache_identity(client)
    return result


# ---------------------------------------------------------------------------


def _load_api() -> dict[str, Callable[..., Any]]:
    """Every public callable ``vedic_parser.api`` currently offers."""
    from vedic_parser import api as api_module

    return {
        name: value
        for name, value in vars(api_module).items()
        if callable(value) and not name.startswith("_")
    }


def _call(
    func: Callable[..., Any], session: Session, chart: Chart, params: dict[str, Any]
) -> dict[str, Any]:
    """Call an api function passing only the parameters it actually accepts.

    Parsers written later may take fewer arguments than the plan carries
    (``show-sade-sati`` has no ``divisional``, say), so the signature decides
    rather than a hardcoded table that would need updating in step with them.
    """
    accepted = inspect.signature(func).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in accepted.values()):
        usable = dict(params)
    else:
        usable = {name: value for name, value in params.items() if name in accepted}
    return func(session, chart, **usable)


def _http_session(retries: int = 2) -> requests.Session:
    """A transport that rides out a hiccup but never hangs on a real limit.

    ``vedic_parser`` deliberately has no retries of its own and takes an
    injected transport for exactly this. Two details are deliberate:

    * ``allowed_methods`` — every actions.php call is a POST, which urllib3
      would otherwise refuse to retry at all.
    * ``respect_retry_after_header=False`` — the site answers a sustained 429
      with a Retry-After of many minutes, and honouring it turns the sweep
      into a silent twenty-minute sleep. Bounded backoff instead lets a real
      limit surface as :class:`RateLimited`, which says what happened and
      leaves a resumable cache behind.
    """
    policy = Retry(
        total=retries,
        backoff_factor=3.0,           # 3s, 6s
        backoff_max=30,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=False,
        raise_on_status=False,
    )
    http = requests.Session()
    adapter = HTTPAdapter(max_retries=policy)
    http.mount("https://", adapter)
    http.mount("http://", adapter)
    return http


def _ensure_session(
    client: Client, session: Session | None, last_call: float
) -> tuple[Session, float]:
    """Open the session on first use, and keep the courtesy pause between calls."""
    if session is None:
        session = Session(lang=client.collect.lang, http=_http_session(),
                          timeout=client.collect.timeout)
        session.open()
        return session, time.monotonic()
    wait = client.collect.throttle - (time.monotonic() - last_call)
    if wait > 0:
        time.sleep(wait)
    return session, last_call


def _probe_html(
    client: Client, session: Session, request: Request, *, log: Callable[[str], None]
) -> Path | None:
    """Save an unparsed response so it can serve as a fixture later."""
    html_dir = client.raw_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    path = html_dir / f"{request.key}.html"
    if path.exists():
        return path  # снимок HTML привязан к тем же параметрам, что и кэш JSON
    params = {
        key: str(value)
        for key, value in request.params.items()
        if key != "from_" and value not in ("", None)
    }
    log(f"  ⋯ {request.key} (парсера нет, снимаю HTML)")
    try:
        html = session.action(request.action, client.chart, **params)
    except VedicHoroError:
        return None
    path.write_text(html, encoding="utf-8")
    return path


def _parser_version() -> str:
    """Version of vedic-parser, so a cache never outlives the code that wrote it.

    A parser that starts reading a response differently makes every cached
    response from before it suspect. That is not hypothetical: a version that
    mis-assigned the columns of the planets table did not fail, it silently
    shifted every value after Navamsa by one, and the wrong numbers sat in the
    cache looking exactly like right ones.
    """
    try:
        from importlib.metadata import version

        return version("vedic-parser")
    except Exception:
        return "unknown"


def _identity(client: Client) -> dict[str, str]:
    chart = client.chart
    return {
        "date": chart.date, "time": chart.time, "timezone": chart.timezone,
        "latitude": chart.latitude, "longitude": chart.longitude,
        "lang": client.collect.lang,
        "parser": _parser_version(),
    }


def _check_cache_identity(client: Client, *, refresh: bool) -> None:
    """Refuse to mix responses computed for two different charts.

    A rectified birth time changes every number in the cache, so the cache
    key is the chart itself.
    """
    marker = client.raw_dir / "_chart.json"
    if not marker.exists():
        return
    stored = json.loads(marker.read_text(encoding="utf-8"))
    if stored == _identity(client) or refresh:
        return
    changed = [k for k, v in _identity(client).items() if stored.get(k) != v]
    if changed == ["parser"]:
        raise VedicHoroError(
            f"кэш собран парсером версии {stored.get('parser')}, установлена "
            f"{_parser_version()}. Разбор ответов мог измениться — запустите "
            "с --refresh, чтобы пересобрать."
        )
    raise VedicHoroError(
        "кэш собран для других параметров карты (изменилось: "
        f"{', '.join(changed)}). Запустите с --refresh, чтобы пересобрать."
    )


def _write_cache_identity(client: Client) -> None:
    (client.raw_dir / "_chart.json").write_text(
        json.dumps(_identity(client), ensure_ascii=False, indent=2), encoding="utf-8"
    )
