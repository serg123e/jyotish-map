"""Stage 10 typesetting: report.md to the HTML of the template, then to PDF.

Typesetting was the one manual step left in the pipeline, and a manual step
in a pipeline that exists to stop mistakes is where mistakes come back. The
report and the template that ships with the skill go in; out comes the page
with the three visual types Prompt 10 requires:

* «опора N» becomes a chip beside the pattern heading, never a percentage;
* ТОП-lists with scores get a numbered badge and a bar;
* the soul-path figure gets the large meter — and only inside its own chapter.

Stone blocks are coloured by the three categories of Prompt 08. The contents
are generated from the chapter headings and the real page numbers of the
printed PDF, in two passes. A report whose chapters repeat or run backwards
is refused: the first PDF went out with three chapters printed twice.

    jyotish build clients/ivan
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .validate import chapter_sequence_problems

#: The template ships with the skill, next to the prompts. The package is
#: installed editable by the launcher, so the relative path holds; a
#: non-editable install can point at it with JYOTISH_TEMPLATE.
TEMPLATE = Path(os.environ.get("JYOTISH_TEMPLATE") or (
    Path(__file__).resolve().parent.parent / "skills" / "jyotish-reading" /
    "assets" / "11_Шаблон_вёрстки.html"))

#: Prompt 08 splits stones into three categories and Prompt 10 asks for them
#: to be colour-banded. Keyed by heading, lowercased.
STONE_CATEGORIES = {
    "основной камень": "stone-main",
    "основные камни": "stone-main",
    "мягкий поддерживающий": "stone-soft",
    "чего не носить и почему": "stone-avoid",
    "без дополнительной проверки не использовать": "stone-avoid",
}

#: Headings that open a chapter needing a page of its own.
PAGE_BREAK = re.compile(r"^\d+\.\s")


def inline(text: str) -> str:
    """Bold, italic, code and the scale tags — after escaping."""
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"<em>\1</em>", out)
    out = re.sub(r"уверенность\s+высокая", '<span class="tag-high">уверенность высокая</span>', out)
    out = re.sub(r"уверенность\s+средняя", '<span class="tag-med">уверенность средняя</span>', out)
    out = re.sub(r"уверенность[:\s]+гипотеза", '<span class="tag-low">уверенность: гипотеза</span>', out)
    out = re.sub(r"подтверждено биографией",
                 '<span class="bio-tag">подтверждено биографией</span>', out)
    return out


def bar(score: int) -> str:
    return (f'<span class="bar"><span class="bar-track">'
            f'<span class="bar-fill" style="width:{min(score, 100)}%"></span></span>'
            f'<span class="bar-num">{score}</span></span>')


def heading(level: int, text: str) -> str:
    """A heading, with «опора N» lifted out into a chip."""
    chip = ""
    match = re.search(r"\bопора\s+(\d{1,3})\b", text, re.IGNORECASE)
    if match:
        chip = f'<span class="chip">опора {match.group(1)}</span>'
        text = (text[:match.start()] + text[match.end():]).strip(" ·—-")
    klass = ' class="section-break"' if level == 2 and PAGE_BREAK.match(text) else ""
    return f"<h{level}{klass}>{inline(text)}{chip}</h{level}>"


def soul_meter(value: float) -> str:
    return (f'<div class="soul-meter"><div class="soul-num">{value:g}'
            f'<small>%</small></div>'
            f'<div class="soul-label">ПРОЙДЕННОСТЬ ПУТИ ДУШИ</div>'
            f'<div class="soul-track"><div class="soul-fill" '
            f'style="width:{value:g}%"></div></div>'
            f'<div class="soul-scale"><span>0 — наиболее напряжённая конфигурация</span>'
            f'<span>100 — наиболее зрелая</span></div></div>')


#: Column headers whose cells are a 0–100 score and deserve a bar. Prompt 10
#: asks for «круглый бейдж + шкала» on the top-lists, and in this report the
#: top-lists are tables rather than numbered lists.
SCORE_COLUMNS = ("балл", "ценность", "опора")


def table(rows: list[str], klass: str = "") -> str:
    """A Markdown table, with the separator row dropped and scores barred."""
    cells = [[c.strip() for c in row.strip().strip("|").split("|")] for row in rows]
    body = [r for r in cells if not all(re.fullmatch(r":?-{2,}:?", c) for c in r)]
    if not body:
        return ""
    header = body[0]
    scored = {i for i, name in enumerate(header)
              if any(word in name.lower() for word in SCORE_COLUMNS)}
    attr = f' class="{klass}"' if klass else ""
    # A real <thead> so the header repeats when a long table breaks across
    # pages. Without it a two-page table loses its column names on page two.
    out = [f"<table{attr}>", "<thead><tr>"
           + "".join(f"<th>{inline(c)}</th>" for c in header) + "</tr></thead>", "<tbody>"]
    for row in body[1:]:
        tds = []
        for i, cell in enumerate(row):
            plain = cell.strip("* ")
            if i in scored and re.fullmatch(r"\d{1,3}", plain):
                tds.append(f"<td>{bar(int(plain))}</td>")
            else:
                tds.append(f"<td>{inline(cell)}</td>")
        out.append("<tr>" + "".join(tds) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def convert(md: str) -> str:
    """Markdown to the body HTML the template expects."""
    lines = md.splitlines()
    out: list[str] = []
    buffer: list[str] = []          # paragraph
    rows: list[str] = []            # table
    items: list[str] = []           # list
    ordered = False
    quote: list[str] = []
    in_soul_chapter = False
    stone_open = False

    def flush_paragraph() -> None:
        if buffer:
            out.append(f"<p>{inline(' '.join(buffer))}</p>")
            buffer.clear()

    def flush_table() -> None:
        if rows:
            out.append(table(rows))
            rows.clear()

    def flush_list() -> None:
        nonlocal ordered
        if items:
            # A scored top-list gets badges and bars; anything else stays plain.
            scored = [re.search(r"(?:ценность|балл)\s+(\d{1,3})", i, re.I) for i in items]
            if ordered and sum(bool(s) for s in scored) >= len(items) * 0.6:
                out.append('<ol class="badge-list">')
                for text, score in zip(items, scored):
                    suffix = bar(int(score.group(1))) if score else ""
                    out.append(f"<li>{inline(text)}{suffix}</li>")
                out.append("</ol>")
            else:
                tag = "ol" if ordered else "ul"
                out.append(f"<{tag}>")
                # extend, not `+=`: augmented assignment would make `out` a
                # local of this nested function and shadow the list above.
                out.extend(f"<li>{inline(i)}</li>" for i in items)
                out.append(f"</{tag}>")
            items.clear()
        ordered = False

    def flush_quote() -> None:
        if quote:
            out.append(f'<div class="callout">{inline(" ".join(quote))}</div>')
            quote.clear()

    def flush_all() -> None:
        flush_paragraph(); flush_table(); flush_list(); flush_quote()

    for index, line in enumerate(lines):
        stripped = line.strip()

        if stripped.startswith("|"):
            flush_paragraph(); flush_list(); flush_quote()
            rows.append(stripped)
            continue
        flush_table()

        if stripped.startswith(">"):
            flush_paragraph(); flush_list()
            quote.append(stripped.lstrip("> ").strip())
            continue
        flush_quote()

        if not stripped:
            flush_paragraph(); flush_list()
            continue

        if stripped == "---":
            flush_all()
            # A divider right before a chapter heading has nothing to divide:
            # the chapter starts a new page anyway, and the flourish alone was
            # left twice on a page of its own.
            following = next((l.strip() for l in lines[index + 1:] if l.strip()), "")
            if not following.startswith("## "):
                out.append('<div class="divider">✦ ✦ ✦</div>')
            continue

        # «**Опора 76 · уверенность средняя · подтверждено биографией**» —
        # это не абзац, а подпись к заголовку паттерна.
        scale = re.match(r"^\*\*Опора\s+(\d{1,3})\s*·\s*(.+?)\*\*$", stripped)
        if scale:
            flush_all()
            out.append(f'<p class="scale-row"><span class="chip">опора '
                       f'{scale.group(1)}</span> {inline(scale.group(2))}</p>')
            continue

        # The soul-path figure, only inside its own chapter.
        figure = re.match(r"^###?\s*Ваш показатель[:\s]+(\d+[.,]?\d*)", stripped)
        if in_soul_chapter and figure:
            flush_all()
            out.append(soul_meter(float(figure.group(1).replace(",", "."))))
            continue

        match = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if match:
            flush_all()
            level, text = len(match.group(1)), match.group(2)
            # Only a chapter heading may change this: an h3 inside the chapter
            # would otherwise switch the flag off before the figure is reached.
            if level == 2:
                in_soul_chapter = "пут" in text.lower() and "душ" in text.lower()
            if stone_open and level <= 3:
                out.append("</div>"); stone_open = False
            out.append(heading(min(level, 4), text))
            # Prompt 08's three categories, coloured green / amber / red.
            category = STONE_CATEGORIES.get(text.lower().rstrip(" .").split(",")[0])
            if level == 3 and category:
                out.append(f'<div class="stone {category}">'); stone_open = True
            continue

        match = re.match(r"^[*\-]\s+(.*)$", stripped)
        if match:
            flush_paragraph()
            items.append(match.group(1)); continue
        match = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if match:
            flush_paragraph()
            ordered = True
            items.append(match.group(2)); continue

        if items and line.startswith(("  ", "\t")):
            items[-1] += " " + stripped
            continue
        flush_list()
        buffer.append(stripped)

    flush_all()
    if stone_open:
        out.append("</div>")
    return "\n".join(out)


class BuildError(RuntimeError):
    """The report cannot be typeset as it stands."""


def build(root: Path) -> Path:
    """report.md → report.html. Raises BuildError on a broken chapter sequence."""
    report_path = root / "report.md"
    if not report_path.exists():
        raise BuildError(f"нет {report_path}: этап 09 пишет отчёт в корень разбора")
    if not TEMPLATE.exists():
        raise BuildError(f"нет шаблона вёрстки {TEMPLATE}; укажите путь в JYOTISH_TEMPLATE")
    report = report_path.read_text(encoding="utf-8")
    broken = chapter_sequence_problems(report)
    if broken:
        raise BuildError("report.md не собирается: " + "; ".join(broken))
    template = TEMPLATE.read_text(encoding="utf-8")
    style = template.split("<style>")[1].split("</style>")[0]

    # The cover and the contents come from the report itself: the preamble
    # before the first chapter heading.
    head, _, rest = report.partition("\n## ")
    body = convert("## " + rest)
    title = re.search(r"^#\s+(.*)$", head, re.M)
    name = re.search(r"^###\s+(.*)$", head, re.M)
    born = re.search(r"^\*\*(.+?)\*\*$", head, re.M)

    cover = f"""<div class="cover">
  <h1>{html.escape(title.group(1)) if title else 'Разбор карты'}</h1>
  <div class="subtitle">Натальный разбор в традиции Джйотиш</div>
  <div class="flourish">✦ ✦ ✦</div>
  <div class="name">{html.escape(name.group(1)) if name else ''}<br>
    <span style="font-size:13pt">{html.escape(born.group(1)) if born else ''}</span></div>
  <div class="mantra">
    ॐ सह नाववतु। सह नौ भुनक्तु।<br>
    सह वीर्यं करवावहै। तेजस्वि नावधीतमस्तु।<br>
    मा विद्विषावहै। ॐ शान्तिः शान्तिः शान्तिः॥
  </div>
</div>"""

    out = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>{html.escape(name.group(1)) if name else 'Разбор'} — карта души</title>
<style>{style}
  .toc table {{ font-size: 11.5pt; }}
  .toc td:first-child {{ width: 3em; color:#9c6b3e; font-weight:bold; }}
  /* Печать. Первая сборка оставила на двадцати страницах из шестидесяти
     пустые нижние трети: «page-break-inside: avoid» на таблицах и блоках
     выталкивало крупный элемент целиком на следующую страницу. */
  h2, h3, h4 {{ page-break-after: avoid; }}
  table {{ page-break-inside: auto; }}
  thead {{ display: table-header-group; }}
  tr {{ page-break-inside: avoid; }}
  .stone, .card {{ page-break-inside: auto; }}
  /* A callout is a few lines; splitting it left its last line alone on a
     page. Blocks that can run long stay splittable, this one does not. */
  .callout {{ page-break-inside: avoid; }}
  p, li {{ orphans: 2; widows: 2; }}
  .scale-row {{ margin: 2px 0 12px; font-size: 10.5pt; page-break-after: avoid; }}
  .stone h3 {{ margin-top: 2px; }}
</style></head>
<body>
{cover}
{body}
</body></html>"""
    path = root / "report.html"
    path.write_text(out, encoding="utf-8")
    return path


#: Headless browsers that can print a page. Chromium ships with the sandbox
#: image; wkhtmltopdf is what the template's own comment suggests.
BROWSERS = (
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "chromium", "chromium-browser", "google-chrome",
)


def _browser() -> str | None:
    for candidate in BROWSERS:
        found = candidate if os.path.isfile(candidate) else shutil.which(candidate)
        if found:
            return found
    return None


def print_pdf(root: Path) -> Path | None:
    browser = _browser()
    if browser is None:
        return None
    pdf = root / "report.pdf"
    subprocess.run(
        [browser, "--headless", "--disable-gpu", "--no-sandbox",
         "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
         f"file://{(root / 'report.html').resolve()}"],
        check=True, capture_output=True, timeout=300,
    )
    return pdf


def chapter_pages(pdf: Path, titles: dict[int, str]) -> dict[int, int]:
    """Which page each numbered chapter starts on, read back from the PDF.

    The contents are written by hand at stage 09, and hand-written page
    numbers in a generated document are wrong by construction. So the build
    runs twice: print once, read the real pages, patch the contents, print
    again.

    Matching is on the chapter's own title, not on "a number and a dot": the
    heading carries a ◆ from the template and lands wherever the page's draw
    order puts it, and numbered list items look the same to a regex.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        # Never skip quietly: a silent return here left the contents pointing
        # at pages 3, 6, 14 in a document where the chapters were on 4, 7, 16,
        # and the build reported success.
        print("нет pypdfium2 — номера страниц в оглавлении НЕ проверены. "
              "Поставьте: pip install pypdfium2", file=sys.stderr)
        return {}
    doc = pdfium.PdfDocument(str(pdf))
    pages: dict[int, int] = {}
    for n in range(len(doc)):
        text = " ".join(doc[n].get_textpage().get_text_range().split())
        for number, title in titles.items():
            if number not in pages and f"{number}. {title}" in text:
                pages[number] = n + 1
    return pages


def chapter_titles(root: Path) -> dict[int, str]:
    """Numbered chapter headings of the report, as written."""
    text = (root / "report.md").read_text(encoding="utf-8")
    return {int(m.group(1)): m.group(2).strip()
            for m in re.finditer(r"^##\s+(\d{1,2})\.\s+(.+)$", text, re.M)}


def repaginate(root: Path, pages: dict[int, int]) -> int:
    """Write the contents table from the chapters and their real page numbers.

    Returns how many rows changed. Whatever sits under «## Оглавление» is
    replaced: stage 09 writes the heading alone, because hand-written page
    numbers in a generated document are wrong by construction. Without the
    heading the section is inserted before the first numbered chapter.

    Scoped to the contents chapter and nothing else. A row like
    ``| 1 | Обратиться к врачу поздно | 90 |`` in the risk table has exactly
    the same shape, and an unscoped substitution overwrote ten scores with
    page numbers on the first run.
    """
    path = root / "report.md"
    text = path.read_text(encoding="utf-8")
    titles = chapter_titles(root)
    if not titles:
        return 0
    rows = ["| | Раздел | Стр. |", "|---|---|---|"]
    rows += [f"| {number} | {title} | {pages.get(number, '—')} |"
             for number, title in sorted(titles.items())]
    table = "\n".join(rows)

    head, marker, rest = text.partition("## Оглавление")
    if marker:
        old_toc, sep, tail = rest.partition("\n## ")
        new_text = head + marker + "\n\n" + table + "\n\n" + ("## " + tail if sep else "")
    else:
        old_toc = ""
        first = re.search(r"^##\s+\d{1,2}\.\s", text, re.M)
        cut = first.start() if first else len(text)
        new_text = text[:cut] + "## Оглавление\n\n" + table + "\n\n" + text[cut:]
    changed = sum(1 for row in rows[2:] if row not in old_toc)
    if changed:
        path.write_text(new_text, encoding="utf-8")
    return changed


def main(root: Path, *, pdf: bool = True, log=print) -> Path:
    """Build, print, fix the contents, print again. Returns the last file made."""
    page = build(root)
    if not pdf:
        return page
    printed = print_pdf(root)
    if printed is None:
        raise BuildError("браузера для печати не нашлось; собран только report.html")
    moved = repaginate(root, chapter_pages(printed, chapter_titles(root)))
    if moved:
        log(f"номера страниц в оглавлении проставлены: {moved}")
        build(root)
        print_pdf(root)
    return printed
