"""Stage 10: the 27-point checklist, as far as a machine can take it.

About half of Prompt 10's checks are formal — a required sentence is present or
it is not, a scale appears outside its chapter or it does not, a pattern has
three independent layers or it has two. Those are settled here.

The rest need judgement ("биография не подогнана под карту"). They are not
dropped and not silently passed: they come back marked as needing a reader,
because a checklist that quietly skips half its items is worse than no
checklist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import patterns as patterns_module
from .client import Client
from .soul_path import DISCLAIMER

AUTO = "авто"
JUDGE = "судья"

PASS = "прошло"
FAIL = "провал"
WARN = "внимание"
MANUAL = "нужен читатель"
SKIP = "неприменимо"

#: Words whose share Prompt 10 §25 caps at 20%. Stems, matched case-insensitively
#: against word starts, so «накшатре» and «накшатрой» both count.
TERM_STEMS = (
    "раши", "варг", "навамш", "дреккан", "шаштьямш", "вимшамш", "накшатр", "пад",
    "даш", "антардаш", "пратьянтардаш", "махадаш", "бхукти", "вимшоттар",
    "лагн", "лагнеш", "грах", "бхав", "аштакаварг", "бинду", "шадбал", "бал",
    "авастх", "йог", "карак", "атмакарак", "аргал", "дришт", "арудх", "упапад",
    "гандант", "паривартан", "экзальтац", "дебилитац", "мулатрикон", "кендр",
    "трикон", "дустхан", "марак", "бадхак", "ретроградн", "диспозитор",
    "сурья", "чандр", "мангал", "будх", "шукр", "шани", "раху", "кету",
    "джйотиш", "джаймини", "випарит", "нича-бханг", "махапуруш", "гочар",
    "саде-сати", "упай", "каракамш", "свамш", "сфут", "упаграх", "панчанг",
)

#: Phrasings Prompt 10 §20 exists to keep out. Flagged for a look, not failed
#: automatically — context decides, and a false alarm is cheap.
FRIGHTENING = (
    "обязательно произойдёт", "неизбежно", "вас ждёт беда", "грозит гибель",
    "смертельно опасн", "катастрофа неминуем", "не избежать", "обречён",
    "приговор", "фатальн",
)

#: Wordings that mark a stone actually being assigned, as opposed to the
#: chapter merely being about stones. Prompt 08 §1: the table of functional
#: roles must come first, and without this distinction the check is vacuous.
STONE_ASSIGNMENT = (
    "основной камень", "основные камни", "поддерживающий камень",
    "мягкий поддерживающий", "камень-заменитель", "рекомендованный камень",
    "минерал-заменитель",
)

#: Prompt 09 §"Правило примеров": the wording an unverified example must use.
HYPOTHETICAL = "может, например, проявляться"
HYPOTHETICAL_ALT = "это может проявляться так"


@dataclass(frozen=True)
class Check:
    number: int
    section: str
    text: str
    kind: str


@dataclass
class Result:
    check: Check
    status: str
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.status == FAIL


CHECKS: tuple[Check, ...] = (
    Check(1, "Доказательность", "У всех 10 паттернов ≥3 независимых подтверждения из разных слоёв", AUTO),
    Check(2, "Доказательность", "Для каждого сильного вывода искались опровергающие факторы", AUTO),
    Check(3, "Доказательность", "Йоги оценены по фактическому выполнению условий", JUDGE),
    Check(4, "Доказательность", "Автосписок йог не выдан за доказательную базу", AUTO),
    Check(5, "Доказательность", "Все числовые данные с vedic-horo, без самостоятельных пересчётов", AUTO),
    Check(6, "Доказательность", "Атмакарака перепроверена по наибольшему градусу", AUTO),
    Check(7, "Доказательность", "Не спутаны «дом размещения» и «управляемый дом»", JUDGE),
    Check(8, "Доказательность", "Не транспонированы строки Раху/Кету", AUTO),
    Check(9, "Честность", "Биография не подогнана под карту", JUDGE),
    Check(10, "Честность", "Гипотезы, противоречащие жизни, пересмотрены, а не оправданы", AUTO),
    Check(11, "Честность", "Собственные ошибки исправлены и открыто описаны", JUDGE),
    Check(12, "Честность", "Нет выдуманных примеров, поданных как факты", JUDGE),
    Check(13, "Честность", "Непроверенные примеры введены оборотом «может, например, проявляться»", AUTO),
    Check(14, "Честность", "Где данных нет — так и написано, без имитации глубины", AUTO),
    Check(15, "Шкалы", "Три шкалы не перепутаны и названы по-разному", AUTO),
    Check(16, "Шкалы", "Шкала пути души использована только в своей главе", AUTO),
    Check(17, "Шкалы", "Таблица слоёв с весами и вкладами показана читателю", AUTO),
    Check(18, "Шкалы", "Есть оговорка, что 0% ≠ «плохой человек»", AUTO),
    Check(19, "Шкалы", "Условие допуска к Промпту 07 соблюдено", AUTO),
    Check(20, "Безопасность", "Нет запугивающих предсказаний", AUTO),
    Check(21, "Безопасность", "Не создаётся зависимость от астрологии, ИИ, ритуалов, камней", JUDGE),
    Check(22, "Безопасность", "Камни назначены только после таблицы функциональных ролей", AUTO),
    Check(23, "Безопасность", "Нет медицинских, юридических или финансовых предписаний", JUDGE),
    Check(24, "Безопасность", "Приоритет медицины указан явно в разделе здоровья", AUTO),
    Check(25, "Читаемость", "Терминологии не больше 20%", AUTO),
    Check(26, "Читаемость", "Нет повторов одной мысли в разных разделах", JUDGE),
    Check(27, "Читаемость", "После прочтения понятно, что конкретно делать", JUDGE),
)

BY_NUMBER = {check.number: check for check in CHECKS}


def review(
    client: Client,
    report: str | None = None,
    *,
    chart_patterns: Sequence[patterns_module.Pattern] | None = None,
    derived: dict[str, Any] | None = None,
) -> list[Result]:
    """Run every check that can be run and mark the rest for a reader."""
    results: list[Result] = []
    biography = client.biography_md.exists()
    text = report or ""
    lower = text.lower()

    results += _pattern_checks(chart_patterns, biography=biography)
    results += _karaka_checks(derived)
    results += _scale_checks(client, text, lower)
    results += _text_checks(client, text, lower, chart_patterns)

    done = {result.check.number for result in results}
    for check in CHECKS:
        if check.number in done:
            continue
        results.append(Result(
            check, MANUAL,
            "смысловая проверка: автоматически не решается, нужен читатель или модель-судья"
            if check.kind == JUDGE else "нет данных для автоматической проверки",
        ))
    return sorted(results, key=lambda result: result.check.number)


# ---------------------------------------------------------------------------


def _pattern_checks(
    chart_patterns: Sequence[patterns_module.Pattern] | None, *, biography: bool
) -> list[Result]:
    if chart_patterns is None:
        return [
            Result(BY_NUMBER[1], SKIP, "паттерны ещё не собраны (нет patterns.json)"),
            Result(BY_NUMBER[2], SKIP, "паттерны ещё не собраны"),
            Result(BY_NUMBER[10], SKIP, "паттерны ещё не собраны"),
        ]
    findings = patterns_module.check(chart_patterns, biography=biography)

    thin = [f for f in findings if f.rule == "≥3 независимых"]
    results = [Result(
        BY_NUMBER[1],
        FAIL if thin else PASS,
        "; ".join(f.message for f in thin) if thin
        else f"все {len(chart_patterns)} паттернов опираются на ≥3 разных слоя",
    )]

    without = [p.name for p in chart_patterns if not p.contradictions]
    results.append(Result(
        BY_NUMBER[2],
        WARN if without else PASS,
        f"противоречащие показатели не найдены у: {', '.join(without)}" if without
        else "у каждого паттерна назван хотя бы один противоречащий показатель",
    ))

    contradicted = [p for p in chart_patterns
                    if p.verification == "противоречит известным фактам"]
    unrevised = [p.name for p in contradicted if not p.revised_from]
    results.append(Result(
        BY_NUMBER[10],
        FAIL if unrevised else PASS,
        f"противоречат биографии и не переписаны: {', '.join(unrevised)}" if unrevised
        else (f"пересмотрено паттернов: {len(contradicted)}" if contradicted
              else "паттернов, противоречащих биографии, нет"),
    ))
    return results


def _karaka_checks(derived: dict[str, Any] | None) -> list[Result]:
    if not derived or "karakas" not in derived:
        return [Result(BY_NUMBER[6], SKIP, "нет данных этапа 01")]
    karakas = derived["karakas"]
    mismatches = karakas.get("mismatches") or []
    ties = karakas.get("near_ties") or []
    if mismatches:
        return [Result(
            BY_NUMBER[6], WARN,
            "расчёт по градусам расходится с сайтом: " + "; ".join(mismatches)
            + ". Расхождение должно быть описано в отчёте, а не сглажено.",
        )]
    detail = f"Атмакарака {karakas.get('computed', {}).get('AK')} — расчёт совпал с сайтом"
    if ties:
        detail += f"; близкие градусы: {'; '.join(ties)}"
    return [Result(BY_NUMBER[6], PASS, detail)]


def _scale_checks(client: Client, text: str, lower: str) -> list[Result]:
    """The three scales, and the chapter the third one is confined to."""
    results: list[Result] = []
    chapters = _chapters(text)
    soul_chapter = _find_chapter(chapters, ("пут", "душ"))

    # 15: «опора» must never be written as a percentage.
    as_percent = re.findall(r"опор\w*[^.\n]{0,24}?\d+\s*%", lower)
    results.append(Result(
        BY_NUMBER[15],
        FAIL if as_percent else PASS,
        f"опора выражена в процентах: {as_percent[:3]}" if as_percent
        else "опора нигде не выражена в процентах",
    ))

    # 16: the soul-path scale belongs to its own chapter only.
    if soul_chapter is None:
        results.append(Result(BY_NUMBER[16], SKIP, "главы о пути души в тексте нет"))
        results.append(Result(BY_NUMBER[17], SKIP, "главы о пути души в тексте нет"))
        results.append(Result(BY_NUMBER[18], SKIP, "главы о пути души в тексте нет"))
    else:
        title, body = soul_chapter
        elsewhere = [
            other_title for other_title, other_body in chapters
            if other_title != title and re.search(r"пройденност|пут\w+ душ\w+\s*[:—-]?\s*\d+\s*%",
                                                  other_body.lower())
        ]
        results.append(Result(
            BY_NUMBER[16],
            FAIL if elsewhere else PASS,
            f"шкала пути души встречается вне своей главы: {', '.join(elsewhere)}"
            if elsewhere else "шкала используется только в своей главе",
        ))

        has_table = bool(re.search(r"\|\s*слой\s*\|", body.lower())) and "вклад" in body.lower()
        results.append(Result(
            BY_NUMBER[17],
            PASS if has_table else FAIL,
            "таблица слоёв с весами и вкладами на месте" if has_table
            else "нет таблицы слоёв: число без неё недопустимо",
        ))

        has_caveat = ("0%" in body and "плохой человек" in body.lower()) or DISCLAIMER in body
        results.append(Result(
            BY_NUMBER[18],
            PASS if has_caveat else FAIL,
            "оговорка на месте" if has_caveat
            else "нет обязательной оговорки «0% не означает „плохой человек“»",
        ))

    # 19: the admission rule — the chapter may exist only if the gate is open.
    if soul_chapter is None:
        results.append(Result(
            BY_NUMBER[19], PASS,
            f"главы нет; время рождения — {client.birth_time.label}"
            if not client.birth_time.confirmed
            else "гейт открыт, но глава не написана — этап 07 ещё не выполнен",
        ))
    elif client.birth_time.confirmed:
        results.append(Result(BY_NUMBER[19], PASS,
                              f"время рождения: {client.birth_time.label}"))
    else:
        results.append(Result(
            BY_NUMBER[19], FAIL,
            f"глава о пути души написана, но время рождения — {client.birth_time.label}. "
            "Промпт 07 при таком статусе не выполняется вовсе.",
        ))
    return results


def _text_checks(
    client: Client,
    text: str,
    lower: str,
    chart_patterns: Sequence[patterns_module.Pattern] | None,
) -> list[Result]:
    results: list[Result] = []
    if not text:
        for number in (4, 5, 8, 13, 14, 20, 22, 24, 25):
            results.append(Result(BY_NUMBER[number], SKIP, "текст отчёта ещё не собран"))
        return results

    # 4: the yoga list is data, not evidence — the caveat must be present.
    yoga_caveat = "доказатель" in lower and "йог" in lower
    results.append(Result(
        BY_NUMBER[4],
        PASS if yoga_caveat else WARN,
        "оговорка про автосписок йог найдена" if yoga_caveat
        else "в тексте нет оговорки, что список йог — данные, а не доказательство",
    ))

    # 5 and 8: structural guarantees of the pipeline, worth stating.
    results.append(Result(
        BY_NUMBER[5], PASS,
        "числовые данные приходят из vedic-horo; всё вычисленное здесь помечено "
        "[расчёт] в 01_RAW_DATA.md",
    ))
    results.append(Result(
        BY_NUMBER[8], PASS,
        "Раху и Кету приходят как именованные поля JSON, а не как строки таблицы — "
        "транспозиция структурно невозможна",
    ))

    # 13: unverified examples must announce themselves.
    unverified = (
        chart_patterns is None
        or any(p.verification == "не проверено" for p in chart_patterns)
    )
    marked = HYPOTHETICAL in lower or HYPOTHETICAL_ALT in lower
    results.append(Result(
        BY_NUMBER[13],
        PASS if (marked or not unverified) else WARN,
        "непроверенные примеры введены оборотом" if marked
        else "есть непроверенные паттерны, но оборота «может, например, проявляться» "
             "в тексте нет — проверьте, не поданы ли гипотезы как факты",
    ))

    # 14: gaps must be named as gaps.
    has_missing_file = client.missing_data_md.exists()
    results.append(Result(
        BY_NUMBER[14],
        PASS if has_missing_file else WARN,
        f"пробелы перечислены в {client.missing_data_md.name}" if has_missing_file
        else "нет файла MISSING_DATA: неясно, зафиксированы ли пробелы",
    ))

    # 20: frightening phrasings.
    found = sorted({phrase for phrase in FRIGHTENING if phrase in lower})
    results.append(Result(
        BY_NUMBER[20],
        WARN if found else PASS,
        f"формулировки, требующие проверки: {', '.join(found)}" if found
        else "запугивающих оборотов не найдено",
    ))

    # 22: the table of functional roles comes before any stone is assigned.
    # Matched against an actual recommendation, not the word "камни" — the
    # chapter heading always precedes the table that lives inside it, so a
    # bare word search would fail every correctly-ordered report.
    roles_at = lower.find("функциональн")
    stones_at = min(
        (position for position in
         (lower.find(marker) for marker in STONE_ASSIGNMENT) if position >= 0),
        default=-1,
    )
    if stones_at < 0:
        results.append(Result(BY_NUMBER[22], SKIP, "камни в тексте не назначаются"))
    elif roles_at < 0:
        results.append(Result(BY_NUMBER[22], FAIL,
                              "камни есть, таблицы функциональных ролей нет"))
    else:
        results.append(Result(
            BY_NUMBER[22],
            PASS if roles_at < stones_at else FAIL,
            "таблица функциональных ролей идёт до камней" if roles_at < stones_at
            else "камни назначены раньше таблицы функциональных ролей",
        ))

    # 24: medicine takes precedence, said out loud.
    medical = any(phrase in lower for phrase in
                  ("приоритет у врач", "приоритет медицин", "обратитесь к врач",
                   "не заменяет консультацию", "к профильному специалисту"))
    results.append(Result(
        BY_NUMBER[24],
        PASS if medical else FAIL,
        "приоритет медицины указан" if medical
        else "в разделе здоровья не указан приоритет врача — Промпт 04 требует явно",
    ))

    # 25: terminology share.
    share, total = terminology_share(text)
    results.append(Result(
        BY_NUMBER[25],
        PASS if share <= 20 else FAIL,
        f"доля терминов {share:.1f}% от {total} слов (порог 20%)",
    ))
    return results


def terminology_share(text: str) -> tuple[float, int]:
    """Percentage of words that are Jyotish terminology, and the word count."""
    words = re.findall(r"[а-яёa-z]+", text.lower())
    if not words:
        return 0.0, 0
    terms = sum(1 for word in words if word.startswith(TERM_STEMS))
    return terms / len(words) * 100, len(words)


def _chapters(text: str) -> list[tuple[str, str]]:
    """Split a report into (heading, body) at level-2 headings."""
    parts = re.split(r"^##\s+(.+)$", text, flags=re.MULTILINE)
    if len(parts) < 3:
        return [("", text)]
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def _find_chapter(
    chapters: Iterable[tuple[str, str]], needles: tuple[str, ...]
) -> tuple[str, str] | None:
    for title, body in chapters:
        lowered = title.lower()
        if all(needle in lowered for needle in needles):
            return title, body
    return None


def _cell(text: str) -> str:
    """One table cell, on one line.

    A detail can quote `chart.yaml`, and a YAML note is often several lines —
    a newline inside a Markdown cell silently ends the row, so the rest of the
    table shifts and the checklist becomes unreadable at exactly the moment it
    reports something. A bare pipe does the same to the columns.
    """
    return " ".join(text.split()).replace("|", "\\|")


def render(results: Sequence[Result]) -> str:
    """The checklist as a document, with the manual items still visible."""
    counts = {status: sum(1 for r in results if r.status == status)
              for status in (PASS, FAIL, WARN, MANUAL, SKIP)}
    lines = [
        "# Контроль качества (Промпт 10)",
        "",
        f"Проверено автоматически: {counts[PASS] + counts[FAIL] + counts[WARN]} из "
        f"{len(results)}. Провалов: {counts[FAIL]}, требуют внимания: {counts[WARN]}, "
        f"передано читателю: {counts[MANUAL]}, неприменимо: {counts[SKIP]}.",
        "",
        "Пункты со статусом «нужен читатель» — не пройденные, а нерешаемые машиной. "
        "Их обязан пройти человек или модель-судья.",
        "",
        "| № | Раздел | Пункт | Статус | Комментарий |",
        "|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| {result.check.number} | {_cell(result.check.section)} | "
            f"{_cell(result.check.text)} | {result.status} | {_cell(result.detail)} |"
        )
    failures = [r for r in results if r.failed]
    if failures:
        lines += ["", "## Провалы — исправить до вёрстки", ""]
        lines += [f"{r.check.number}. **{r.check.text}** — {' '.join(r.detail.split())}"
                  for r in failures]
    return "\n".join(lines).rstrip() + "\n"
