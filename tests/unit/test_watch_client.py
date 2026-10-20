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

"""Watch edge client: scopes, self-build denial, and voice-turn contract."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from two.api import create_app
from two.api.principal import (
    OPERATOR_HARNESS_PROFILES,
    WATCH_HARNESS_PROFILES,
    AuthenticatedPrincipal,
    allows_self_build,
)
from two.store import Store, open_store
from two.types import HarnessProfile, Scope

EDGE = "edge-secret"
EDGE_HEADERS = {
    "X-Two-Edge-Token": EDGE,
    "X-Two-Client-Id": "watch",
}
MANIFEST = {
    "id": "task-123",
    "repository": "example-service",
    "base_ref": "origin/main",
    "objective": "Add optimistic locking to order updates",
    "acceptance_criteria": ["Concurrent updates cannot silently overwrite"],
    "mode": "unattended",
    "execution_profile": "overnight",
    "cloud_allowed": False,
}


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = open_store(tmp_path / "two.sqlite", check_same_thread=False)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def client(store: Store) -> Iterator[TestClient]:
    app = create_app(store=store, edge_token=EDGE)
    with TestClient(app) as test_client:
        yield test_client


def test_operator_profiles_include_self_build_and_watch_profiles_do_not() -> None:
    operator = AuthenticatedPrincipal(
        id="local",
        method="local_trust",
        scopes=frozenset({Scope.TASKS_CONTROL.value}),
        harness_profiles=OPERATOR_HARNESS_PROFILES,
    )
    watch = AuthenticatedPrincipal(
        id="client:watch",
        method="edge_client",
        scopes=frozenset({Scope.TASKS_READ.value}),
        harness_profiles=WATCH_HARNESS_PROFILES,
    )
    assert allows_self_build(operator) is True
    assert allows_self_build(watch) is False
    assert HarnessProfile.SELF_BUILD.value not in WATCH_HARNESS_PROFILES
    assert HarnessProfile.CHAT.value in WATCH_HARNESS_PROFILES


def test_edge_capabilities_are_the_watch_client(client: TestClient) -> None:
    response = client.get("/v1/system/capabilities", headers=EDGE_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["principal"] == "client:watch"
    assert body["auth"]["method"] == "edge_client"
    assert body["auth"]["edge_available"] is True
    assert body["auth"]["oidc_available"] is False
    assert body["allowed_harness_profiles"] == ["chat", "home-action"]
    assert "tasks:control" not in body["scopes"]
    assert "source:read" not in body["scopes"]
    assert "admin" not in body["scopes"]
    assert "tasks:read" in body["scopes"]
    assert "approvals:decide" in body["scopes"]
    assert "system:read" in body["scopes"]


def test_client_id_without_edge_token_stays_local_trust(client: TestClient) -> None:
    response = client.get("/v1/system/capabilities", headers={"X-Two-Client-Id": "watch"})
    assert response.status_code == 200
    body = response.json()
    assert body["principal"] == "local"
    assert body["auth"]["method"] == "local_trust"
    assert body["allowed_harness_profiles"] == ["self-build"]


def test_bad_edge_token_is_401(client: TestClient) -> None:
    response = client.get(
        "/v1/system/capabilities",
        headers={"X-Two-Edge-Token": "nope", "X-Two-Client-Id": "watch"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_watch_cannot_submit_self_build(client: TestClient) -> None:
    response = client.post("/v1/tasks", json=MANIFEST, headers=EDGE_HEADERS)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert response.json()["detail"] == "client cannot submit self-build"


def test_local_trust_can_still_submit(client: TestClient) -> None:
    response = client.post("/v1/tasks", json=MANIFEST)
    assert response.status_code == 201


def test_watch_voice_turn_rejects_self_build_and_holds_chat(client: TestClient) -> None:
    denied = client.post(
        "/v1/voice/turns",
        json={"text": "set the air con to 20", "profile": "self-build"},
        headers=EDGE_HEADERS,
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "client cannot submit self-build"
    held = client.post(
        "/v1/voice/turns",
        json={"text": "set the air con to 20", "profile": "home-action"},
        headers=EDGE_HEADERS,
    )
    assert held.status_code == 409
    assert held.json()["error"]["code"] == "profile_not_executable"
    chat = client.post(
        "/v1/voice/turns",
        json={"text": "hello", "profile": "chat"},
        headers=EDGE_HEADERS,
    )
    assert chat.status_code == 409


def test_operator_voice_turn_cannot_use_chat(client: TestClient) -> None:
    response = client.post(
        "/v1/voice/turns",
        json={"text": "hello", "profile": "chat"},
    )
    assert response.status_code == 403
    assert "chat" in response.json()["detail"]


def test_watch_cannot_pause_or_read_source(client: TestClient, store: Store) -> None:
    created = client.post("/v1/tasks", json=MANIFEST)
    assert created.status_code == 201
    paused = client.post("/v1/tasks/task-123/pause", json={}, headers=EDGE_HEADERS)
    assert paused.status_code == 403
    assert "tasks:control" in paused.json()["detail"]
    diff = client.get("/v1/tasks/task-123/diff", headers=EDGE_HEADERS)
    assert diff.status_code == 200
    body = diff.json()
    assert body["source_included"] is False
    assert store.get_task("task-123") is not None
