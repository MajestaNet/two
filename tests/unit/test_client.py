# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for the stdlib control-API client."""

from __future__ import annotations

import ast
import socket
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from two.api import bind as api_bind
from two.api import create_app
from two.client import (
    DEFAULT_BIND,
    DEFAULT_PORT,
    ENV_BIND,
    ENV_PORT,
    ENV_SOCKET,
    ENV_TOKEN,
    ControlApiError,
    ControlClient,
    UnixHTTPConnection,
    transport_from_testclient,
)
from two.manifest import TaskManifest
from two.store import Store, open_store
from two.types import ErrorCode

REPO_ROOT = Path(__file__).resolve().parents[2]

MANIFEST = {
    "id": "task-123",
    "repository": "example-service",
    "base_ref": "origin/main",
    "objective": "Add optimistic locking to order updates",
    "acceptance_criteria": ["Concurrent updates cannot silently overwrite"],
    "mode": "unattended",
    "execution_profile": "overnight",
    "cloud_allowed": False,
    "time_budget_minutes": 480,
    "max_model_turns": 30,
    "max_repair_cycles": 6,
    "no_progress_limit": 2,
}


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = open_store(tmp_path / "two.sqlite", check_same_thread=False)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def api_client(store: Store) -> Iterator[TestClient]:
    app = create_app(store=store)
    with TestClient(app) as client:
        yield client


def test_submit_duplicate_returns_existing_projection(api_client: TestClient) -> None:
    client = ControlClient(request=transport_from_testclient(api_client))
    manifest = TaskManifest.model_validate(MANIFEST)
    first = client.submit_task(manifest)
    second = client.submit_task(manifest)
    assert first.id == second.id == "task-123"
    assert second.lifecycle.value == "queued"


def test_bearer_token_required_when_api_requires_auth(store: Store) -> None:
    app = create_app(store=store, require_auth=True, auth_token="secret-token")
    with TestClient(app) as api:
        denied = ControlClient(request=transport_from_testclient(api), token=None)
        with pytest.raises(ControlApiError) as exc_info:
            denied.submit_task(TaskManifest.model_validate(MANIFEST))
        assert exc_info.value.status_code == 401
        assert exc_info.value.code == ErrorCode.UNAUTHORIZED.value
        allowed = ControlClient(request=transport_from_testclient(api), token="secret-token")
        view = allowed.submit_task(TaskManifest.model_validate(MANIFEST))
        assert view.id == "task-123"


def test_client_injects_authorization_header() -> None:
    seen: dict[str, Mapping[str, str]] = {}

    def fake(
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
    ) -> object:
        del method, path, body
        seen["headers"] = headers
        raise AssertionError("stop")

    client = ControlClient(request=fake, token="secret-token")  # type: ignore[arg-type]
    with pytest.raises(AssertionError, match="stop"):
        client.get_task("task-123")
    assert seen["headers"]["Authorization"] == "Bearer secret-token"


def test_unix_connection_dials_af_unix(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class FakeSocket:
        def settimeout(self, value: object) -> None:
            seen["timeout"] = value

        def connect(self, path: object) -> None:
            seen["path"] = path

    def fake_socket(family: int, kind: int) -> FakeSocket:
        seen["family"] = family
        seen["kind"] = kind
        return FakeSocket()

    monkeypatch.setattr("two.client.socket.socket", fake_socket)
    conn = UnixHTTPConnection("/tmp/two.sock", timeout=5.0)
    conn.connect()
    assert seen["family"] == socket.AF_UNIX
    assert seen["kind"] == socket.SOCK_STREAM
    assert seen["path"] == "/tmp/two.sock"


def test_client_defaults_match_api_bind() -> None:
    assert DEFAULT_BIND == api_bind.DEFAULT_BIND
    assert DEFAULT_PORT == api_bind.DEFAULT_PORT
    assert ENV_BIND == api_bind.ENV_BIND
    assert ENV_PORT == api_bind.ENV_PORT
    assert ENV_SOCKET == api_bind.ENV_SOCKET
    assert ENV_TOKEN == api_bind.ENV_TOKEN


def test_client_source_is_stdlib_http() -> None:
    source = (REPO_ROOT / "src" / "two" / "client.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert "httpx" not in imported
    assert "urllib.request" in imported
    assert "http.client" in imported
    assert "two.projection" in imported
    assert all(not name.startswith("two.store") for name in imported)
    assert "httpx" not in source
