"""Typesetting is where the three scales got mixed up; these are the traps that fired."""

from __future__ import annotations

from pathlib import Path

import pytest

from jyotish import report
from jyotish.report import BuildError, build, convert, repaginate


# ---- the three visual types --------------------------------------------------


def test_opora_becomes_a_chip_and_never_a_percentage() -> None:
    html = convert("### 3. Название паттерна — опора 78\n\n**Опора 78 · уверенность высокая · подтверждено биографией**\n")
    assert html.count('<span class="chip">опора 78</span>') == 2
    assert "78%" not in html
    assert 'class="bio-tag"' in html and 'class="tag-high"' in html


def test_scored_top_lists_get_badges_and_bars() -> None:
    html = convert("1. Первое — ценность 90\n2. Второе — ценность 80\n3. Третье — балл 70\n")
    assert '<ol class="badge-list">' in html
    assert 'style="width:90%"' in html and 'style="width:70%"' in html


def test_a_plain_numbered_list_stays_plain() -> None:
    html = convert("1. Первое\n2. Второе\n")
    assert "badge-list" not in html and "<ol>" in html


def test_the_soul_meter_appears_only_inside_its_chapter() -> None:
    inside = convert("## 15. Пройденность пути души\n\n### Ваш показатель: 64.8%\n")
    outside = convert("## 21. Итоги\n\n### Ваш показатель: 64.8%\n")
    assert 'class="soul-meter"' in inside and "64.8" in inside
    assert "soul-meter" not in outside


def test_an_h3_inside_the_soul_chapter_does_not_switch_the_meter_off() -> None:
    """The flag was reassigned on every heading once; the figure came after an h3."""
    html = convert("## 15. Пройденность пути души\n\n### Как это считалось\n\nтекст\n\n### Ваш показатель: 58%\n")
    assert "soul-meter" in html


# ---- tables and stones -------------------------------------------------------


def test_tables_get_a_real_thead_and_score_bars() -> None:
    html = convert("| # | Ресурс | Балл |\n|---|---|---|\n| 1 | Выносливость | 95 |\n")
    assert "<thead><tr><th>#</th>" in html
    assert 'style="width:95%"' in html
    assert "<tbody>" in html


def test_stone_categories_are_colour_banded() -> None:
    html = convert("## 16. Камни\n\n### Основной камень\n\nРубин.\n\n### Чего не носить и почему\n\nСиний сапфир.\n\n## 17. Ароматы\n")
    assert '<div class="stone stone-main">' in html
    assert '<div class="stone stone-avoid">' in html
    assert html.count("</div>") >= 2


# ---- dividers and chapters ---------------------------------------------------


def test_a_divider_before_a_chapter_heading_is_dropped() -> None:
    assert "divider" not in convert("текст\n\n---\n\n## 4. Глава\n")
    assert "divider" in convert("текст\n\n---\n\nещё текст\n")


def test_numbered_chapters_start_a_new_page() -> None:
    html = convert("## 4. Глава\n\n## Закрытие\n")
    assert '<h2 class="section-break">4. Глава</h2>' in html
    assert "<h2>Закрытие</h2>" in html


# ---- the contents ------------------------------------------------------------


def _reading(tmp_path: Path, text: str) -> Path:
    (tmp_path / "report.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_repaginate_touches_only_the_contents(tmp_path: Path) -> None:
    """The risk table has rows shaped exactly like contents rows."""
    root = _reading(tmp_path,
        "# О\n\n## Оглавление\n\n| | Раздел | Стр. |\n|---|---|---|\n| 1 | Первая | 9 |\n\n"
        "## 1. Первая\n\n| # | Риск | Балл |\n|---|---|---|\n| 1 | Поздно к врачу | 90 |\n")
    assert repaginate(root, {1: 3}) == 1
    text = (root / "report.md").read_text(encoding="utf-8")
    assert "| 1 | Первая | 3 |" in text
    assert "| 1 | Поздно к врачу | 90 |" in text


def test_repaginate_writes_the_contents_from_the_headings(tmp_path: Path) -> None:
    root = _reading(tmp_path, "# О\n\nвступление\n\n## 1. Первая\n\nт\n\n## 2. Вторая\n\nт\n")
    assert repaginate(root, {1: 3, 2: 5}) == 2
    text = (root / "report.md").read_text(encoding="utf-8")
    assert text.index("## Оглавление") < text.index("## 1. Первая")
    assert "| 2 | Вторая | 5 |" in text
    assert repaginate(root, {1: 3, 2: 5}) == 0          # idempotent


def test_a_report_with_a_repeated_chapter_is_refused(tmp_path: Path) -> None:
    root = _reading(tmp_path, "# О\n\n## 3. Сферы\n\nт\n\n## 4. История\n\nт\n\n## 3. Сферы\n\nт\n")
    with pytest.raises(BuildError, match="глава 3 встречается повторно"):
        build(root)


def test_build_writes_the_page_with_the_cover(tmp_path: Path) -> None:
    root = _reading(tmp_path, "# Разбор карты\n\n### Иван\n\n**1 января 1990 · Москва**\n\n## 1. Первая\n\nтекст\n")
    page = build(root)
    html = page.read_text(encoding="utf-8")
    assert '<div class="cover">' in html and "Иван" in html
    assert "<style>" in html and "section-break" in html


def test_a_missing_report_says_where_stage_09_writes(tmp_path: Path) -> None:
    with pytest.raises(BuildError, match="этап 09"):
        build(tmp_path)


def test_chapter_pages_never_fails_silently(tmp_path: Path, monkeypatch, capsys) -> None:
    """Without pypdfium2 the contents cannot be checked, and it must say so."""
    import builtins

    real_import = builtins.__import__

    def no_pdfium(name, *args, **kwargs):
        if name == "pypdfium2":
            raise ImportError
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pdfium)
    assert report.chapter_pages(tmp_path / "x.pdf", {1: "Первая"}) == {}
    assert "pypdfium2" in capsys.readouterr().err
