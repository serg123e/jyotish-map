"""Command line front end.

    jyotish new ivan                 # create clients/ivan/chart.yaml to fill in
    jyotish collect clients/ivan     # stage 01: fetch, derive, write both files
    jyotish status clients/ivan      # what is collected, what is missing
    jyotish soul-path clients/ivan   # stage 07: weights x scores, refuses if the gate is shut
    jyotish crosscheck clients/ivan  # recompute locally and report every disagreement
    jyotish check clients/ivan       # stage 10: the checklist, as far as code can take it
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from vedic_parser.session import VedicHoroError

from . import crosscheck, patterns, render_raw, soul_path, validate
from .client import Client, ConfigError, scaffold
from .collect import RateLimited, build_plan, collect, from_cache
from .derive import derive_all
from .text import number

DEFAULT_CLIENTS_DIR = Path("clients")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jyotish", description="Конвейер разбора карты Джйотиш."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    new_cmd = sub.add_parser("new", help="создать каталог разбора с chart.yaml")
    new_cmd.add_argument("slug", help="короткое имя разбора, оно же имя каталога")
    new_cmd.add_argument("--dir", default=None, help=f"куда (по умолчанию {DEFAULT_CLIENTS_DIR}/<slug>)")
    new_cmd.set_defaults(handler=_cmd_new)

    collect_cmd = sub.add_parser("collect", help="этап 01: собрать данные и записать экспорт")
    collect_cmd.add_argument("client", help="каталог разбора, например clients/ivan")
    collect_cmd.add_argument("--refresh", action="store_true",
                             help="перезапросить всё, игнорируя кэш")
    collect_cmd.add_argument("--no-probe", action="store_true",
                             help="не сохранять сырой HTML действий без парсера")
    collect_cmd.add_argument("--plan-only", action="store_true",
                             help="показать план запросов и выйти, ничего не запрашивая")
    collect_cmd.set_defaults(handler=_cmd_collect)

    status_cmd = sub.add_parser("status", help="что уже собрано и чего не хватает")
    status_cmd.add_argument("client")
    status_cmd.set_defaults(handler=_cmd_status)

    soul_cmd = sub.add_parser(
        "soul-path",
        help="этап 07: посчитать показатель из баллов слоёв (soul_path_input.json)",
    )
    soul_cmd.add_argument("client")
    soul_cmd.add_argument("--input", default=None,
                          help="файл с баллами (по умолчанию <client>/soul_path_input.json)")
    soul_cmd.add_argument("--template", action="store_true",
                          help="создать заготовку файла с баллами и выйти")
    soul_cmd.set_defaults(handler=_cmd_soul_path)

    cross_cmd = sub.add_parser(
        "crosscheck", help="сверить данные сайта с независимым локальным расчётом")
    cross_cmd.add_argument("client")
    cross_cmd.set_defaults(handler=_cmd_crosscheck)

    check_cmd = sub.add_parser("check", help="этап 10: чек-лист качества")
    check_cmd.add_argument("client")
    check_cmd.add_argument("--report", default=None,
                           help="файл отчёта (по умолчанию <client>/report.md)")
    check_cmd.set_defaults(handler=_cmd_check)

    return parser


def _cmd_new(args: argparse.Namespace) -> int:
    root = Path(args.dir) if args.dir else DEFAULT_CLIENTS_DIR / args.slug
    path = scaffold(root, args.slug)
    print(f"создан {path}")
    print("Заполните дату, время, координаты и статус времени рождения, затем:")
    print(f"  jyotish collect {root}")
    return 0


def _cmd_collect(args: argparse.Namespace) -> int:
    client = Client.load(args.client)
    plan = build_plan(client)

    if args.plan_only:
        print(f"{len(plan)} запросов, ~{len(plan) * client.collect.throttle / 60:.0f} мин "
              f"при throttle={client.collect.throttle}s")
        for request in plan:
            print(f"  {request.key}")
        return 0

    print(f"Разбор: {client.slug} — {client.chart.date} {client.chart.time} "
          f"({client.place or 'место не указано'})")
    print(f"{len(plan)} запросов, кэш в {client.raw_dir}")

    try:
        result = collect(client, refresh=args.refresh, probe=not args.no_probe,
                         log=lambda message: print(message, flush=True))
    except RateLimited as error:
        print(f"\n{error}", file=sys.stderr)
        return 2

    print(f"\nполучено {len(result.fetched)}, из кэша {len(result.cached)}, "
          f"пропусков {len(result.gaps)}")
    for gap in result.gaps:
        print(f"  ✗ {gap.key}: {gap.reason}")

    render_raw.write(client, result)
    print(f"\n{client.raw_data_md}")
    print(f"{client.missing_data_md}")
    print(f"{client.summaries_dir / '01.md'}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    client = Client.load(args.client)
    plan = build_plan(client)
    cached = {path.stem for path in client.raw_dir.glob("*.json") if path.stem != "_chart"}
    done = [r for r in plan if r.key in cached]
    todo = [r for r in plan if r.key not in cached]

    print(f"{client.slug}: собрано {len(done)} из {len(plan)}")
    print(f"время рождения: {client.birth_time.label}")
    print(f"биография: {'есть' if client.biography_md.exists() else 'НЕ ПРИСЛАНА'}")
    print(f"этап 07 (путь души): {'допустим' if client.birth_time.confirmed else 'закрыт гейтом'}")
    if todo:
        print(f"\nне собрано ({len(todo)}):")
        for request in todo:
            print(f"  {request.key}")
    return 0


SOUL_TEMPLATE = {
    "_": "Баллы 0–100 выставляет модель на этапе 07. Арифметику делает код: "
         "вклад = вес × балл ÷ 100. Обоснование у каждого слоя обязательно — "
         "балл без него Промпт 07 запрещает.",
    "layers": [
        {"key": key, "score": None, "rationale": ""}
        for key, _title, _weight, _what in soul_path.LAYERS
    ],
    "subscales": [
        {"key": key, "value": None, "explanation": ""}
        for key, _title, _note in soul_path.SUBSCALES
    ],
    "raised_by": "",
    "lowered_by": "",
}


def _cmd_soul_path(args: argparse.Namespace) -> int:
    client = Client.load(args.client)
    path = Path(args.input) if args.input else client.root / "soul_path_input.json"

    if args.template:
        if path.exists():
            raise ConfigError(f"{path} уже существует")
        path.write_text(json.dumps(SOUL_TEMPLATE, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"создан {path}")
        return 0

    collection = from_cache(client)
    available = soul_path.available_layers(collection.data)
    try:
        soul_path.check_gate(client, available)
    except soul_path.GateClosed as error:
        print(f"{error}", file=sys.stderr)
        return 3

    if not path.exists():
        print(f"нет файла с баллами: {path}\nсоздайте заготовку: "
              f"jyotish soul-path {args.client} --template", file=sys.stderr)
        return 1

    # soul_path_input.json is written by hand, so a malformed one is an
    # expected outcome and must read as a message, not a traceback.
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path}: это не JSON — {error}") from error
    try:
        scores = [
            soul_path.LayerScore(item["key"], item["score"], item.get("rationale", ""))
            for item in payload["layers"] if item.get("score") is not None
        ]
        subscales = [
            soul_path.Subscale(item["key"], item["value"], item.get("explanation", ""))
            for item in payload["subscales"] if item.get("value") is not None
        ]
    except (KeyError, TypeError) as error:
        raise ConfigError(
            f"{path}: не хватает поля {error}. Заготовку с нужной структурой даёт "
            f"`jyotish soul-path {args.client} --template`."
        ) from error
    result = soul_path.compute(
        client, scores, subscales, available=available,
        raised_by=payload.get("raised_by", ""), lowered_by=payload.get("lowered_by", ""),
    )

    client.ensure_dirs()
    (client.root / "soul_path.json").write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    chapter = client.stages_dir / "07.md"
    chapter.write_text(soul_path.render(result), encoding="utf-8")
    print(f"Пройденность пути души: {number(result.total)}%")
    for note in result.notes:
        print(f"  {note}")
    print(chapter)
    return 0


def _cmd_crosscheck(args: argparse.Namespace) -> int:
    client = Client.load(args.client)
    try:
        report = crosscheck.compare(client, from_cache(client).data)
    except crosscheck.CrossCheckUnavailable as error:
        print(f"{error}", file=sys.stderr)
        return 3

    path = client.root / "crosscheck.md"
    path.write_text(crosscheck.render(report), encoding="utf-8")
    conflicts = report.conflicts
    print(f"сверено пунктов {len(report.findings)}, расхождений {len(conflicts)}")
    for finding in conflicts:
        print(f"  ✗ {finding.subject}: {finding.site} против {finding.local}")
    print(path)
    return 1 if conflicts else 0


def _cmd_check(args: argparse.Namespace) -> int:
    client = Client.load(args.client)
    report_path = Path(args.report) if args.report else client.root / "report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    if report is None:
        print(f"отчёта нет ({report_path}) — проверяются только пункты, "
              "не требующие текста")

    patterns_path = client.state_dir / "patterns.json"
    chart_patterns = patterns.load(patterns_path) if patterns_path.exists() else None

    collection = from_cache(client)
    derived = None
    if collection.get("show-chart-D1") and collection.get("show-info-D1"):
        derived = derive_all(collection.get("show-chart-D1"), collection.get("show-info-D1"))

    results = validate.review(client, report, chart_patterns=chart_patterns, derived=derived)
    text = validate.render(results)
    (client.root / "qa.md").write_text(text, encoding="utf-8")

    failures = [r for r in results if r.failed]
    warnings = [r for r in results if r.status == validate.WARN]
    manual = [r for r in results if r.status == validate.MANUAL]
    print(f"провалов {len(failures)}, требуют внимания {len(warnings)}, "
          f"передано читателю {len(manual)}")
    for result in failures + warnings:
        print(f"  {result.status}: {result.check.number}. {result.check.text} — {result.detail}")
    print(client.root / "qa.md")
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (ConfigError, VedicHoroError, soul_path.ScoringError) as error:
        print(f"ошибка: {error}", file=sys.stderr)
        return 1
    except soul_path.GateClosed as error:
        print(f"{error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
