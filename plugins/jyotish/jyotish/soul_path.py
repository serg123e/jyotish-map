"""Stage 07: the soul-path figure, computed rather than felt.

Prompt 07 forbids assigning the final number "by general impression" and then,
in the same breath, asks a language model to do weighted arithmetic. This
module takes the arithmetic away: the model supplies a 0–100 score per layer
*with its reasoning*, and the code multiplies, sums and lays out the table. The
number and the table it is shown with then cannot disagree, because they are
the same computation.

Three refusals are deliberate and are not conveniences to be worked around:

* no confirmed birth time — the stage does not run at all (Prompt 07's own
  admission rule; the half-measure "let's just skip D60" is banned there
  explicitly, because it yields a number that looks precise and is not);
* no D60 data — same, it carries 30% of the weight;
* a layer scored without reasoning — that is the "general impression" the
  prompt forbids, wearing a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .client import Client
from .text import number

#: Prompt 07's table: layer key, weight in percent, and what it judges.
LAYERS: tuple[tuple[str, str, int, str], ...] = (
    ("D1", "D1 (Раши)", 20,
     "достоинства планет, сила лагны и лагнеши, состояние 5/9/12 домов, Раху–Кету"),
    ("D9", "D9 (Навамша)", 20,
     "подтверждение или опровержение достоинств D1, положение лагнеши и Атмакараки"),
    ("D60", "D60 (Шаштьямша)", 30,
     "достоинства планет в шаштьямше, состояние 9-го и 12-го домов, положение Атмакараки"),
    ("AK", "Атмакарака / Каракамша", 10,
     "состояние АК, её дом в D1/D9/D60, связь с Кету и с 12-м домом"),
    ("YOGA", "Дхармические и кармические йоги", 10,
     "йоги с полностью выполненным условием, благоприятные и напряжённые вместе"),
    ("D20", "D20 (Вимшамша)", 10,
     "показатели устойчивости духовной практики"),
)

LAYER_WEIGHTS = {key: weight for key, _title, weight, _what in LAYERS}
LAYER_TITLES = {key: title for key, title, _weight, _what in LAYERS}
LAYER_SUBJECTS = {key: what for key, _title, _weight, what in LAYERS}

#: The one layer Prompt 07 allows to be absent, and where its weight goes.
OPTIONAL_LAYER = "D20"
REDISTRIBUTE_TO = ("D1", "D9")

#: Layers without which the stage does not run at all.
REQUIRED_LAYERS = ("D1", "D9", "D60", "AK", "YOGA")

#: Prompt 07's guidance for scoring a layer. Printed with the table so the
#: reader can see the ruler, not just the measurement.
BANDS: tuple[tuple[int, int, str], ...] = (
    (80, 100, "преобладают экзальтации, собственные знаки, сильные благоприятные "
              "планеты в 5/9, поддержка дхармы, мало напряжённых показателей"),
    (60, 79, "сильные опоры есть, но рядом с ними существенные напряжённые показатели"),
    (40, 59, "примерный баланс, ни одна сторона не преобладает"),
    (20, 39, "напряжённых показателей заметно больше, поддержки мало"),
    (0, 19, "тяжёлая конфигурация по всем ключевым признакам слоя"),
)

#: The three subscales, and which way each one points. The second is the trap:
#: a high number there is *more* work left, not more progress, and Prompt 07
#: requires the direction to be stated in the text.
SUBSCALES: tuple[tuple[str, str, str], ...] = (
    ("resource", "Накопленный ресурс души",
     "чем выше число, тем больше уже наработано"),
    ("remaining", "Объём ещё активной кармической работы",
     "**чем выше число, тем больше работы остаётся** — шкала направлена обратно двум другим"),
    ("integration", "Степень интеграции опыта",
     "чем выше число, тем полнее наработанное встроено в повседневность"),
)

#: Prompt 07 refuses to publish the chapter without this. It is a constant, not
#: a suggestion to paraphrase.
DISCLAIMER = (
    "0% не означает «плохой человек», 100% не означает «лучшая душа». Это оценка "
    "конфигурации карты, а не человека. Шкала авторская и не является "
    "классическим показателем Джйотиш."
)


class GateClosed(RuntimeError):
    """The stage may not run. Raised instead of returning a weaker number."""


class ScoringError(ValueError):
    """The inputs are not a valid set of layer scores."""


@dataclass(frozen=True)
class LayerScore:
    """One layer's verdict: a number and the concrete reasons behind it."""

    key: str
    score: int
    rationale: str

    def __post_init__(self) -> None:
        if self.key not in LAYER_WEIGHTS:
            raise ScoringError(f"неизвестный слой {self.key!r}; ожидались {sorted(LAYER_WEIGHTS)}")
        if not isinstance(self.score, int) or not 0 <= self.score <= 100:
            raise ScoringError(f"{self.key}: балл слоя должен быть целым 0–100, получено {self.score!r}")
        if len(self.rationale.strip()) < 20:
            raise ScoringError(
                f"{self.key}: балл без обоснования. Промпт 07 запрещает выставлять "
                "оценку «по общему впечатлению» — назовите конкретные показатели."
            )

    @property
    def band(self) -> str:
        for low, high, text in BANDS:
            if low <= self.score <= high:
                return text
        return ""


@dataclass(frozen=True)
class Subscale:
    key: str
    value: int
    explanation: str

    def __post_init__(self) -> None:
        if self.key not in {key for key, _title, _note in SUBSCALES}:
            raise ScoringError(f"неизвестная подшкала {self.key!r}")
        if not isinstance(self.value, int) or not 0 <= self.value <= 100:
            raise ScoringError(f"{self.key}: подшкала должна быть целой 0–100, получено {self.value!r}")
        if len(self.explanation.strip()) < 20:
            raise ScoringError(f"{self.key}: подшкала без объяснения простым языком")


@dataclass(frozen=True)
class Contribution:
    key: str
    title: str
    weight: float
    score: int
    rationale: str
    band: str

    @property
    def value(self) -> float:
        """weight × score / 100, as Prompt 07 spells the formula."""
        return self.weight * self.score / 100


@dataclass
class SoulPath:
    """A finished calculation: the number, and everything it was made of."""

    total: float
    contributions: list[Contribution]
    subscales: list[Subscale]
    redistributed: bool = False
    raised_by: str = ""
    lowered_by: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 1),
            "redistributed_d20": self.redistributed,
            "layers": [
                {"key": c.key, "title": c.title, "weight": c.weight,
                 "score": c.score, "contribution": round(c.value, 2),
                 "rationale": c.rationale}
                for c in self.contributions
            ],
            "subscales": [
                {"key": s.key, "value": s.value, "explanation": s.explanation}
                for s in self.subscales
            ],
            "raised_by": self.raised_by,
            "lowered_by": self.lowered_by,
            "notes": self.notes,
        }


def check_gate(client: Client, available: Iterable[str]) -> None:
    """Raise unless Prompt 07 is allowed to run at all.

    ``available`` is the set of layers there is data for — normally derived
    from a :class:`~jyotish.collect.Collection` via :func:`available_layers`.
    """
    if not client.birth_time.confirmed:
        raise GateClosed(
            f"Промпт 07 не выполняется: время рождения — {client.birth_time.label}. "
            "Нужно документальное подтверждение или профессиональная ректификация. "
            "Половинчатый расчёт без D60 запрещён самим промптом: он даёт число, "
            "которое выглядит точным и им не является."
        )
    have = set(available)
    missing = [layer for layer in REQUIRED_LAYERS if layer not in have]
    if missing:
        raise GateClosed(
            "Промпт 07 не выполняется: нет данных для слоёв "
            + ", ".join(LAYER_TITLES[layer] for layer in missing)
            + ". Соберите их (`jyotish collect`) или откажитесь от этапа."
        )


def available_layers(collection: Mapping[str, Any]) -> list[str]:
    """Which of Prompt 07's layers the collected data can actually support."""
    have: list[str] = []
    for varga in ("D1", "D9", "D60", "D20"):
        if f"show-info-{varga}" in collection and f"show-chart-{varga}" in collection:
            have.append(varga)
    if "show-info-D1" in collection:
        have.append("AK")
    if any(key.startswith("show-yogas-") for key in collection):
        have.append("YOGA")
    return have


def weights_for(available: Iterable[str]) -> tuple[dict[str, float], bool]:
    """Layer weights, with D20's ten points shared out when it is absent.

    Prompt 07 allows exactly this one substitution and requires it to be
    declared, so the flag comes back with the weights rather than being
    inferred later from a suspicious-looking total.
    """
    have = set(available)
    weights = {key: float(weight) for key, weight in LAYER_WEIGHTS.items()}
    if OPTIONAL_LAYER in have:
        return weights, False
    share = weights.pop(OPTIONAL_LAYER) / len(REDISTRIBUTE_TO)
    for key in REDISTRIBUTE_TO:
        weights[key] += share
    return weights, True


def compute(
    client: Client,
    scores: Iterable[LayerScore],
    subscales: Iterable[Subscale],
    *,
    available: Iterable[str],
    raised_by: str,
    lowered_by: str,
) -> SoulPath:
    """Weigh the layers and add them up. Refuses rather than approximates."""
    check_gate(client, available)
    weights, redistributed = weights_for(available)

    by_key = {}
    for score in scores:
        if score.key in by_key:
            raise ScoringError(f"слой {score.key} оценён дважды")
        by_key[score.key] = score

    expected = set(weights)
    if set(by_key) != expected:
        extra = sorted(set(by_key) - expected)
        absent = sorted(expected - set(by_key))
        raise ScoringError(
            "набор оценённых слоёв не совпадает с расчётным: "
            + (f"лишние {extra}; " if extra else "")
            + (f"не оценены {absent}" if absent else "")
        )

    given = {subscale.key: subscale for subscale in subscales}
    wanted = [key for key, _title, _note in SUBSCALES]
    if set(given) != set(wanted):
        raise ScoringError(
            "нужны все три подшкалы: " + ", ".join(wanted)
            + f"; получены: {', '.join(sorted(given)) or '—'}"
        )
    for text, name in ((raised_by, "что дало высокие баллы"),
                       (lowered_by, "что снизило балл")):
        if len(text.strip()) < 40:
            raise ScoringError(
                f"обязательный абзац «{name}» пуст или слишком короток: "
                "Промпт 07 требует конкретных показателей, а не общих слов"
            )

    contributions = [
        Contribution(
            key=key, title=LAYER_TITLES[key], weight=weights[key],
            score=by_key[key].score, rationale=by_key[key].rationale,
            band=by_key[key].band,
        )
        for key, _title, _weight, _what in LAYERS if key in weights
    ]
    total = sum(item.value for item in contributions)

    notes: list[str] = []
    if redistributed:
        notes.append(
            "Карта D20 не получена: её вес 10% разделён поровну между D1 и D9, "
            "как предписывает Промпт 07. Это указано здесь, а не выведено из числа."
        )
    return SoulPath(
        total=total, contributions=contributions,
        subscales=[given[key] for key in wanted],
        redistributed=redistributed, raised_by=raised_by.strip(),
        lowered_by=lowered_by.strip(), notes=notes,
    )


def render(result: SoulPath) -> str:
    """The chapter as Prompt 07 requires it: number, table, subscales, caveat."""
    lines = [
        "## Пройденность пути души",
        "",
        f"**{number(result.total)}%**",
        "",
        f"> {DISCLAIMER}",
        "",
        "### Из чего сложилось это число",
        "",
        "| Слой | Что оценивается | Вес | Балл | Вклад |",
        "|---|---|---|---|---|",
    ]
    for item in result.contributions:
        lines.append(
            f"| {item.title} | {LAYER_SUBJECTS[item.key]} | {item.weight:g}% | "
            f"{item.score} | {number(item.value)} |"
        )
    lines.append(
        f"| **Итого** |  | {sum(i.weight for i in result.contributions):g}% |  | "
        f"**{number(result.total)}** |"
    )
    lines += ["", "Вклад слоя = вес × балл ÷ 100.", ""]

    for note in result.notes:
        lines += [f"*{note}*", ""]

    lines += ["### Почему такие баллы", ""]
    for item in result.contributions:
        lines += [f"**{item.title} — {item.score}.** {item.rationale}", ""]

    lines += [
        "### Что дало высокие баллы", "", result.raised_by, "",
        "### Что снизило балл", "", result.lowered_by, "",
        "### Три подшкалы", "",
    ]
    notes_by_key = {key: note for key, _title, note in SUBSCALES}
    titles_by_key = {key: title for key, title, _note in SUBSCALES}
    for subscale in result.subscales:
        lines += [
            f"**{titles_by_key[subscale.key]} — {subscale.value}/100.** "
            f"{notes_by_key[subscale.key]}.",
            "",
            subscale.explanation,
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"
