"""Where a reading stands, decided from its files rather than from memory.

The order of the ten stages and what each one needs were written in prose —
in a command file, in SKILL.md, in the README — and prose is not enforced.
The first full reading finished with the summaries of stages 03 and 09
never written, and nobody noticed, because the next stage was started by a
person who remembered the previous one, not by anything that looked.

Here the dependency table is data, a stage is «done» when its files exist,
and :func:`next_stage` says what comes next and what, if anything, stops it.
That is what a run without confirmations between stages needs: a loop that
asks this module instead of asking the person.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .client import Client

STAGES = ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10")

TITLES = {
    "01": "сбор технических данных",
    "02": "открытие и слепой аудит",
    "03": "сверка с реальным человеком",
    "04": "разбор сфер жизни",
    "05": "текущий период",
    "06": "глубокий синтез",
    "07": "путь души: расчёт",
    "08": "система гармонизации",
    "09": "финальный отчёт",
    "10": "контроль качества и вёрстка",
}

#: Which stages each one reads, from ARCHITECTURE.md's table.
DEPENDS = {
    "01": (),
    "02": ("01",),
    "03": ("01", "02"),
    "04": ("01", "02", "03"),
    "05": ("01", "03", "04"),
    "06": ("02", "03", "04", "05"),
    "07": ("01", "03", "06"),
    "08": ("01", "03", "04", "07"),
    "09": ("02", "03", "04", "05", "06", "07", "08"),
    "10": ("09",),
}

#: Stages that need biography.md before they start — Prompt 03's gate.
NEED_BIOGRAPHY = ("04", "05", "06", "07", "08", "09", "10")

DONE = "выполнен"
SKIPPED = "пропущен"        # stage 07 with the gate shut: allowed, and noted
PENDING = "не начат"
PARTIAL = "не завершён"     # some files are there, some are not


@dataclass
class StageState:
    number: str
    status: str
    #: Files the stage produced, including parts like ``04_часть2.md``.
    present: list[Path] = field(default_factory=list)
    #: What a finished stage should have left behind but did not.
    missing: list[str] = field(default_factory=list)
    #: Anything worth telling about this stage — e.g. 07 run with the gate shut.
    notes: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return TITLES[self.number]

    @property
    def satisfied(self) -> bool:
        """Whether a later stage may treat this one as available."""
        return self.status in (DONE, SKIPPED)


# ---------------------------------------------------------------------------


def stage_files(client: Client, number: str) -> list[Path]:
    """The prose of a stage: ``stages/NN.md`` and any ``stages/NN_часть*.md``.

    Stage 04 did not fit in one pass on the first reading and came out as
    two files; a state check that only knew ``04.md`` would have called it
    complete on the first half. Only «часть» files are parts: stage 03 also
    leaves ``03_вопросы.md`` and the like behind, and those are letters to
    the person, not the stage.
    """
    return sorted(client.stages_dir.glob(f"{number}.md")) + \
        sorted(client.stages_dir.glob(f"{number}_часть*.md"))


def _summary(client: Client, number: str) -> Path:
    return client.summaries_dir / f"{number}.md"


def stage_state(client: Client, number: str) -> StageState:
    """What is on disk for one stage."""
    state = StageState(number, PENDING)
    summary = _summary(client, number)

    if number == "01":
        wanted = {"01_RAW_DATA.md": client.raw_data_md,
                  "state/summaries/01.md": summary}
    elif number == "07":
        wanted = {"stages/07.md": client.stages_dir / "07.md",
                  "soul_path.json": client.root / "soul_path.json",
                  "state/summaries/07.md": summary}
    elif number == "09":
        wanted = {"report.md": client.root / "report.md",
                  "state/summaries/09.md": summary}
    elif number == "10":
        wanted = {"qa.md": client.root / "qa.md",
                  "stages/10.md": client.stages_dir / "10.md"}
    else:
        parts = stage_files(client, number)
        wanted = {f"stages/{number}.md": parts[0] if parts else client.stages_dir / f"{number}.md",
                  f"state/summaries/{number}.md": summary}
        state.present += parts

    for label, path in wanted.items():
        if path.exists():
            if path not in state.present:
                state.present.append(path)
        else:
            state.missing.append(label)

    if number == "07":
        return _stage_07(client, state)

    if not state.present:
        state.status = PENDING
    elif state.missing:
        state.status = PARTIAL
    else:
        state.status = DONE
    return state


def _stage_07(client: Client, state: StageState) -> StageState:
    """Stage 07 is the one stage that may legitimately not run.

    With the gate shut it is skipped and the reading goes on; with the gate
    shut *and* the files present, it ran when it must not have — the reading
    goes on too, but the note is loud, and check 19 of stage 10 fails.
    """
    gate_open = client.birth_time.confirmed
    ran = any(p.name in ("07.md", "soul_path.json") for p in state.present)
    if not gate_open:
        if ran:
            state.status = DONE
            state.notes.append(
                "этап 07 выполнен при закрытом гейте — время рождения: "
                f"{client.birth_time.short}. Результат публиковать нельзя (пункт 19)."
            )
        else:
            state.status = SKIPPED
            state.notes.append(
                f"гейт закрыт (время рождения: {client.birth_time.short}) — этап "
                "пропускается с пометкой в отчёте, не выполняется частично."
            )
        return state
    if not state.present:
        state.status = PENDING
    elif state.missing:
        state.status = PARTIAL
    else:
        state.status = DONE
    return state


def progress(client: Client) -> list[StageState]:
    return [stage_state(client, number) for number in STAGES]


@dataclass
class Next:
    """What to do now, and whether anything stops it."""

    stage: str | None
    #: Reasons a person is needed before this stage can start. Empty means go.
    blockers: list[str] = field(default_factory=list)
    #: Things to say but not to stop for.
    notes: list[str] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.stage is None


def next_stage(client: Client, states: Iterable[StageState] | None = None) -> Next:
    """The first stage that is not satisfied, with what blocks it.

    A stage whose dependencies are unfinished is not «next»: the earlier one
    is. Stage 07 with the gate shut is reported as skipped, not as blocked —
    Prompt 07 says the reading continues without it.
    """
    by_number = {s.number: s for s in (states if states is not None else progress(client))}
    for number in STAGES:
        state = by_number[number]
        if state.satisfied:
            continue
        result = Next(number)
        result.notes += state.notes
        if state.status == PARTIAL:
            result.notes.append(
                f"этап {number} начат, но не хватает: " + ", ".join(state.missing))
        unmet = [d for d in DEPENDS[number] if not by_number[d].satisfied]
        if unmet:
            # Cannot happen for the *first* unsatisfied stage unless the
            # order was broken by hand; still, say it rather than guess.
            result.blockers.append(
                f"этап {number} зависит от {', '.join(unmet)}, а они не выполнены")
        if number in NEED_BIOGRAPHY and not client.biography_md.exists():
            result.blockers.append(
                "нет biography.md — гейт Промпта 03 закрыт. Нужны: профессия, "
                "семейное положение и дети, минимум 3 датированных события, практики.")
        if number == "01":
            result.notes.append("сбор с сайта: `jyotish collect`")
        return result

    finish = Next(None)
    for state in by_number.values():
        finish.notes += state.notes
    return finish


# ---------------------------------------------------------------------------


MARK = {DONE: "✓", SKIPPED: "—", PARTIAL: "…", PENDING: "·"}


def render_line(states: Iterable[StageState]) -> str:
    """``01 ✓ 02 ✓ 03 … 04 ·`` — one glance at the whole reading."""
    cells = []
    for state in states:
        mark = MARK[state.status]
        parts = [p for p in state.present if p.parent.name == "stages"]
        if len(parts) > 1:
            mark += f"({len(parts)} ч.)"
        cells.append(f"{state.number} {mark}")
    return "  ".join(cells)
