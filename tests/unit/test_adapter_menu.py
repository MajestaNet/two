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

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from two.api import create_app
from two.cli import main
from two.operator.menu import project_adapter_menu
from two.store import Store, open_store
from two.types import Scope

REPO = Path(__file__).resolve().parents[2]
TOKEN = "secret-token"
AUTH = {"Authorization": "Bearer secret-token"}

CLIMATE = """
enabled: true
upstream: http://192.168.1.10:8123
token_env: TWO_CLIMATE_TOKEN
zones:
  living:
    entity_id: climate.living
    min_celsius: 18
    max_celsius: 26
    modes:
      - cool
      - "off"
"""

TELEVISION = """
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
      netflix:
        app_id: "111299001912"
  bedroom:
    address: 192.168.1.41
    mac: "02:00:00:00:00:02"
    token_env: SAMSUNG_TV_BEDROOM_TOKEN
    secure: true
    volume_min: 0
    volume_max: 20
    volume_step: 3
    targets:
      hdmi-1:
        key: KEY_HDMI1
"""

SECRETS = (
    "climate.living",
    "192.168.1.10",
    "TWO_CLIMATE_TOKEN",
    "192.168.1.40",
    "192.168.1.41",
    "02:00:00:00:00:01",
    "02:00:00:00:00:02",
    "SAMSUNG_TV_LIVING_ROOM_TOKEN",
    "111299001912",
    "KEY_HDMI1",
)


def _bind(data_dir: Path) -> None:
    devices = data_dir / "devices"
    devices.mkdir(parents=True)
    (devices / "climate.yaml").write_text(CLIMATE, encoding="utf-8")
    (devices / "tv.yaml").write_text(TELEVISION, encoding="utf-8")


def test_menu_lists_zone_and_set_ids_without_secrets(tmp_path: Path) -> None:
    _bind(tmp_path)
    body = project_adapter_menu(tmp_path, repo_root=REPO).model_dump()
    blob = json.dumps(body)
    for secret in SECRETS:
        assert secret not in blob
    assert "entity_id" not in blob
    assert "token_env" not in blob
    by_id = {slot["id"]: slot for slot in body["slots"]}
    assert [slot["id"] for slot in body["slots"]][:2] == ["cli", "console"]
    assert by_id["cli"]["install_enabled"] is True
    assert by_id["console"]["default_enabled"] is False
    assert by_id["console"]["install_enabled"] is False
    assert by_id["console"]["harness_profiles"] == ["chat"]
    assert by_id["climate"]["install_enabled"] is True
    assert by_id["climate"]["devices"] == [{"id": "living", "kind": "zone"}]
    assert by_id["tv"]["devices"] == [
        {"id": "living-room", "kind": "set"},
        {"id": "bedroom", "kind": "set"},
    ]


def test_disabled_binding_lists_no_devices(tmp_path: Path) -> None:
    devices = tmp_path / "devices"
    devices.mkdir()
    (devices / "climate.yaml").write_text("enabled: false\n", encoding="utf-8")
    body = project_adapter_menu(tmp_path, repo_root=REPO).model_dump()
    climate = next(slot for slot in body["slots"] if slot["id"] == "climate")
    assert climate["install_enabled"] is False
    assert climate["devices"] == []


def test_adapters_json_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind(tmp_path)
    monkeypatch.setenv("TWO_DATA_DIR", str(tmp_path))
    assert main(["adapters", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    climate = next(slot for slot in body["slots"] if slot["id"] == "climate")
    assert climate["devices"] == [{"id": "living", "kind": "zone"}]


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = open_store(tmp_path / "two.sqlite", check_same_thread=False)
    try:
        yield opened
    finally:
        opened.close()


def test_system_adapters_route_redacts_bindings(store: Store, tmp_path: Path) -> None:
    data = tmp_path / "data"
    _bind(data)
    app = create_app(store=store, data_dir=data)
    with TestClient(app) as client:
        response = client.get("/v1/system/adapters")
    assert response.status_code == 200
    blob = response.text
    for secret in SECRETS:
        assert secret not in blob
    body = response.json()
    climate = next(slot for slot in body["slots"] if slot["id"] == "climate")
    television = next(slot for slot in body["slots"] if slot["id"] == "tv")
    assert climate["devices"] == [{"id": "living", "kind": "zone"}]
    assert [item["id"] for item in television["devices"]] == ["living-room", "bedroom"]


def test_system_adapters_requires_scope(store: Store) -> None:
    remote = create_app(store=store, require_auth=True, auth_token=TOKEN)
    with TestClient(remote) as client:
        assert client.get("/v1/system/adapters").status_code == 401
        assert client.get("/v1/system/adapters", headers=AUTH).status_code == 200
    limited = create_app(
        store=store,
        require_auth=True,
        auth_token=TOKEN,
        operator_scopes={Scope.TASKS_READ},
    )
    with TestClient(limited) as client:
        assert client.get("/v1/system/adapters", headers=AUTH).status_code == 403
