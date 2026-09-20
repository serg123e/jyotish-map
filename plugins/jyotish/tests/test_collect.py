"""The sweep: its plan, its cache and how it behaves when things go wrong.

Nothing here touches the network — the api layer is replaced with stubs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from jyotish import collect as collect_module
from jyotish.client import Client
from jyotish.collect import (
    PAID,
    UNAVAILABLE,
    RateLimited,
    Request,
    build_plan,
    collect,
)
from vedic_parser.session import AccessDenied, VedicHoroError

CHART = {
    "slug": "t", "name": "T", "date": "07.08.1983", "time": "23:00:00",
    "timezone": "+4", "latitude": "55.45", "longitude": "37.37",
}


@pytest.fixture()
def client(tmp_path: Path) -> Client:
    return Client.from_dict(dict(CHART), tmp_path)


def _stub_api(monkeypatch, **functions) -> None:
    monkeypatch.setattr(collect_module, "_load_api", lambda: functions)


def _never_called(*args, **kwargs):
    raise AssertionError("сеть не должна была понадобиться")


# ---- the plan --------------------------------------------------------------


def test_plan_keys_are_unique(client: Client) -> None:
    """A duplicate key would make one response silently overwrite another."""
    keys = [request.key for request in build_plan(client)]
    assert len(keys) == len(set(keys)), sorted(k for k in keys if keys.count(k) > 1)


def test_plan_covers_every_requested_varga(client: Client) -> None:
    plan = build_plan(client)
    for varga in client.collect.vargas:
        assert Request("show-info", {"divisional": varga}).key in {r.key for r in plan}
        assert Request("show-chart", {"divisional": varga}).key in {r.key for r in plan}


def test_plan_asks_every_sign_for_rasi_drishti_and_argala(client: Client) -> None:
    keys = {request.key for request in build_plan(client)}
    for sign in range(1, 13):
        assert f"get-aspects-{sign}-D1" in keys
        assert f"get-argala-{sign}" in keys


# ---- calling ---------------------------------------------------------------


def test_only_parameters_the_function_accepts_are_passed(client: Client, monkeypatch) -> None:
    """A parser with a narrower signature must not be handed extra arguments."""
    seen = {}

    def show_sade_sati(session, chart):          # no divisional at all
        seen["called"] = True
        return {"ok": True}

    _stub_api(monkeypatch, show_sade_sati=show_sade_sati)
    monkeypatch.setattr(collect_module, "_ensure_session",
                        lambda c, s, t: (object(), 0.0))
    result = collect(client, plan=[Request("show-sade-sati", {"divisional": "D1"})],
                     probe=False)
    assert seen["called"]
    assert result.data["show-sade-sati-D1"] == {"ok": True}


def test_missing_parser_becomes_a_gap_and_the_sweep_continues(
    client: Client, monkeypatch
) -> None:
    _stub_api(monkeypatch, show_info=lambda session, chart, **kw: {"planets": []})
    monkeypatch.setattr(collect_module, "_ensure_session",
                        lambda c, s, t: (object(), 0.0))
    result = collect(
        client,
        plan=[Request("show-current-periods", optional=True),
              Request("show-info", {"divisional": "D1"})],
        probe=False,
    )
    assert [gap.marker for gap in result.gaps] == [UNAVAILABLE]
    assert "show_current_periods" in result.gaps[0].reason
    assert "show-info-D1" in result.data          # the sweep went on


def test_paid_action_is_marked_paid_not_merely_absent(client: Client, monkeypatch) -> None:
    def refused(session, chart, **kwargs):
        raise AccessDenied("403")

    _stub_api(monkeypatch, show_info=refused)
    monkeypatch.setattr(collect_module, "_ensure_session", lambda c, s, t: (object(), 0.0))
    result = collect(client, plan=[Request("show-info", {"divisional": "D1"})], probe=False)
    assert result.gaps[0].marker == PAID


def test_rate_limit_stops_the_sweep_instead_of_inventing_gaps(
    client: Client, monkeypatch
) -> None:
    """Being throttled says nothing about whether the data exists."""
    response = requests.Response()
    response.status_code = 429

    def throttled(session, chart, **kwargs):
        raise requests.HTTPError("429", response=response)

    _stub_api(monkeypatch, show_info=throttled)
    monkeypatch.setattr(collect_module, "_ensure_session", lambda c, s, t: (object(), 0.0))
    with pytest.raises(RateLimited):
        collect(client, plan=[Request("show-info", {"divisional": "D1"})], probe=False)


# ---- the cache -------------------------------------------------------------


def test_cached_responses_are_reused_without_the_network(
    client: Client, monkeypatch
) -> None:
    client.ensure_dirs()
    (client.raw_dir / "show-info-D1.json").write_text(
        json.dumps({"planets": ["cached"]}), encoding="utf-8"
    )
    _stub_api(monkeypatch, show_info=_never_called)
    monkeypatch.setattr(collect_module, "_ensure_session", _never_called)
    result = collect(client, plan=[Request("show-info", {"divisional": "D1"})], probe=False)
    assert result.cached == ["show-info-D1"]
    assert result.data["show-info-D1"] == {"planets": ["cached"]}


def test_refresh_ignores_the_cache(client: Client, monkeypatch) -> None:
    client.ensure_dirs()
    (client.raw_dir / "show-info-D1.json").write_text('{"planets": ["old"]}', encoding="utf-8")
    _stub_api(monkeypatch, show_info=lambda session, chart, **kw: {"planets": ["fresh"]})
    monkeypatch.setattr(collect_module, "_ensure_session", lambda c, s, t: (object(), 0.0))
    result = collect(client, plan=[Request("show-info", {"divisional": "D1"})],
                     refresh=True, probe=False)
    assert result.data["show-info-D1"] == {"planets": ["fresh"]}


def test_cache_from_another_birth_time_is_refused(tmp_path: Path, monkeypatch) -> None:
    """A rectified time changes every number, so the cache must not be mixed."""
    first = Client.from_dict(dict(CHART), tmp_path)
    _stub_api(monkeypatch, show_info=lambda session, chart, **kw: {"planets": []})
    monkeypatch.setattr(collect_module, "_ensure_session", lambda c, s, t: (object(), 0.0))
    collect(first, plan=[Request("show-info", {"divisional": "D1"})], probe=False)

    rectified = Client.from_dict({**CHART, "time": "23:14:00"}, tmp_path)
    with pytest.raises(Exception, match="кэш собран для других параметров"):
        collect(rectified, plan=[Request("show-info", {"divisional": "D1"})], probe=False)

    # …and --refresh is the documented way through.
    collect(rectified, plan=[Request("show-info", {"divisional": "D1"})],
            refresh=True, probe=False)


# ---- --refresh must not leave the previous chart's answer behind -----------


def test_refresh_deletes_the_old_answer_before_asking_again(client: Client, monkeypatch) -> None:
    """A failed re-fetch must leave no file, or the stale numbers look current.

    Every later command (`status`, `check`, `crosscheck`, re-render) reads the
    cache and has no way to tell that one file belongs to the birth time from
    before the rectification.
    """
    client.ensure_dirs()
    stale = client.raw_dir / "show-info-D1.json"
    stale.write_text('{"planets": [{"code": "Su", "stale": true}]}', encoding="utf-8")

    def always_fails(func, session, chart, params):
        raise VedicHoroError("сайт не ответил")

    monkeypatch.setattr(collect_module, "_call", always_fails)
    monkeypatch.setattr(collect_module, "_ensure_session",
                        lambda client, session, last: (object(), 0.0))
    _stub_api(monkeypatch, show_info=_never_called)

    plan = [Request("show-info", {"divisional": "D1"})]
    result = collect_module.collect(client, plan=plan, refresh=True, probe=False)

    assert not stale.exists(), "устаревший ответ остался на диске"
    assert "show-info-D1" not in result.data
    assert [gap.key for gap in result.gaps] == ["show-info-D1"]
    assert collect_module.from_cache(client, plan=plan).data == {}


def test_a_dasha_level_of_one_is_not_planned_twice(client: Client) -> None:
    """(1, settings.dasha_level) queued the same key twice when the level was 1."""
    from dataclasses import replace

    shallow = replace(client, collect=replace(client.collect, dasha_level=1))
    keys = [request.key for request in build_plan(shallow)]
    assert len(keys) == len(set(keys)), sorted(k for k in keys if keys.count(k) > 1)


def test_an_empty_answer_is_named_as_the_sites_not_ours(client: Client, monkeypatch) -> None:
    """98 bytes of markup is «nothing here», not a page waiting for a parser."""
    _stub_api(monkeypatch)
    monkeypatch.setattr(collect_module, "_ensure_session", lambda c, s, t: (object(), 0.0))

    def probe(client, session, request, *, log):
        path = client.raw_dir / "html" / f"{request.key}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<b>VD: </b>", encoding="utf-8")
        return path

    monkeypatch.setattr(collect_module, "_probe_html", probe)
    result = collect(client, plan=[Request("show-current-periods", optional=True)], probe=True)
    assert "сайт вернул пустой ответ" in result.gaps[0].reason
    assert "не реализован" not in result.gaps[0].reason


# ---- where a block comes from -----------------------------------------------


class FakeBackend:
    """Stands in for jyotish.local.Backend: no ephemeris, no network."""

    def __init__(self, client):
        self.client = client

    def payload(self, key):
        if key.startswith("show-chart-") or key.startswith("show-dasha-vimshottari-"):
            return {"source": "local", "key": key}
        if key == "show-info-D1":
            return {"source": "local", "planets": []}
        return None


VERIFIED = {"show-chart-D9": "совпало", "show-chart-D60": "расходится",
            "show-dasha-vimshottari-1": "совпало"}


def test_the_policy_never_replaces_the_planets_table() -> None:
    from jyotish.collect import local_allowed

    assert not local_allowed("local", "show-info-D1", {})
    assert not local_allowed("auto", "show-info-D1", {"show-info-D1": "совпало"})


def test_auto_takes_only_what_the_cross_check_verified() -> None:
    from jyotish.collect import local_allowed

    assert local_allowed("auto", "show-chart-D9", VERIFIED)
    assert not local_allowed("auto", "show-chart-D60", VERIFIED)      # differed
    assert not local_allowed("auto", "show-chart-D10", VERIFIED)      # never checked
    assert not local_allowed("auto", "show-chart-D9", {})             # no check at all
    assert local_allowed("local", "show-chart-D10", {})
    assert not local_allowed("site", "show-chart-D9", VERIFIED)
    assert not local_allowed("local", "show-bala-D1", {})


def test_a_bad_source_is_refused() -> None:
    from jyotish.collect import local_allowed

    with pytest.raises(ValueError, match="source"):
        local_allowed("cloud", "show-chart-D9", {})


def test_verified_blocks_are_computed_locally_without_the_network(client: Client, monkeypatch) -> None:
    monkeypatch.setattr(collect_module.local_module, "Backend", FakeBackend)
    _stub_api(monkeypatch, show_chart=_never_called)
    monkeypatch.setattr(collect_module, "_ensure_session", _never_called)
    plan = [Request("show-chart", {"divisional": "D9"})]
    result = collect(client, plan=plan, probe=False, source="auto", verified=VERIFIED)
    assert result.local == ["show-chart-D9"]
    assert result.data["show-chart-D9"]["source"] == "local"
    # …and it is cached like any other block.
    assert (client.raw_dir / "show-chart-D9.json").exists()


def test_an_unverified_block_still_goes_to_the_site(client: Client, monkeypatch) -> None:
    monkeypatch.setattr(collect_module.local_module, "Backend", FakeBackend)
    _stub_api(monkeypatch, show_chart=lambda session, chart, **kw: {"from": "site"})
    monkeypatch.setattr(collect_module, "_ensure_session", lambda c, s, t: (object(), 0.0))
    plan = [Request("show-chart", {"divisional": "D60"})]
    result = collect(client, plan=plan, probe=False, source="auto", verified=VERIFIED)
    assert result.local == [] and result.data["show-chart-D60"] == {"from": "site"}


def test_source_local_takes_everything_the_backend_offers(client: Client, monkeypatch) -> None:
    monkeypatch.setattr(collect_module.local_module, "Backend", FakeBackend)
    _stub_api(monkeypatch, show_chart=_never_called, show_info=lambda s, c, **kw: {"from": "site"})
    monkeypatch.setattr(collect_module, "_ensure_session", lambda c, s, t: (object(), 0.0))
    plan = [Request("show-chart", {"divisional": "D60"}), Request("show-info", {"divisional": "D1"})]
    result = collect(client, plan=plan, probe=False, source="local")
    assert result.local == ["show-chart-D60"]
    assert result.data["show-info-D1"] == {"from": "site"}        # never local


# ---- an answer that parsed but cannot be a chart -----------------------------


def _planets(**fields):
    return {"planets": [{"code": c, **fields} for c in ("As", "Su", "Mo")]}


def test_a_planets_table_without_houses_or_nakshatras_is_reported(client: Client, monkeypatch) -> None:
    """A stale parser read the columns by counting and returned holes, not an error."""
    hollow = _planets(nakshatra=None, house=None)
    _stub_api(monkeypatch, show_info=lambda session, chart, **kw: hollow)
    monkeypatch.setattr(collect_module, "_ensure_session", lambda c, s, t: (object(), 0.0))
    result = collect(client, plan=[Request("show-info", {"divisional": "D1"})],
                     probe=False, source="site")
    assert result.data["show-info-D1"] is hollow          # данные сохранены как есть
    assert [gap.marker for gap in result.gaps] == [collect_module.SUSPECT]
    assert "vedic-parser" in result.gaps[0].reason


def test_a_real_looking_table_raises_nothing(client: Client, monkeypatch) -> None:
    full = _planets(nakshatra={"name": "Bharani"}, house=1)
    _stub_api(monkeypatch, show_info=lambda session, chart, **kw: full)
    monkeypatch.setattr(collect_module, "_ensure_session", lambda c, s, t: (object(), 0.0))
    assert collect(client, plan=[Request("show-info", {"divisional": "D1"})],
                   probe=False, source="site").gaps == []


def test_one_missing_column_is_not_enough_to_cry_wolf() -> None:
    """The ascendant legitimately has no house; a varga table has no nakshatra."""
    from jyotish.collect import suspect_reason

    assert suspect_reason("show-info-D1", _planets(nakshatra={"name": "Bharani"}, house=None)) is None
    assert suspect_reason("show-info-D1", _planets(nakshatra=None, house=3)) is None
    assert suspect_reason("show-info-D9", _planets(nakshatra=None, house=None)) is None
    assert suspect_reason("show-info-D1", {"planets": []}) is None
    assert suspect_reason("show-info-D1", {"planets": ["не словарь"]}) is None
