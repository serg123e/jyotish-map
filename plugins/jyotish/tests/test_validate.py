"""The checklist must never pass an item it did not actually check."""

from __future__ import annotations

from pathlib import Path

import pytest

from jyotish import validate
from jyotish.client import Client
from jyotish.patterns import Confirmation, Pattern
from jyotish.validate import (
    AUTO,
    CHECKS,
    FAIL,
    JUDGE,
    MANUAL,
    PASS,
    SKIP,
    WARN,
    review,
    terminology_share,
)

CHART = {
    "slug": "t", "date": "07.08.1983", "time": "23:00:00", "timezone": "+4",
    "latitude": "55.45", "longitude": "37.37",
}

SOUL_CHAPTER = """
## 15. Пройденный путь души

**58%**

> 0% не означает «плохой человек», 100% не означает «лучшая душа».

| Слой | Вес | Балл | Вклад |
|---|---|---|---|
| D1 | 20% | 60 | 12.0 |
"""

REPORT = """
# Отчёт

## 2. Десять паттернов

Опора 78. Это может, например, проявляться так: вы берётесь за задачу сами.
Список йог здесь — данные, а не доказательство.

## 6. Здоровье

Тенденция к перегрузке. При любых симптомах приоритет у врача, не у карты.

## 16. Камни

Сначала таблица функциональных ролей планет, затем назначение.
Основной камень подбирается после неё.
""" + SOUL_CHAPTER


def _client(tmp_path: Path, status: str = "documented", biography: bool = False) -> Client:
    client = Client.from_dict({**CHART, "birth_time": {"status": status}}, tmp_path)
    client.ensure_dirs()
    if biography:
        client.biography_md.write_text("работает врачом", encoding="utf-8")
    return client


def _patterns(**kwargs) -> list[Pattern]:
    defaults = dict(
        opora=70, confidence="средняя",
        confirmations=[Confirmation(layer, "показатель")
                       for layer in ("d1", "lordship", "varga")],
        contradictions=["смягчающий фактор"], meaning="смысл",
    )
    defaults.update(kwargs)
    return [Pattern(number=n, name=f"П{n}", **defaults) for n in range(1, 11)]


def _by_number(results, number: int):
    return next(r for r in results if r.check.number == number)


# ---- the shape of the report ------------------------------------------------


def test_every_one_of_the_27_checks_comes_back(tmp_path: Path) -> None:
    results = review(_client(tmp_path), REPORT, chart_patterns=_patterns())
    assert len(results) == 27
    assert [r.check.number for r in results] == list(range(1, 28))


def test_judgement_items_are_marked_not_silently_passed(tmp_path: Path) -> None:
    results = review(_client(tmp_path), REPORT, chart_patterns=_patterns())
    for result in results:
        if result.check.kind == JUDGE:
            assert result.status == MANUAL, f"пункт {result.check.number} тихо прошёл"


def test_nothing_is_checked_when_there_is_no_report(tmp_path: Path) -> None:
    results = review(_client(tmp_path), None, chart_patterns=None)
    assert not any(r.status == PASS and r.check.kind == AUTO and r.check.number in (13, 25)
                   for r in results)


# ---- scales -----------------------------------------------------------------


def test_opora_written_as_a_percentage_fails(tmp_path: Path) -> None:
    """«Опора» and the soul-path percentage are different scales."""
    bad = REPORT.replace("Опора 78.", "Опора: 78%.")
    results = review(_client(tmp_path), bad, chart_patterns=_patterns())
    assert _by_number(results, 15).status == FAIL


def test_opora_as_a_plain_number_passes(tmp_path: Path) -> None:
    results = review(_client(tmp_path), REPORT, chart_patterns=_patterns())
    assert _by_number(results, 15).status == PASS


def test_soul_scale_leaking_into_another_chapter_fails(tmp_path: Path) -> None:
    leaked = REPORT.replace(
        "## 6. Здоровье", "## 6. Здоровье\n\nПройденность пути души: 58%.\n"
    )
    results = review(_client(tmp_path), leaked, chart_patterns=_patterns())
    assert _by_number(results, 16).status == FAIL


def test_missing_layer_table_fails(tmp_path: Path) -> None:
    without = REPORT.replace("| Слой | Вес | Балл | Вклад |", "| Что-то | Иное |")
    results = review(_client(tmp_path), without, chart_patterns=_patterns())
    assert _by_number(results, 17).status == FAIL


def test_missing_caveat_fails(tmp_path: Path) -> None:
    without = REPORT.replace("> 0% не означает «плохой человек», 100% не означает «лучшая душа».", "")
    results = review(_client(tmp_path), without, chart_patterns=_patterns())
    assert _by_number(results, 18).status == FAIL


def test_soul_chapter_without_a_confirmed_birth_time_fails(tmp_path: Path) -> None:
    """The one check that catches the gate being walked around."""
    results = review(_client(tmp_path, "relatives"), REPORT, chart_patterns=_patterns())
    result = _by_number(results, 19)
    assert result.status == FAIL and "не выполняется вовсе" in result.detail


def test_no_soul_chapter_with_an_unconfirmed_time_is_correct(tmp_path: Path) -> None:
    text = REPORT.replace(SOUL_CHAPTER, "")
    results = review(_client(tmp_path, "relatives"), text, chart_patterns=_patterns())
    assert _by_number(results, 19).status == PASS


# ---- patterns ----------------------------------------------------------------


def test_thin_patterns_fail_check_one(tmp_path: Path) -> None:
    thin = _patterns(confirmations=[Confirmation("d1", "одно и то же"),
                                    Confirmation("d1", "оно же иначе")])
    results = review(_client(tmp_path), REPORT, chart_patterns=thin)
    assert _by_number(results, 1).status == FAIL


def test_patterns_without_contradictions_warn(tmp_path: Path) -> None:
    results = review(_client(tmp_path), REPORT, chart_patterns=_patterns(contradictions=[]))
    assert _by_number(results, 2).status == WARN


def test_pattern_contradicted_by_biography_must_be_rewritten(tmp_path: Path) -> None:
    contradicted = _patterns(
        verification="противоречит известным фактам", verification_facts=["факт"]
    )
    results = review(_client(tmp_path, biography=True), REPORT, chart_patterns=contradicted)
    assert _by_number(results, 10).status == FAIL


def test_pattern_checks_are_skipped_not_passed_without_patterns(tmp_path: Path) -> None:
    results = review(_client(tmp_path), REPORT, chart_patterns=None)
    assert _by_number(results, 1).status == SKIP


# ---- karakas ------------------------------------------------------------------


def test_karaka_mismatch_surfaces_as_a_warning(tmp_path: Path) -> None:
    derived = {"karakas": {"computed": {"AK": "Ma"}, "mismatches": ["AK: расчёт Ma, сайт Su"]}}
    results = review(_client(tmp_path), REPORT, chart_patterns=_patterns(), derived=derived)
    assert _by_number(results, 6).status == WARN


def test_karaka_agreement_passes(tmp_path: Path) -> None:
    derived = {"karakas": {"computed": {"AK": "Su"}, "mismatches": [], "near_ties": []}}
    results = review(_client(tmp_path), REPORT, chart_patterns=_patterns(), derived=derived)
    assert _by_number(results, 6).status == PASS


# ---- safety and readability ----------------------------------------------------


def test_frightening_wording_is_flagged(tmp_path: Path) -> None:
    scary = REPORT + "\n\nЭто неизбежно, и вас ждёт беда.\n"
    results = review(_client(tmp_path), scary, chart_patterns=_patterns())
    assert _by_number(results, 20).status == WARN


def test_roles_table_before_the_stones_passes(tmp_path: Path) -> None:
    """The chapter heading «Камни» precedes its own table — that is not a fault."""
    results = review(_client(tmp_path), REPORT, chart_patterns=_patterns())
    assert _by_number(results, 22).status == PASS


def test_a_chapter_about_stones_that_assigns_none_is_not_judged(tmp_path: Path) -> None:
    text = REPORT.replace("Основной камень подбирается после неё.", "")
    results = review(_client(tmp_path), text, chart_patterns=_patterns())
    assert _by_number(results, 22).status == SKIP


def test_stones_before_the_roles_table_fails(tmp_path: Path) -> None:
    reordered = REPORT.replace(
        "Сначала таблица функциональных ролей планет, затем назначение.\nОсновной камень подбирается после неё.",
        "Основной камень — жёлтый сапфир.\nТаблица функциональных ролей приводится ниже.",
    )
    results = review(_client(tmp_path), reordered, chart_patterns=_patterns())
    assert _by_number(results, 22).status == FAIL


def test_health_section_without_medical_precedence_fails(tmp_path: Path) -> None:
    without = REPORT.replace("При любых симптомах приоритет у врача, не у карты.", "")
    results = review(_client(tmp_path), without, chart_patterns=_patterns())
    assert _by_number(results, 24).status == FAIL


def test_terminology_share_counts_stems_not_exact_words() -> None:
    share, total = terminology_share("В накшатре Ашлеша Луна образует йогу с Сатурном")
    assert total == 8
    assert share > 0


def test_a_terminology_heavy_text_fails(tmp_path: Path) -> None:
    dense = REPORT + "\n\n" + " ".join(
        ["накшатра варга навамша даша лагна граха бхава аштакаварга шадбала карака"] * 20
    )
    results = review(_client(tmp_path), dense, chart_patterns=_patterns())
    assert _by_number(results, 25).status == FAIL


def test_a_plain_language_text_passes(tmp_path: Path) -> None:
    results = review(_client(tmp_path), REPORT, chart_patterns=_patterns())
    assert _by_number(results, 25).status == PASS


# ---- the rendered document -------------------------------------------------------


def test_rendered_checklist_shows_the_manual_items(tmp_path: Path) -> None:
    results = review(_client(tmp_path), REPORT, chart_patterns=_patterns())
    text = validate.render(results)
    assert "передано читателю" in text
    assert "нерешаемые машиной" in text
    for check in CHECKS:
        assert check.text in text


def test_failures_get_their_own_section(tmp_path: Path) -> None:
    results = review(_client(tmp_path, "relatives"), REPORT, chart_patterns=_patterns())
    text = validate.render(results)
    assert "## Провалы — исправить до вёрстки" in text


# ---- the table must survive a multi-line detail ----------------------------


def test_a_multiline_detail_stays_inside_its_cell() -> None:
    """A YAML note spans several lines; a newline in a cell ends the row."""
    from jyotish.validate import BY_NUMBER, MANUAL, Result, render

    text = render([Result(BY_NUMBER[19], MANUAL, "первая строка\nвторая строка\n\nтретья")])
    rows = [line for line in text.splitlines() if line.startswith("| 19 ")]
    assert len(rows) == 1
    assert rows[0].endswith("|")
    assert "первая строка вторая строка третья" in rows[0]


def test_a_pipe_in_a_detail_does_not_add_a_column() -> None:
    from jyotish.validate import BY_NUMBER, MANUAL, Result, render

    text = render([Result(BY_NUMBER[19], MANUAL, "а | б")])
    row = next(line for line in text.splitlines() if line.startswith("| 19 "))
    assert row.count("|") - row.count(r"\|") == 6   # шесть границ ячеек, и ни одной лишней
    assert r"а \| б" in row


def test_the_phrase_functional_malefic_is_not_a_roles_table(tmp_path: Path) -> None:
    """«функциональный вредитель» appears in any reading — it proves nothing.

    Matching the bare word made check 22 pass no matter where the table was,
    which is the same vacuous match that was already fixed on the stones side.
    """
    from jyotish.validate import _roles_table_at

    assert _roles_table_at("меркурий здесь функциональный вредитель.") == -1
    assert _roles_table_at("| планета | функциональная роль |\n") == 0
    assert _roles_table_at("сначала таблица функциональных ролей") == 8


def test_stones_after_a_real_roles_table_pass(tmp_path: Path) -> None:
    text = (
        "## Функции планет\n\n"
        "| Планета | Функциональная роль |\n|---|---|\n| Ve | йогакарака |\n\n"
        "## Камни\n\nОсновной камень — алмаз.\n"
    )
    results = review(_client(tmp_path), text, chart_patterns=_patterns())
    assert _by_number(results, 22).status == PASS


def test_stones_with_only_the_phrase_functional_malefic_fail(tmp_path: Path) -> None:
    text = "Меркурий — функциональный вредитель.\n\n## Камни\n\nОсновной камень — алмаз.\n"
    results = review(_client(tmp_path), text, chart_patterns=_patterns())
    assert _by_number(results, 22).status == FAIL
