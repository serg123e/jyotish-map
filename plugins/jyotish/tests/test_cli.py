"""The command line, where a hand-edited file meets a Python traceback.

`soul_path_input.json` is written by a person, so a malformed one is an
expected outcome of normal use. The tool's whole posture is to refuse loudly
and say why; a `KeyError` stack trace is neither.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jyotish.cli import main

CHART = """slug: t
name: T
date: "07.08.1983"
time: "23:00:00"
timezone: "+4"
latitude: "55.45"
longitude: "37.37"
birth_time:
  status: documented
"""


@pytest.fixture()
def reading(tmp_path: Path) -> Path:
    root = tmp_path / "t"
    root.mkdir()
    (root / "chart.yaml").write_text(CHART, encoding="utf-8")
    return root


def _run(capsys, *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_the_template_has_every_layer_and_subscale(reading: Path, capsys) -> None:
    code, _ = _run(capsys, "soul-path", str(reading), "--template")
    assert code == 0
    payload = json.loads((reading / "soul_path_input.json").read_text(encoding="utf-8"))
    assert [item["key"] for item in payload["layers"]] == \
        ["D1", "D9", "D60", "AK", "YOGA", "D20"]
    assert len(payload["subscales"]) == 3


def test_a_template_is_not_overwritten(reading: Path, capsys) -> None:
    _run(capsys, "soul-path", str(reading), "--template")
    code, text = _run(capsys, "soul-path", str(reading), "--template")
    assert code == 1
    assert "уже существует" in text


def test_a_closed_gate_is_reported_not_raised(tmp_path: Path, capsys) -> None:
    root = tmp_path / "u"
    root.mkdir()
    (root / "chart.yaml").write_text(
        CHART.replace("status: documented", "status: unverified"), encoding="utf-8")
    code, text = _run(capsys, "soul-path", str(root))
    assert code == 3
    assert "Промпт 07 не выполняется" in text


def _open_the_gate(root: Path) -> None:
    """Enough cached blocks that stage 07 is allowed to run.

    Without this the gate closes first and the tests below pass without ever
    reaching the file they are about.
    """
    raw = root / "raw"
    raw.mkdir(exist_ok=True)
    for varga in ("D1", "D9", "D60"):
        for action in ("show-info", "show-chart"):
            (raw / f"{action}-{varga}.json").write_text("{}", encoding="utf-8")
    (raw / "show-yogas-D1.json").write_text("{}", encoding="utf-8")


def test_the_gate_opens_once_the_layers_are_cached(reading: Path, capsys) -> None:
    _open_the_gate(reading)
    code, text = _run(capsys, "soul-path", str(reading))
    assert code == 1
    assert "нет файла с баллами" in text


def test_a_file_that_is_not_json_says_so(reading: Path, capsys) -> None:
    _open_the_gate(reading)
    (reading / "soul_path_input.json").write_text("{не json", encoding="utf-8")
    code, text = _run(capsys, "soul-path", str(reading))
    assert code == 1
    assert "это не JSON" in text


def test_a_missing_field_names_the_field_instead_of_raising(reading: Path, capsys) -> None:
    _open_the_gate(reading)
    (reading / "soul_path_input.json").write_text(
        json.dumps({"subscales": []}), encoding="utf-8")
    code, text = _run(capsys, "soul-path", str(reading))
    assert code == 1, text
    assert "не хватает поля" in text and "--template" in text
