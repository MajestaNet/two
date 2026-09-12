# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for B14 slice 1 client-API contract foundations."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from two.api import create_app
from two.store import Store, open_store
from two.types import Scope

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

TOKEN = "secret-token"
AUTH = {"Authorization": "Bearer secret-token"}


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = open_store(tmp_path / "two.sqlite", check_same_thread=False)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def client(store: Store) -> Iterator[TestClient]:
    app = create_app(store=store)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def remote(store: Store) -> Iterator[TestClient]:
    app = create_app(store=store, require_auth=True, auth_token=TOKEN)
    with TestClient(app) as test_client:
        yield test_client


def _create(client: TestClient, headers: dict[str, str] | None = None) -> dict[str, object]:
    response = client.post("/v1/tasks", json=MANIFEST, headers=headers)
    assert response.status_code == 201
    return response.json()


def test_capabilities_local_trust(client: TestClient) -> None:
    response = client.get("/v1/system/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["api_versions"] == ["v1"]
    assert body["principal"] == "local"
    assert body["auth"]["method"] == "local_trust"
    assert body["auth"]["oidc_available"] is False
    assert body["auth"]["mobile_ready"] is False
    assert body["features"]["idempotency_keys"] is True
    assert body["features"]["etags"] is True
    assert body["features"]["conversation"] is False
    assert body["features"]["graph"] is True
    assert "tasks:read" in body["scopes"]
    assert "events:audit" in body["scopes"]
    assert "X-Correlation-ID" in response.headers


def test_capabilities_unauthenticated_remote_is_401(remote: TestClient) -> None:
    denied = remote.get("/v1/system/capabilities")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "unauthorized"
    assert denied.json()["correlation_id"]


def test_capabilities_bearer_lists_server_principal(remote: TestClient) -> None:
    body = remote.get("/v1/system/capabilities", headers=AUTH).json()
    assert body["principal"] == "token:operator"
    assert body["auth"]["method"] == "bearer_token"
    assert "admin" in body["scopes"]


def test_request_body_cannot_elevate_network_principal(remote: TestClient, store: Store) -> None:
    _create(remote, AUTH)
    paused = remote.post(
        "/v1/tasks/task-123/pause",
        json={"principal": "admin"},
        headers=AUTH,
    )
    assert paused.status_code == 200
    assert paused.json()["lifecycle"] == "paused"
    event = store.list_events("task-123")[-1]
    assert event.payload["principal"] == "token:operator"
    decided = remote.post(
        "/v1/tasks/task-123/approvals/ap-missing/decide",
        json={
            "decision": "approve",
            "actor": "admin",
            "action_digest": "sha256:deadbeef",
            "scopes": ["admin"],
        },
        headers=AUTH,
    )
    assert decided.status_code == 422
    assert decided.json()["error"]["code"] == "validation_error"
    fields = {item["field"] for item in decided.json()["field_errors"]}
    assert any("scopes" in field for field in fields)


def test_local_trust_keeps_cli_principal_label(client: TestClient, store: Store) -> None:
    _create(client)
    paused = client.post(
        "/v1/tasks/task-123/pause",
        json={"principal": "cli:operator", "reason": "step away"},
    )
    assert paused.status_code == 200
    assert store.list_events("task-123")[-1].payload["principal"] == "cli:operator"


def test_missing_scope_is_403(store: Store) -> None:
    privileged = create_app(store=store, require_auth=True, auth_token=TOKEN)
    with TestClient(privileged) as client:
        _create(client, AUTH)
    limited = create_app(
        store=store,
        require_auth=True,
        auth_token=TOKEN,
        operator_scopes={Scope.TASKS_READ, Scope.SYSTEM_READ},
    )
    with TestClient(limited) as client:
        listed = client.get("/v1/tasks", headers=AUTH)
        assert listed.status_code == 200
        paused = client.post("/v1/tasks/task-123/pause", headers=AUTH)
        assert paused.status_code == 403
        assert paused.json()["error"]["code"] == "forbidden"
        events = client.get("/v1/tasks/task-123/events", headers=AUTH)
        assert events.status_code == 403
        assert "events:audit" in events.json()["error"]["message"]


def test_etag_and_stale_if_match(client: TestClient) -> None:
    created = client.post("/v1/tasks", json=MANIFEST)
    etag = created.headers["etag"]
    assert created.json()["revision"] >= 1
    fetched = client.get("/v1/tasks/task-123")
    assert fetched.headers["etag"] == etag
    stale = client.post(
        "/v1/tasks/task-123/pause",
        headers={"If-Match": '"999999"'},
    )
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "stale_revision"
    paused = client.post("/v1/tasks/task-123/pause", headers={"If-Match": etag})
    assert paused.status_code == 200
    assert paused.headers["etag"] != etag
    assert paused.json()["revision"] > created.json()["revision"]


def test_idempotent_retry_and_changed_payload(client: TestClient, store: Store) -> None:
    _create(client)
    headers = {"Idempotency-Key": "pause-1"}
    first = client.post("/v1/tasks/task-123/pause", headers=headers)
    assert first.status_code == 200
    first_rev = first.json()["revision"]
    replay = client.post("/v1/tasks/task-123/pause", headers=headers)
    assert replay.status_code == 200
    assert replay.json()["revision"] == first_rev
    paused_events = [
        event for event in store.list_events("task-123") if event.type == "task.paused"
    ]
    assert len(paused_events) == 1
    conflict = client.post(
        "/v1/tasks/task-123/resume",
        headers={"Idempotency-Key": "pause-1"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"


def test_correlation_id_echo(client: TestClient) -> None:
    missing = client.get(
        "/v1/tasks/missing",
        headers={"X-Correlation-ID": "corr-test-1"},
    )
    assert missing.status_code == 404
    assert missing.headers["x-correlation-id"] == "corr-test-1"
    assert missing.json()["correlation_id"] == "corr-test-1"


def test_graph_stays_null(client: TestClient) -> None:
    body = _create(client)
    assert body["graph"] is None
    fetched = client.get("/v1/tasks/task-123").json()
    assert fetched["graph"] is None
    assert fetched["revision"] >= 1
