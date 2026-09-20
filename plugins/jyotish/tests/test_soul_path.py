"""Stage 07 must refuse more readily than it approximates."""

from __future__ import annotations

from pathlib import Path

import pytest

from jyotish.client import Client
from jyotish.soul_path import (
    DISCLAIMER,
    GateClosed,
    LayerScore,
    ScoringError,
    Subscale,
    available_layers,
    check_gate,
    compute,
    render,
    weights_for,
)

CHART = {
    "slug": "t", "date": "07.08.1983", "time": "23:00:00", "timezone": "+4",
    "latitude": "55.45", "longitude": "37.37",
}
ALL_LAYERS = ("D1", "D9", "D60", "AK", "YOGA", "D20")
REASON = "Экзальтированный Сатурн в лагне, лагнеша в 4-м, 9-й дом занят Кету."
EXPLANATION = "Наработанного заметно больше, чем нерешённого, но опыт встроен неравномерно."
RAISED = "Экзальтация Сатурна, Луна в своём знаке, поддержка 9-го дома в трёх варгах подряд."
LOWERED = "Дебилитированный Марс, напряжённый 8-й дом, расхождение D9 и D60 по Атмакараке."

#: A rectified time is a claim and carries its evidence; the tests state it
#: the way a real chart.yaml must.
RECTIFICATION = {"by": "астролог Н.", "events": ["06.2013 — переезд", "09.2016 — рождение сына"]}


def _birth(status: str) -> dict:
    return {"status": status, **(RECTIFICATION if status == "rectified" else {})}


def _client(tmp_path: Path, status: str = "documented") -> Client:
    return Client.from_dict({**CHART, "birth_time": _birth(status)}, tmp_path)


def _scores(layers=ALL_LAYERS, **overrides) -> list[LayerScore]:
    return [LayerScore(key, overrides.get(key, 50), REASON) for key in layers]


def _subscales() -> list[Subscale]:
    return [
        Subscale("resource", 60, EXPLANATION),
        Subscale("remaining", 45, EXPLANATION),
        Subscale("integration", 55, EXPLANATION),
    ]


def _compute(client: Client, layers=ALL_LAYERS, **overrides):
    return compute(
        client, _scores(layers, **overrides), _subscales(),
        available=layers, raised_by=RAISED, lowered_by=LOWERED,
    )


# ---- the gate --------------------------------------------------------------


@pytest.mark.parametrize("status", ["relatives", "unverified"])
def test_unconfirmed_birth_time_closes_the_stage(tmp_path: Path, status: str) -> None:
    with pytest.raises(GateClosed, match="Промпт 07 не выполняется"):
        check_gate(_client(tmp_path, status), ALL_LAYERS)


@pytest.mark.parametrize("status", ["documented", "rectified"])
def test_confirmed_or_rectified_opens_it(tmp_path: Path, status: str) -> None:
    check_gate(_client(tmp_path, status), ALL_LAYERS)


def test_missing_d60_closes_the_stage(tmp_path: Path) -> None:
    """D60 carries 30%; the prompt bans computing without it."""
    with pytest.raises(GateClosed, match="D60"):
        check_gate(_client(tmp_path), ("D1", "D9", "AK", "YOGA", "D20"))


def test_available_layers_reads_what_was_collected() -> None:
    collected = {
        "show-info-D1": {}, "show-chart-D1": {},
        "show-info-D9": {}, "show-chart-D9": {},
        "show-info-D60": {}, "show-chart-D60": {},
        "show-yogas-D1": {},
    }
    assert set(available_layers(collected)) == {"D1", "D9", "D60", "AK", "YOGA"}
    assert "D20" not in available_layers(collected)


# ---- the weights -----------------------------------------------------------


def test_weights_sum_to_one_hundred_with_and_without_d20() -> None:
    full, redistributed = weights_for(ALL_LAYERS)
    assert sum(full.values()) == 100 and not redistributed

    without, redistributed = weights_for(("D1", "D9", "D60", "AK", "YOGA"))
    assert sum(without.values()) == 100 and redistributed
    assert "D20" not in without


def test_d20_weight_is_split_evenly_between_d1_and_d9() -> None:
    without, _ = weights_for(("D1", "D9", "D60", "AK", "YOGA"))
    assert without["D1"] == 25 and without["D9"] == 25
    assert without["D60"] == 30  # untouched


def test_redistribution_is_declared_not_left_to_be_noticed(tmp_path: Path) -> None:
    result = _compute(_client(tmp_path), ("D1", "D9", "D60", "AK", "YOGA"))
    assert result.redistributed
    assert any("D20" in note for note in result.notes)
    assert "D20" in render(result)


# ---- the arithmetic --------------------------------------------------------


def test_total_is_the_weighted_sum(tmp_path: Path) -> None:
    result = _compute(_client(tmp_path), D1=80, D9=60, D60=40, AK=100, YOGA=0, D20=50)
    expected = 20 * .8 + 20 * .6 + 30 * .4 + 10 * 1.0 + 10 * 0 + 10 * .5
    assert result.total == pytest.approx(expected)


def test_all_hundreds_give_one_hundred(tmp_path: Path) -> None:
    result = _compute(_client(tmp_path), **{layer: 100 for layer in ALL_LAYERS})
    assert result.total == pytest.approx(100)


def test_all_zeroes_give_zero(tmp_path: Path) -> None:
    result = _compute(_client(tmp_path), **{layer: 0 for layer in ALL_LAYERS})
    assert result.total == pytest.approx(0)


def test_table_contributions_add_up_to_the_printed_total(tmp_path: Path) -> None:
    """The number and the table shown with it are the same computation."""
    result = _compute(_client(tmp_path), D1=73, D9=41, D60=88, AK=12, YOGA=65, D20=30)
    assert sum(item.value for item in result.contributions) == pytest.approx(result.total)


# ---- what counts as a valid score ------------------------------------------


def test_a_score_without_reasoning_is_refused() -> None:
    with pytest.raises(ScoringError, match="без обоснования"):
        LayerScore("D1", 70, "хорошо")


@pytest.mark.parametrize("bad", [-1, 101, 50.5, "70"])
def test_scores_outside_zero_to_hundred_are_refused(bad) -> None:
    with pytest.raises(ScoringError):
        LayerScore("D1", bad, REASON)


def test_unknown_layer_is_refused() -> None:
    with pytest.raises(ScoringError, match="неизвестный слой"):
        LayerScore("D7", 50, REASON)


def test_a_layer_scored_twice_is_refused(tmp_path: Path) -> None:
    scores = _scores() + [LayerScore("D1", 90, REASON)]
    with pytest.raises(ScoringError, match="дважды"):
        compute(_client(tmp_path), scores, _subscales(), available=ALL_LAYERS,
                raised_by=RAISED, lowered_by=LOWERED)


def test_a_layer_left_unscored_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ScoringError, match="не оценены"):
        compute(_client(tmp_path), _scores(("D1", "D9", "D60", "AK")), _subscales(),
                available=ALL_LAYERS, raised_by=RAISED, lowered_by=LOWERED)


def test_all_three_subscales_are_required(tmp_path: Path) -> None:
    with pytest.raises(ScoringError, match="все три подшкалы"):
        compute(_client(tmp_path), _scores(), [Subscale("resource", 60, EXPLANATION)],
                available=ALL_LAYERS, raised_by=RAISED, lowered_by=LOWERED)


def test_the_two_mandatory_paragraphs_are_required(tmp_path: Path) -> None:
    with pytest.raises(ScoringError, match="что снизило балл"):
        compute(_client(tmp_path), _scores(), _subscales(), available=ALL_LAYERS,
                raised_by=RAISED, lowered_by="мало")


# ---- the chapter -----------------------------------------------------------


def test_chapter_carries_the_mandatory_caveat(tmp_path: Path) -> None:
    """Prompt 07: without this sentence the chapter may not be published."""
    assert DISCLAIMER in render(_compute(_client(tmp_path)))


def test_chapter_shows_every_layer_with_weight_and_contribution(tmp_path: Path) -> None:
    text = render(_compute(_client(tmp_path)))
    for title in ("D1 (Раши)", "D9 (Навамша)", "D60 (Шаштьямша)",
                  "Атмакарака / Каракамша", "D20 (Вимшамша)"):
        assert title in text
    assert "Вклад слоя = вес × балл ÷ 100" in text


def test_chapter_states_the_direction_of_the_reversed_subscale(tmp_path: Path) -> None:
    """A high "remaining work" score means more left to do, not more done."""
    text = render(_compute(_client(tmp_path)))
    assert "чем выше число, тем больше работы остаётся" in text
