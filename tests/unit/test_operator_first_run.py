# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

"""First-run operator steps. No live television or Ecovacs account."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from two.api import create_app
from two.cli import main
from two.client import transport_from_testclient
from two.operator.assist import AssistError, install_status
from two.operator.first_run import (
    account_reply,
    env_presence,
    list_account,
    pair_device,
    pair_reply,
)
from two.operator.hostenv import parse_env_file
from two.scheduler import Scheduler
from two.store import OperatorTurnStatus, Store, open_store
from two.types import ErrorCode
from two.worker import AcpWorker
from two.worker.models import ChildConfig

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
FAKE_CHILD = Path(__file__).parent / "fixtures" / "acp" / "fake_acp_child.py"
EDGE = "edge-secret"
EDGE_HEADERS = {"X-Two-Edge-Token": EDGE, "X-Two-Client-Id": "watch"}
FAST_CHILD = ChildConfig(
    cooperative_seconds=0.4,
    grace_seconds=0.4,
    inference_timeout_seconds=2.0,
    stream_liveness_seconds=0.2,
)
TV_DOC = """
enabled: true
sets:
  living-room:
    address: 192.168.1.40
    mac: "02:00:00:00:00:01"
    token_env: SAMSUNG_TV_LIVING_ROOM_TOKEN
    secure: true
    volume_min: 0
    volume_max: 30
    volume_step: 3
    targets:
      hdmi-1:
        key: KEY_HDMI1
"""


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


def _argv(tool: str, arguments: object, invoke: Path) -> list[str]:
    return [
        sys.executable,
        str(FAKE_CHILD),
        "--mode",
        "home-tool",
        "--tool",
        tool,
        "--arguments",
        json.dumps(arguments),
        "--invoke-out",
        str(invoke),
    ]


def test_status_reports_env_presence_without_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ECO_API_KEY", raising=False)
    monkeypatch.delenv("TWO_CLIMATE_TOKEN", raising=False)
    (tmp_path / "env").write_text("ECO_API_KEY=super-secret-token\n", encoding="utf-8")
    text = install_status(tmp_path)
    assert "ECO_API_KEY: present" in text
    assert "TWO_CLIMATE_TOKEN: missing" in text
    assert "super-secret-token" not in text
    names = {item.name: item.present for item in env_presence(tmp_path)}
    assert names["ECO_API_KEY"] is True
    assert names["TWO_CLIMATE_TOKEN"] is False


def test_list_account_does_not_need_an_enabled_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ECO_API_KEY", raising=False)
    (tmp_path / "env").write_text("ECO_API_KEY=super-secret-token\n", encoding="utf-8")

    def fake_list(api_host: str, token: str) -> tuple[str, ...]:
        assert api_host == "open.ecovacs.com"
        assert token == "super-secret-token"
        return ("Bob", "Lynne")

    listing = list_account(
        "vacuum",
        {},
        data_dir=tmp_path,
        list_nicknames=fake_list,
    )
    assert listing.nicknames == ("Bob", "Lynne")
    reply = account_reply(listing)
    assert "Bob" in reply
    assert "super-secret-token" not in reply
    with pytest.raises(AssistError) as missing:
        list_account("vacuum", {}, data_dir=tmp_path / "empty", list_nicknames=fake_list)
    assert missing.value.code == ErrorCode.INSTALL_ENV_MISSING.value


def test_pair_device_stores_the_token_and_omits_it_from_the_reply(tmp_path: Path) -> None:
    devices = tmp_path / "devices"
    devices.mkdir()
    (devices / "tv.yaml").write_text(TV_DOC, encoding="utf-8")

    def fake_pair(_policy: object) -> str:
        return "tv-token-value"

    stored = pair_device("tv", "living-room", data_dir=tmp_path, pair=fake_pair)
    assert stored.stored is True
    assert stored.token_env == "SAMSUNG_TV_LIVING_ROOM_TOKEN"
    env_path = tmp_path / "env"
    parsed = parse_env_file(env_path)
    assert parsed["SAMSUNG_TV_LIVING_ROOM_TOKEN"] == "tv-token-value"
    reply = pair_reply(stored)
    assert "SAMSUNG_TV_LIVING_ROOM_TOKEN" in reply
    assert "tv-token-value" not in reply


def test_watch_cannot_list_or_pair(client: TestClient, tmp_path: Path) -> None:
    env = client.get("/v1/install/env", headers=EDGE_HEADERS)
    assert env.status_code == 403
    robots = client.post("/v1/install/vacuum/robots", json={}, headers=EDGE_HEADERS)
    assert robots.status_code == 403
    pair = client.post(
        "/v1/install/tv/pair",
        json={"set": "living-room"},
        headers=EDGE_HEADERS,
    )
    assert pair.status_code == 403
    apps = client.get("/v1/install/tv/apps?set=living-room", headers=EDGE_HEADERS)
    assert apps.status_code == 403
    local = client.get("/v1/install/env")
    assert local.status_code == 200
    assert local.json()["names"]


def test_api_lists_nicknames_and_cli_prints_them(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("ECO_API_KEY", raising=False)
    monkeypatch.setenv("ECO_API_KEY", "super-secret-token")

    def fake_list(api_host: str, token: str) -> tuple[str, ...]:
        del api_host, token
        return ("Bob", "Lynne")

    monkeypatch.setattr("two.operator.first_run._ecovacs_nicknames", fake_list)
    listed = client.post("/v1/install/vacuum/robots", json={})
    assert listed.status_code == 200
    body = listed.json()
    assert body["nicknames"] == ["Bob", "Lynne"]
    assert "super-secret-token" not in json.dumps(body)
    transport = transport_from_testclient(client)
    assert (
        main(
            ["vacuum", "robots", "--data-dir", str(tmp_path)],
            request=transport,
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Bob" in out
    assert "super-secret-token" not in out


def test_fake_child_lists_account_nicknames(
    store: Store,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ECO_API_KEY", "super-secret-token")
    monkeypatch.setattr(
        "two.operator.first_run._ecovacs_nicknames",
        lambda _host, _token: ("Bob", "Lynne"),
    )
    turn = store.insert_operator_turn("list robots", "local", turn_id="list-1", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    invoke = tmp_path / "invoke.txt"
    worker = AcpWorker(
        store,
        operator_argv=_argv("install.list_account", {"slot": "vacuum"}, invoke),
        data_dir=tmp_path,
        child_config=FAST_CHILD,
    )
    finished = worker.run_operator(turn.id, now=T0)
    assert finished.status is OperatorTurnStatus.COMPLETE
    assert finished.reply_text is not None
    assert "Bob" in finished.reply_text
    assert "super-secret-token" not in finished.reply_text
    assert not invoke.exists()
