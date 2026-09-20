"""chart.yaml is the one hand-written file, and the birth-time status in it
decides the whole reading. A claim there must carry its evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from jyotish.client import BirthTime, Client, ConfigError

CHART = {
    "slug": "t", "date": "07.08.1983", "time": "23:00:00", "timezone": "+4",
    "latitude": "55.45", "longitude": "37.37",
}


def _client(tmp_path: Path, **birth) -> Client:
    return Client.from_dict({**CHART, "birth_time": birth}, tmp_path)


# ---- rectified is a claim, and a claim needs evidence ----------------------


def test_rectified_with_who_and_events_opens_the_gate(tmp_path: Path) -> None:
    client = _client(tmp_path, status="rectified", by="астролог Н.",
                     events=["06.2013 — переезд", "09.2016 — рождение сына"])
    assert client.birth_time.confirmed
    assert client.birth_time.evidence_missing == ()
    assert "астролог Н." in client.birth_time.label
    assert "09.2016 — рождение сына" in client.birth_time.label


def test_the_word_rectified_alone_opens_nothing(tmp_path: Path) -> None:
    """The first reading opened Prompt 07 on this one word. Never again."""
    client = _client(tmp_path, status="rectified", note="ректифицировано астрологом отдельно")
    assert not client.birth_time.confirmed
    assert len(client.birth_time.evidence_missing) == 2
    assert "НЕ ЗАСЧИТАНО" in client.birth_time.label
    assert "НЕ ЗАСЧИТАНО" in client.birth_time.short


@pytest.mark.parametrize("given, absent", [
    ({"by": "астролог Н."}, "по каким событиям"),
    ({"events": ["06.2013 — переезд"]}, "кем"),
])
def test_half_the_evidence_is_no_evidence(tmp_path: Path, given: dict, absent: str) -> None:
    client = _client(tmp_path, status="rectified", **given)
    assert not client.birth_time.confirmed
    assert len(client.birth_time.evidence_missing) == 1
    assert absent in client.birth_time.evidence_missing[0]


def test_blank_strings_do_not_count_as_evidence(tmp_path: Path) -> None:
    client = _client(tmp_path, status="rectified", by="  ", events=["", "  "])
    assert not client.birth_time.confirmed


def test_events_may_be_date_and_what_pairs(tmp_path: Path) -> None:
    client = _client(tmp_path, status="rectified", by="астролог Н.",
                     events=[{"date": "06.2013", "what": "переезд"}])
    assert client.birth_time.events == ("06.2013 — переезд",)
    assert client.birth_time.confirmed


def test_a_pair_without_its_date_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="date и what"):
        _client(tmp_path, status="rectified", by="астролог Н.", events=[{"what": "переезд"}])


def test_events_must_be_a_list(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="списком"):
        _client(tmp_path, status="rectified", by="астролог Н.", events={"06.2013": "переезд"})


# ---- the other statuses are unchanged --------------------------------------


def test_documented_needs_no_evidence_fields(tmp_path: Path) -> None:
    client = _client(tmp_path, status="documented")
    assert client.birth_time.confirmed
    assert client.birth_time.evidence_missing == ()


@pytest.mark.parametrize("status", ["relatives", "unverified"])
def test_unconfirmed_statuses_ignore_evidence(tmp_path: Path, status: str) -> None:
    """Evidence fields on a status that claims nothing must not open anything."""
    client = _client(tmp_path, status=status, by="кто-то", events=["06.2013 — переезд"])
    assert not client.birth_time.confirmed
    assert client.birth_time.evidence_missing == ()


def test_an_unknown_status_is_refused() -> None:
    with pytest.raises(ConfigError, match="birth_time.status"):
        BirthTime(status="confirmed")


def test_the_scaffold_explains_the_evidence_fields(tmp_path: Path) -> None:
    from jyotish.client import scaffold

    text = scaffold(tmp_path / "x", "x").read_text(encoding="utf-8")
    assert "by:" in text and "events:" in text
    assert Client.load(tmp_path / "x").birth_time.status == "unverified"
