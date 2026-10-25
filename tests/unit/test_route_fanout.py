# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline route and fan-out through the control API and home-action worker."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from two.api import create_app
from two.cli import main
from two.client import transport_from_testclient
from two.devices.climate.contract import ClimateReadback
from two.devices.tv.config import load_tv_config
from two.devices.tv.contract import TvReadback, TvUpstreamError
from two.store import HomeActionTurnStatus, Store, open_store
from two.worker.home_action import run_home_action_turn

T0 = datetime(2026, 10, 25, 1, 0, 0, tzinfo=UTC)
EDGE = "edge-secret"
EDGE_HEADERS = {"X-Two-Edge-Token": EDGE, "X-Two-Client-Id": "watch"}


class FakeClimate:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def read(self, entity_id: str, *, zone: str) -> ClimateReadback:
        self.calls.append(("read", zone))
        return _climate(zone, "cool")

    def set_setpoint(self, entity_id: str, celsius: float, *, zone: str) -> ClimateReadback:
        self.calls.append(("setpoint", zone, celsius))
        return _climate(zone, "cool", setpoint=celsius)

    def set_mode(self, entity_id: str, mode: str, *, zone: str) -> ClimateReadback:
        self.calls.append(("mode", zone, mode))
        return _climate(zone, mode)


class FakeTv:
    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.fail = fail or set()

    def read(self, set_id: str) -> TvReadback:
        self.calls.append(("read", set_id))
        return _tv(set_id, "on")

    def set_power(self, set_id: str, power: str) -> TvReadback:
        self.calls.append(("set_power", set_id, power))
        if set_id in self.fail:
            raise TvUpstreamError("down")
        return _tv(set_id, power)

    def open_target(self, set_id: str, target: str) -> TvReadback:
        self.calls.append(("open", set_id, target))
        return _tv(set_id, "on", target=target)

    def set_volume(
        self,
        set_id: str,
        *,
        level: int | None,
        mute: bool | None,
        step: str | None,
    ) -> TvReadback:
        self.calls.append(("volume", set_id, level, mute, step))
        return _tv(set_id, "on")


def _climate(zone: str, mode: str, *, setpoint: float = 20.0) -> ClimateReadback:
    return ClimateReadback(
        zone=zone,
        celsius=21.0,
        setpoint_celsius=setpoint,
        mode=mode,  # type: ignore[arg-type]
        reachable=True,
    )


def _tv(set_id: str, power: str, *, target: str | None = None) -> TvReadback:
    return TvReadback(
        set=set_id,
        power=power,  # type: ignore[arg-type]
        active_target=target,
        volume=10,
        mute=False,
        reachable=True,
    )


def _bind(tmp_path: Path, *, climate: bool = False, modes: str = '"off"') -> None:
    directory = tmp_path / "devices"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tv.yaml").write_text(
        "\n".join(
            [
                "enabled: true",
                "sets:",
                "  bedroom:",
                "    address: 192.168.1.41",
                "    mac: '02:00:00:00:00:02'",
                "    token_env: SAMSUNG_TV_BEDROOM_TOKEN",
                "    secure: true",
                "    volume_min: 0",
                "    volume_max: 30",
                "    volume_step: 3",
                "    targets:",
                "      netflix:",
                "        app_id: '3201907018807'",
                "  lounge:",
                "    address: 192.168.1.40",
                "    mac: '02:00:00:00:00:01'",
                "    token_env: SAMSUNG_TV_LOUNGE_TOKEN",
                "    secure: true",
                "    volume_min: 0",
                "    volume_max: 30",
                "    volume_step: 3",
                "    targets:",
                "      netflix:",
                "        app_id: '3201907018807'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    if climate:
        (directory / "climate.yaml").write_text(
            "\n".join(
                [
                    "enabled: true",
                    "upstream: http://127.0.0.1:8123",
                    "token_env: TWO_CLIMATE_TOKEN",
                    "zones:",
                    "  living:",
                    "    entity_id: climate.living",
                    "    min_celsius: 18",
                    "    max_celsius: 26",
                    "    modes:",
                    "      - cool",
                    f"      - {modes}",
                    "  study:",
                    "    entity_id: climate.study",
                    "    min_celsius: 18",
                    "    max_celsius: 26",
                    "    modes:",
                    "      - cool",
                    f"      - {modes}",
                    "",
                ]
            ),
            encoding="utf-8",
        )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = open_store(tmp_path / "two.sqlite", check_same_thread=False)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def client(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(store=store, edge_token=EDGE, data_dir=tmp_path)
    with TestClient(app) as test_client:
        yield test_client


def test_omitted_profile_routes_chat_and_refuses_an_unbound_device(
    client: TestClient,
    store: Store,
) -> None:
    chat = client.post(
        "/v1/voice/turns", json={"text": "hello from the watch"}, headers=EDGE_HEADERS
    )
    assert chat.status_code == 202
    assert chat.json()["profile"] == "chat"
    assert store.list_home_action_turns() == []

    missing = client.post(
        "/v1/voice/turns",
        json={"text": "turn all tvs off"},
        headers=EDGE_HEADERS,
    )
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "profile_not_executable"
    assert store.list_home_action_turns() == []


def test_watch_all_tvs_off_is_one_turn_for_every_set(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    _bind(tmp_path)
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "turn all tvs off"},
        headers=EDGE_HEADERS,
    )
    assert accepted.status_code == 202
    body = accepted.json()
    assert body["profile"] == "home-action"
    assert body["status"] == "queued"
    assert body["route_slots"] == ["tv"]
    assert [item["target"] for item in body["fanout"]] == ["bedroom", "lounge"]
    assert all(item["status"] == "pending" for item in body["fanout"])
    turn_id = body["turn_id"]
    stored = store.get_home_action_turn(turn_id)
    assert stored is not None
    assert stored.fanout_scope == "kind"
    broker = FakeTv()
    admitted = store.admit_home_action_turn(now=T0)
    assert admitted is not None
    finished = run_home_action_turn(
        store,
        turn_id,
        now=T0,
        data_dir=tmp_path,
        tv_install=load_tv_config(tmp_path),
        tv_broker=broker,
    )
    assert finished.status is HomeActionTurnStatus.COMPLETE
    assert broker.calls == [("set_power", "bedroom", "off"), ("set_power", "lounge", "off")]
    shown = client.get(f"/v1/voice/turns/{turn_id}", headers=EDGE_HEADERS)
    assert shown.status_code == 200
    receipt = shown.json()
    assert receipt["status"] == "complete"
    assert [item["status"] for item in receipt["fanout"]] == ["complete", "complete"]
    assert {item["tv"]["power"] for item in receipt["fanout"]} == {"off"}
    assert "bedroom" in receipt["reply"]
    assert "lounge" in receipt["reply"]


def test_explicit_tv_send_also_fans_out(
    client: TestClient,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _bind(tmp_path)
    transport = transport_from_testclient(client)
    assert main(["tv", "send", "--text", "turn all tvs off"], request=transport) == 0
    captured = capsys.readouterr()
    assert "fanout: bedroom tv.set_power pending" in captured.out
    assert "fanout: lounge tv.set_power pending" in captured.out


def test_route_send_hello_is_chat(client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
    transport = transport_from_testclient(client)
    assert main(["route", "send", "--text", "hello"], request=transport) == 0
    captured = capsys.readouterr()
    assert "profile: chat" in captured.out


def test_partial_upstream_keeps_the_sets_that_answered(
    store: Store,
    tmp_path: Path,
) -> None:
    _bind(tmp_path)
    store.ensure_home_action_session(now=T0)
    plan = json.dumps(
        [
            {
                "arguments": {"power": "off", "set": "bedroom"},
                "slot": "tv",
                "status": "pending",
                "target": "bedroom",
                "tool": "tv.set_power",
            },
            {
                "arguments": {"power": "off", "set": "lounge"},
                "slot": "tv",
                "status": "pending",
                "target": "lounge",
                "tool": "tv.set_power",
            },
        ],
        separators=(",", ":"),
    )
    store.insert_home_action_turn(
        "turn all tvs off",
        "local",
        turn_id="fan",
        now=T0,
        route_slots='["tv"]',
        fanout_scope="kind",
        fanout_json=plan,
    )
    store.admit_home_action_turn(now=T0)
    broker = FakeTv(fail={"lounge"})
    finished = run_home_action_turn(
        store,
        "fan",
        now=T0,
        tv_install=load_tv_config(tmp_path),
        tv_broker=broker,
    )
    assert finished.status is HomeActionTurnStatus.COMPLETE
    assert "lounge: tv_upstream" in (finished.reply_text or "")
    stored = json.loads(finished.fanout_json or "[]")
    assert [item["status"] for item in stored] == ["complete", "failed"]


def test_fanout_that_needs_approval_calls_nothing(store: Store, tmp_path: Path) -> None:
    _bind(tmp_path, climate=True, modes="heat")
    from two.devices.climate.config import load_climate_config

    install = load_climate_config(tmp_path)
    assert install is not None
    store.ensure_home_action_session(now=T0)
    store.insert_home_action_turn(
        "turn all air conditioners off",
        "local",
        turn_id="ac",
        now=T0,
        fanout_scope="kind",
        fanout_json=json.dumps(
            [
                {
                    "arguments": {"mode": "off", "zone": "living"},
                    "slot": "climate",
                    "status": "pending",
                    "target": "living",
                    "tool": "climate.set_mode",
                }
            ]
        ),
    )
    store.admit_home_action_turn(now=T0)
    broker = FakeClimate()
    finished = run_home_action_turn(
        store,
        "ac",
        now=T0,
        install=install,
        broker=broker,
    )
    assert finished.status is HomeActionTurnStatus.FAILED
    assert finished.error_code == "fanout_needs_approval"
    assert broker.calls == []


def test_model_decider_narrows_before_a_missing_child(store: Store) -> None:
    store.ensure_home_action_session(now=T0)
    store.insert_home_action_turn(
        "turn it off",
        "local",
        turn_id="amb",
        now=T0,
        route_slots='["climate","tv"]',
    )
    store.admit_home_action_turn(now=T0)

    class _Pick:
        def choose(
            self,
            text: str,
            slots: tuple[str, ...],
            *,
            allow_chat: bool,
        ) -> str | None:
            assert text == "turn it off"
            assert slots == ("climate", "tv")
            assert allow_chat is False
            return "tv"

    finished = run_home_action_turn(
        store,
        "amb",
        now=T0,
        argv=["/nonexistent/dsh"],
        route_decider=_Pick(),
    )
    assert finished.status is HomeActionTurnStatus.FAILED
    assert finished.route_slots == '["tv"]'


def test_expand_runs_the_harness_tool_on_every_set(store: Store, tmp_path: Path) -> None:
    _bind(tmp_path)
    install = load_tv_config(tmp_path)
    assert install is not None
    store.ensure_home_action_session(now=T0)
    store.insert_home_action_turn(
        "open netflix on all tvs",
        "local",
        turn_id="open",
        now=T0,
        route_slots='["tv"]',
        fanout_scope="kind",
    )
    store.admit_home_action_turn(now=T0)
    from two.worker.home_action import _handle_tool

    broker = FakeTv()
    finished = _handle_tool(
        store,
        "open",
        {"intent": {"tool": "tv.open", "arguments": {"set": "lounge", "target": "netflix"}}},
        None,
        None,
        install,
        broker,
        data_dir=tmp_path,
        now=T0,
    )
    assert finished.status is HomeActionTurnStatus.COMPLETE
    assert broker.calls == [("open", "bedroom", "netflix"), ("open", "lounge", "netflix")]
