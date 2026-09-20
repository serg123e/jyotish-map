"""Evidence about the software accumulates across charts — carefully.

A verdict from one chart is evidence about that chart. Only several charts
agreeing make it evidence about the convention, and a single disagreement
takes that away again.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jyotish import ledger as ledger_module
from jyotish.client import Client
from jyotish.collect import local_allowed
from jyotish.ledger import AGREED, DEFAULT_THRESHOLD, Ledger, record, render

CHART = {
    "slug": "t", "date": "20.03.1980", "time": "07:45:00", "timezone": "+3",
    "latitude": "54.25", "longitude": "42.50",
}
AGREE = {"show-chart-D9": AGREED, "show-chart-D60": AGREED}


@pytest.fixture(autouse=True)
def _fixed_fingerprint(monkeypatch):
    monkeypatch.setattr(ledger_module, "fingerprint", lambda: "тест · соглашения 1")


@pytest.fixture()
def path(tmp_path: Path) -> Path:
    return tmp_path / "ledger.json"


def _chart(tmp_path: Path, n: int) -> Client:
    """A distinct nativity: another date, another place."""
    return Client.from_dict(
        {**CHART, "date": f"{n:02d}.03.1980", "latitude": f"5{n}.25"}, tmp_path / f"c{n}")


# ---- accumulation ------------------------------------------------------------


def test_one_chart_is_not_enough(tmp_path: Path, path: Path) -> None:
    book = record(_chart(tmp_path, 1), AGREE, path=path)
    assert book.established() == set()
    assert book.status("show-chart-D9")[1] == "совпало на 1 из 3 нужных карт"


def test_three_charts_establish_a_block(tmp_path: Path, path: Path) -> None:
    for n in (1, 2, 3):
        book = record(_chart(tmp_path, n), AGREE, path=path)
    assert book.established() == {"show-chart-D9", "show-chart-D60"}
    assert "3 картах подряд" in book.status("show-chart-D9")[1]


def test_the_same_chart_counted_twice_is_still_one_chart(tmp_path: Path, path: Path) -> None:
    """Re-running the cross-check must not manufacture agreement."""
    chart = _chart(tmp_path, 1)
    for _ in range(5):
        book = record(chart, AGREE, path=path)
    assert book.charts() == 1
    assert book.established() == set()


def test_one_disagreement_takes_the_block_back(tmp_path: Path, path: Path) -> None:
    for n in (1, 2, 3):
        record(_chart(tmp_path, n), AGREE, path=path)
    book = record(_chart(tmp_path, 4), {"show-chart-D9": "расходится"}, path=path)
    assert "show-chart-D9" not in book.established()
    assert "разошлось на 1" in book.status("show-chart-D9")[1]
    assert "show-chart-D60" in book.established()          # the other block stands


def test_a_changed_verdict_replaces_the_old_one(tmp_path: Path, path: Path) -> None:
    """A convention was fixed: the same chart now agrees, and it counts once."""
    chart = _chart(tmp_path, 1)
    record(chart, {"show-chart-D9": "расходится"}, path=path)
    book = record(chart, AGREE, path=path)
    assert book.blocks["show-chart-D9"] == {"agreed": [book.chart_id(chart)], "disagreed": []}


def test_the_threshold_can_be_raised(tmp_path: Path, path: Path) -> None:
    for n in (1, 2, 3):
        book = record(_chart(tmp_path, n), AGREE, path=path)
    assert book.established(threshold=4) == set()
    assert book.established(threshold=3) == {"show-chart-D9", "show-chart-D60"}


# ---- the ledger is about the software, so the arithmetic is part of the key --


def test_changed_conventions_void_the_observations(tmp_path: Path, path: Path, monkeypatch) -> None:
    for n in (1, 2, 3):
        record(_chart(tmp_path, n), AGREE, path=path)
    monkeypatch.setattr(ledger_module, "fingerprint", lambda: "тест · соглашения 2")
    book = Ledger.load(path)
    assert book.blocks == {} and book.established() == set()
    assert book.dropped == "тест · соглашения 1"
    assert "отброшены" in render(book)


def test_the_fingerprint_names_all_three_sources_of_change(monkeypatch) -> None:
    """Including the parser: it reads the site, and it has shifted columns before."""
    monkeypatch.undo()                      # нужен настоящий отпечаток, не подменённый
    text = ledger_module.fingerprint()
    for part in ("PyJHora", "соглашения", "vedic-parser", "проверки"):
        assert part in text, text


def test_a_damaged_file_starts_over_instead_of_raising(path: Path) -> None:
    path.write_text("{не json", encoding="utf-8")
    book = Ledger.load(path)
    assert book.blocks == {} and "повреждён" in book.dropped


# ---- no birth data leaves the reading ----------------------------------------


def test_the_file_holds_no_birth_data(tmp_path: Path, path: Path) -> None:
    client = Client.from_dict(
        {**CHART, "slug": "распознаваемое-имя", "name": "Пётр Иванович"}, tmp_path / "c")
    record(client, AGREE, path=path)
    text = path.read_text(encoding="utf-8")
    for secret in ("1980", "20.03", "07:45", "54.25", "42.50",
                   "распознаваемое-имя", "Пётр"):
        assert secret not in text, secret
    assert json.loads(text)["blocks"]["show-chart-D9"]["agreed"]      # …but the count is there


def test_the_same_chart_has_the_same_id_and_others_do_not(tmp_path: Path, path: Path) -> None:
    book = Ledger.load(path)
    first, again = book.chart_id(_chart(tmp_path, 1)), book.chart_id(_chart(tmp_path, 1))
    assert first == again != book.chart_id(_chart(tmp_path, 2))


def test_candidate_birth_times_of_one_nativity_count_once(tmp_path: Path, path: Path) -> None:
    """Rectification and `sensitivity` make charts by the dozen from one person."""
    book = Ledger.load(path)
    one = Client.from_dict({**CHART, "time": "07:45:00"}, tmp_path / "a")
    other = Client.from_dict({**CHART, "time": "07:48:00"}, tmp_path / "b")
    assert book.chart_id(one) == book.chart_id(other)

    for time in ("07:40:00", "07:45:00", "07:50:00"):
        book = record(Client.from_dict({**CHART, "time": time}, tmp_path / time), AGREE, path=path)
    assert book.charts() == 1 and book.established() == set()


def test_two_ledgers_salt_differently(tmp_path: Path) -> None:
    """The same chart must not have the same id in someone else's ledger."""
    one = record(_chart(tmp_path, 1), AGREE, path=tmp_path / "a.json")
    two = record(_chart(tmp_path, 1), AGREE, path=tmp_path / "b.json")
    chart = _chart(tmp_path, 1)
    assert one.chart_id(chart) != two.chart_id(chart)


# ---- how the collector reads it ----------------------------------------------


def test_the_ledger_decides_only_where_the_chart_is_silent() -> None:
    settled = {"show-chart-D9", "show-chart-D60"}
    # nothing known about this chart → the ledger decides
    assert local_allowed("auto", "show-chart-D9", {}, settled)
    assert not local_allowed("auto", "show-chart-D10", {}, settled)
    # a verdict on this chart always wins, in both directions
    assert not local_allowed("auto", "show-chart-D9", {"show-chart-D9": "расходится"}, settled)
    assert local_allowed("auto", "show-chart-D10", {"show-chart-D10": AGREED}, settled)
    # and the planets table is still never local
    assert not local_allowed("auto", "show-info-D1", {}, settled | {"show-info-D1"})


def test_the_report_names_what_is_settled_and_what_is_short(tmp_path: Path, path: Path) -> None:
    record(_chart(tmp_path, 1), {"show-chart-D9": AGREED, "show-chart-D60": "расходится"}, path=path)
    for n in (2, 3):
        record(_chart(tmp_path, n), {"show-chart-D9": AGREED}, path=path)
    text = render(Ledger.load(path))
    assert "| `show-chart-D9` | **закреплено** |" in text
    assert "| `show-chart-D60` | копится |" in text
    assert "Карт в журнале: 3" in text
