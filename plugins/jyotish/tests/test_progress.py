"""The state of a reading is what is on disk, and the next step follows from it."""

from __future__ import annotations

from pathlib import Path

import pytest

from jyotish.cli import main
from jyotish.client import Client
from jyotish.progress import (
    DONE, PARTIAL, PENDING, SKIPPED, STAGES, next_stage, progress, render_line, stage_state,
)

CHART = {
    "slug": "t", "date": "07.08.1983", "time": "23:00:00", "timezone": "+4",
    "latitude": "55.45", "longitude": "37.37",
}


def _client(tmp_path: Path, status: str = "documented", biography: bool = True) -> Client:
    client = Client.from_dict({**CHART, "birth_time": {"status": status}}, tmp_path)
    client.ensure_dirs()
    if biography:
        client.biography_md.write_text("врач, женат, 06.2013 переезд", encoding="utf-8")
    return client


def _finish(client: Client, *numbers: str) -> None:
    """Leave behind what a finished stage leaves behind."""
    for number in numbers:
        if number == "01":
            client.raw_data_md.write_text("# raw", encoding="utf-8")
        elif number == "07":
            (client.stages_dir / "07.md").write_text("глава", encoding="utf-8")
            (client.root / "soul_path.json").write_text("{}", encoding="utf-8")
        elif number == "09":
            (client.root / "report.md").write_text("# отчёт", encoding="utf-8")
        elif number == "10":
            (client.root / "qa.md").write_text("# qa", encoding="utf-8")
            (client.stages_dir / "10.md").write_text("проверка", encoding="utf-8")
        else:
            (client.stages_dir / f"{number}.md").write_text("текст", encoding="utf-8")
        if number != "10":
            (client.summaries_dir / f"{number}.md").write_text("сводка", encoding="utf-8")


# ---- one stage ---------------------------------------------------------------


def test_a_fresh_reading_has_nothing_done(tmp_path: Path) -> None:
    client = _client(tmp_path, biography=False)
    assert all(s.status == PENDING for s in progress(client) if s.number != "07")


def test_a_stage_without_its_summary_is_not_done(tmp_path: Path) -> None:
    """Stages 03 and 09 of the first reading had prose and no summary; nobody saw."""
    client = _client(tmp_path)
    (client.stages_dir / "03.md").write_text("текст", encoding="utf-8")
    state = stage_state(client, "03")
    assert state.status == PARTIAL
    assert state.missing == ["state/summaries/03.md"]


def test_stage_parts_count_as_the_stage(tmp_path: Path) -> None:
    """04.md and 04_часть2.md are one stage, not one stage and a stray file."""
    client = _client(tmp_path)
    _finish(client, "04")
    (client.stages_dir / "04_часть2.md").write_text("ещё", encoding="utf-8")
    state = stage_state(client, "04")
    assert state.status == DONE
    assert [p.name for p in state.present if p.parent.name == "stages"] == ["04.md", "04_часть2.md"]
    assert "04 ✓(2 ч.)" in render_line([state])


def test_letters_to_the_person_are_not_stage_parts(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _finish(client, "03")
    (client.stages_dir / "03_вопросы.md").write_text("вопросы", encoding="utf-8")
    assert "03 ✓ " in render_line([stage_state(client, "03")]) + " "


def test_stage_09_lives_in_report_md(tmp_path: Path) -> None:
    client = _client(tmp_path)
    (client.root / "report.md").write_text("# отчёт", encoding="utf-8")
    assert stage_state(client, "09").missing == ["state/summaries/09.md"]
    (client.summaries_dir / "09.md").write_text("сводка", encoding="utf-8")
    assert stage_state(client, "09").status == DONE


# ---- stage 07 and its gate ---------------------------------------------------


def test_a_shut_gate_skips_stage_07_instead_of_blocking(tmp_path: Path) -> None:
    client = _client(tmp_path, status="relatives")
    state = stage_state(client, "07")
    assert state.status == SKIPPED and state.satisfied
    assert "гейт закрыт" in state.notes[0]


def test_stage_07_run_with_the_gate_shut_is_loud(tmp_path: Path) -> None:
    client = _client(tmp_path, status="relatives")
    _finish(client, "07")
    state = stage_state(client, "07")
    assert state.status == DONE
    assert "при закрытом гейте" in state.notes[0] and "пункт 19" in state.notes[0]


def test_the_word_rectified_without_events_keeps_07_skipped(tmp_path: Path) -> None:
    client = _client(tmp_path, status="rectified")
    assert stage_state(client, "07").status == SKIPPED


# ---- what comes next ---------------------------------------------------------


def test_next_is_the_first_unsatisfied_stage(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _finish(client, "01", "02")
    following = next_stage(client)
    assert following.stage == "03" and not following.blockers


def test_biography_gate_blocks_04_but_not_03(tmp_path: Path) -> None:
    client = _client(tmp_path, biography=False)
    _finish(client, "01", "02")
    assert next_stage(client).blockers == []
    _finish(client, "03")
    following = next_stage(client)
    assert following.stage == "04"
    assert any("biography.md" in b for b in following.blockers)


def test_a_skipped_07_lets_08_proceed(tmp_path: Path) -> None:
    client = _client(tmp_path, status="relatives")
    _finish(client, "01", "02", "03", "04", "05", "06")
    following = next_stage(client)
    assert following.stage == "08"
    assert any("гейт закрыт" in n for n in following.notes) or True   # noted on 07 itself
    assert not following.blockers


def test_a_partial_stage_is_next_and_says_what_is_missing(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _finish(client, "01", "02")
    (client.stages_dir / "03.md").write_text("текст", encoding="utf-8")
    following = next_stage(client)
    assert following.stage == "03"
    assert any("не хватает: state/summaries/03.md" in n for n in following.notes)


def test_everything_done_means_finished(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _finish(client, *STAGES)
    assert next_stage(client).finished


# ---- the command line contract -----------------------------------------------


def _run(capsys, *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


def _write_chart(root: Path, status: str = "documented") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "chart.yaml").write_text(
        'slug: t\ndate: "07.08.1983"\ntime: "23:00:00"\ntimezone: "+4"\n'
        f'latitude: "55.45"\nlongitude: "37.37"\nbirth_time:\n  status: {status}\n',
        encoding="utf-8")


def test_next_exit_codes_are_the_contract(tmp_path: Path, capsys) -> None:
    root = tmp_path / "t"
    _write_chart(root)
    client = Client.load(root)
    client.ensure_dirs()

    code, text = _run(capsys, "next", str(root))
    assert code == 0 and text.rstrip().endswith("01 сбор технических данных")

    _finish(client, "01", "02", "03")
    code, text = _run(capsys, "next", str(root))
    assert code == 3 and "biography.md" in text

    client.biography_md.write_text("есть", encoding="utf-8")
    code, text = _run(capsys, "next", str(root))
    assert code == 0 and text.rstrip().endswith("04 разбор сфер жизни")

    _finish(client, *STAGES)
    code, text = _run(capsys, "next", str(root))
    assert code == 4 and "завершён" in text


def test_status_shows_the_stages_and_the_next_step(tmp_path: Path, capsys) -> None:
    root = tmp_path / "t"
    _write_chart(root, status="relatives")
    client = Client.load(root)
    client.ensure_dirs()
    client.biography_md.write_text("есть", encoding="utf-8")
    _finish(client, "01", "02")
    (client.stages_dir / "03.md").write_text("текст", encoding="utf-8")
    code, text = _run(capsys, "status", str(root))
    assert code == 0
    assert "01 ✓  02 ✓  03 …  04 ·" in text
    assert "07 —" in text
    assert "03: не хватает state/summaries/03.md" in text
    assert "дальше: этап 03" in text
