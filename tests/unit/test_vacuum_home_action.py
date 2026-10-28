# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline vacuum home-action tests. No live harness and no live robot."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient

from two.api import create_app
from two.cli import main
from two.client import transport_from_testclient
from two.devices.climate.contract import ClimateInstall, ZonePolicy
from two.devices.vacuum.config import load_vacuum_config
from two.devices.vacuum.contract import (
    RobotPolicy,
    VacuumInstall,
    VacuumReadback,
    VacuumUpstreamError,
    interpret_vacuum_tool,
)
from two.devices.vacuum.ecovacs import EcovacsCloud, _RefuseRedirect
from two.routing import cards_for, compiled_call, decide_route
from two.store import HomeActionTurnStatus, Store, open_store
from two.worker.acp_home import _vacuum_prompt_lines
from two.worker.home_action import home_child_env, run_home_action_turn

T0 = datetime(2026, 10, 27, 8, 0, 0, tzinfo=UTC)
EDGE = "edge-secret"
EDGE_HEADERS = {"X-Two-Edge-Token": EDGE, "X-Two-Client-Id": "watch"}


class FakeVacuum:
    """Records device calls and returns a fixed read-back."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def read(self, robot_id: str) -> VacuumReadback:
        self.calls.append(("read", robot_id))
        return _seen(robot_id, "idle")

    def clean(self, robot_id: str, action: str) -> VacuumReadback:
        self.calls.append(("clean", robot_id, action))
        activity = "cleaning" if action == "start" else "idle"
        return _seen(robot_id, activity)

    def dock(self, robot_id: str, action: str) -> VacuumReadback:
        self.calls.append(("dock", robot_id, action))
        return _seen(robot_id, "returning")


def _seen(robot_id: str, activity: str) -> VacuumReadback:
    return VacuumReadback(
        robot=robot_id,
        activity=activity,  # type: ignore[arg-type]
        charging=False,
        station="idle",
        reachable=True,
    )


def _install() -> VacuumInstall:
    return VacuumInstall(
        api_host="open.ecovacs.com",
        token_env="ECO_API_KEY",
        robots={
            "downstairs": RobotPolicy(robot_id="downstairs", nickname="Downstairs"),
            "upstairs": RobotPolicy(robot_id="upstairs", nickname="Upstairs"),
        },
    )


def _binding(tmp_path: Path, *, host: str = "open.ecovacs.com", enabled: bool = True) -> None:
    directory = tmp_path / "devices"
    directory.mkdir(parents=True, exist_ok=True)
    flag = "true" if enabled else "false"
    (directory / "vacuum.yaml").write_text(
        "\n".join(
            [
                f"enabled: {flag}",
                f"api_host: {host}",
                "token_env: ECO_API_KEY",
                "robots:",
                "  downstairs:",
                '    nickname: "Downstairs"',
                "  upstairs:",
                '    nickname: "Upstairs"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def _cards(install: VacuumInstall | None = None) -> tuple[object, ...]:
    return cards_for(climate=None, television=None, vacuum=install)


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


def test_open_api_posts_the_key_in_the_body_and_reads_back() -> None:
    calls: list[tuple[str, str, dict[str, str]]] = []

    def request(method: str, url: str, body: Mapping[str, str]) -> object:
        calls.append((method, url, dict(body)))
        if body.get("cmd") == "Clean":
            return {"code": 0}
        if body.get("cmd") == "Charge":
            return {"code": 0}
        return {
            "code": 0,
            "data": {
                "ctl": {
                    "data": {
                        "ret": "ok",
                        "cleanSt": "s",
                        "chargeSt": "",
                        "stationSt": "i",
                    }
                }
            },
        }

    cloud = EcovacsCloud("open.ecovacs.com", "secret-key", request=request)
    readback = cloud.clean("downstairs", "Downstairs", "start")
    assert calls[0] == (
        "POST",
        "https://open.ecovacs.com/robot/ctl",
        {"nickName": "Downstairs", "cmd": "Clean", "act": "s", "ak": "secret-key"},
    )
    assert "?" not in calls[0][1]
    assert calls[1][2]["cmd"] == "GetWorkState"
    assert calls[1][2]["nickName"] == "Downstairs"
    assert readback.robot == "downstairs"
    assert readback.activity == "cleaning"
    assert readback.charging is False
    assert readback.station == "idle"
    assert readback.reachable is True
    docked = cloud.dock("upstairs", "Upstairs", "start")
    assert calls[2][2]["cmd"] == "Charge"
    assert calls[2][2]["act"] == "go-start"
    assert calls[2][2]["nickName"] == "Upstairs"
    assert docked.activity == "cleaning"


def test_device_list_accepts_strings_and_objects() -> None:
    def request(method: str, url: str, body: Mapping[str, str]) -> object:
        assert method == "GET"
        assert url == "https://open.ecovacs.com/robot/deviceList?ak=secret-key"
        assert body == {}
        return {"status": "0", "data": ["Downstairs", {"nickName": "Upstairs"}, ""]}

    cloud = EcovacsCloud("open.ecovacs.com", "secret-key", request=request)
    assert cloud.list_nicknames() == ("Downstairs", "Upstairs")


def test_bad_host_redirect_and_disabled_binding_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        EcovacsCloud("example.com", "secret-key")
    handler = _RefuseRedirect()
    with pytest.raises(VacuumUpstreamError):
        handler.redirect_request(
            Request("https://open.ecovacs.com/robot/ctl"),
            None,
            302,
            "Found",
            {},
            "https://evil.example/robot/ctl",
        )
    _binding(tmp_path, host="example.com")
    assert load_vacuum_config(tmp_path) is None
    _binding(tmp_path, enabled=False)
    assert load_vacuum_config(tmp_path) is None
    _binding(tmp_path)
    loaded = load_vacuum_config(tmp_path)
    assert loaded is not None
    assert loaded.api_host == "open.ecovacs.com"
    assert set(loaded.robots) == {"downstairs", "upstairs"}


def test_unknown_robot_is_refused_and_not_called(store: Store) -> None:
    install = _install()
    denied = interpret_vacuum_tool(
        "vacuum.clean",
        {"robot": "attic", "action": "start"},
        install,
    )
    assert denied.kind == "deny"
    assert denied.error_code == "vacuum_robot_denied"
    assert denied.call is None
    allowed = interpret_vacuum_tool(
        "vacuum.clean",
        {"robot": "downstairs", "action": "start"},
        install,
    )
    assert allowed.kind == "allow"
    assert allowed.call is not None
    assert "Downstairs" not in allowed.call.arguments_json
    store.ensure_home_action_session(now=T0)
    store.insert_home_action_turn(
        "start the attic vacuum",
        "local",
        turn_id="attic",
        now=T0,
        route_slots='["vacuum"]',
        tool_name="vacuum.clean",
        arguments_json='{"action":"start","robot":"attic"}',
    )
    store.admit_home_action_turn(now=T0)
    broker = FakeVacuum()
    finished = run_home_action_turn(
        store,
        "attic",
        now=T0,
        vacuum_install=install,
        vacuum_broker=broker,
        argv=["/nonexistent/dsh"],
    )
    assert finished.status is HomeActionTurnStatus.FAILED
    assert finished.error_code == "vacuum_robot_denied"
    assert broker.calls == []


def test_named_start_compiles_and_runs_without_the_harness(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    install = _install()
    named = decide_route("start the downstairs vacuum", _cards(install))
    assert compiled_call(named) == (
        "vacuum.clean",
        {"action": "start", "robot": "downstairs"},
    )
    dock_one = decide_route("dock upstairs", _cards(install))
    assert compiled_call(dock_one) == (
        "vacuum.dock",
        {"action": "start", "robot": "upstairs"},
    )
    alone = decide_route("start", _cards(install))
    assert alone.profile == "chat"
    _binding(tmp_path)
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "start the downstairs vacuum"},
        headers=EDGE_HEADERS,
    )
    assert accepted.status_code == 202
    body = accepted.json()
    assert body["profile"] == "home-action"
    assert body["route_slots"] == ["vacuum"]
    turn_id = body["turn_id"]
    stored = store.get_home_action_turn(turn_id)
    assert stored is not None
    assert stored.tool_name == "vacuum.clean"
    assert stored.fanout_json is None
    broker = FakeVacuum()
    admitted = store.admit_home_action_turn(now=T0)
    assert admitted is not None
    finished = run_home_action_turn(
        store,
        turn_id,
        now=T0,
        data_dir=tmp_path,
        vacuum_install=load_vacuum_config(tmp_path),
        vacuum_broker=broker,
        argv=["/nonexistent/dsh"],
    )
    assert finished.status is HomeActionTurnStatus.COMPLETE
    assert broker.calls == [("clean", "downstairs", "start")]
    shown = client.get(f"/v1/voice/turns/{turn_id}", headers=EDGE_HEADERS)
    assert shown.status_code == 200
    receipt = shown.json()
    assert receipt["status"] == "complete"
    assert receipt["vacuum"]["robot"] == "downstairs"
    assert receipt["vacuum"]["activity"] == "cleaning"
    assert receipt["vacuum"]["reachable"] is True
    assert "Downstairs" not in shown.text
    assert "open.ecovacs.com" not in shown.text


def test_dock_all_vacuums_fans_out_without_the_harness(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    install = _install()
    decision = decide_route("dock all vacuums", _cards(install))
    assert decision.fanout_scope == "kind"
    assert [item["target"] for item in decision.fanout] == ["downstairs", "upstairs"]
    assert {item["tool"] for item in decision.fanout} == {"vacuum.dock"}
    assert all(item["arguments"]["action"] == "start" for item in decision.fanout)
    _binding(tmp_path)
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "dock all vacuums"},
        headers=EDGE_HEADERS,
    )
    assert accepted.status_code == 202
    body = accepted.json()
    assert body["route_slots"] == ["vacuum"]
    assert [item["target"] for item in body["fanout"]] == ["downstairs", "upstairs"]
    turn_id = body["turn_id"]
    broker = FakeVacuum()
    assert store.admit_home_action_turn(now=T0) is not None
    finished = run_home_action_turn(
        store,
        turn_id,
        now=T0,
        data_dir=tmp_path,
        vacuum_install=load_vacuum_config(tmp_path),
        vacuum_broker=broker,
        argv=["/nonexistent/dsh"],
    )
    assert finished.status is HomeActionTurnStatus.COMPLETE
    assert broker.calls == [
        ("dock", "downstairs", "start"),
        ("dock", "upstairs", "start"),
    ]
    shown = client.get(f"/v1/voice/turns/{turn_id}", headers=EDGE_HEADERS)
    receipt = shown.json()
    assert [item["status"] for item in receipt["fanout"]] == ["complete", "complete"]
    assert [item["vacuum"]["activity"] for item in receipt["fanout"]] == [
        "returning",
        "returning",
    ]
    assert "downstairs" in receipt["reply"]
    assert "upstairs" in receipt["reply"]


def test_unbound_install_stores_nothing(client: TestClient, store: Store) -> None:
    missing = client.post(
        "/v1/voice/turns",
        json={"text": "start the downstairs vacuum"},
        headers=EDGE_HEADERS,
    )
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "profile_not_executable"
    assert store.list_home_action_turns() == []


def test_stop_without_a_vacuum_word_stays_chat() -> None:
    climate = ClimateInstall(
        upstream="http://127.0.0.1:8123",
        token_env="TWO_CLIMATE_TOKEN",
        zones={
            "living": ZonePolicy(
                zone="living",
                entity_id="climate.living",
                min_celsius=18.0,
                max_celsius=26.0,
                modes=frozenset({"cool", "off"}),
            )
        },
    )
    decision = decide_route("please stop", cards_for(climate=climate, television=None))
    assert decision.profile == "chat"


def test_child_env_and_prompt_omit_the_key_and_nicknames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ECO_API_KEY", "secret-key")
    env = home_child_env()
    assert "ECO_API_KEY" not in env
    assert "secret-key" not in env.values()
    lines = _vacuum_prompt_lines(_install())
    text = "\n".join(lines)
    assert "downstairs" in text
    assert "upstairs" in text
    assert "Downstairs" not in text
    assert "open.ecovacs.com" not in text


def test_vacuum_send_prints_a_queued_receipt(
    client: TestClient,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _binding(tmp_path)
    transport = transport_from_testclient(client)
    assert main(["vacuum", "send", "--text", "start the downstairs vacuum"], request=transport) == 0
    captured = capsys.readouterr()
    assert "profile: home-action" in captured.out
    assert "status: queued" in captured.out
    assert "route_slots: vacuum" in captured.out


def test_robots_refuses_a_missing_binding(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["vacuum", "robots", "--data-dir", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "not enabled" in captured.err
