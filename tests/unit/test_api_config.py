# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for B14 slice 3 typed project/config candidates."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from two.api import create_app
from two.store import SCHEMA_VERSION, Store, open_store
from two.types import Scope

TOKEN = "secret-token"
AUTH = {"Authorization": "Bearer secret-token"}
REPO_YAML = """
id: example-service
display_name: Example Service
language: python
validation_profile: standard
allowed_paths:
  - src/**
  - /Users/operator/canonical/example
forbidden_paths:
  - .env
commands:
  test: pytest -q --secret never-show
  lint: ruff check src
secret_scan: true
network:
  allow_package_downloads: true
  allow_external_mutations: false
"""


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = open_store(tmp_path / "two.sqlite", check_same_thread=False)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def repos_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "repositories"
    directory.mkdir()
    (directory / "example-service.yaml").write_text(REPO_YAML, encoding="utf-8")
    return directory


@pytest.fixture
def client(store: Store, repos_dir: Path) -> Iterator[TestClient]:
    app = create_app(store=store, repositories_dir=repos_dir)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def remote(store: Store, repos_dir: Path) -> Iterator[TestClient]:
    app = create_app(
        store=store,
        require_auth=True,
        auth_token=TOKEN,
        repositories_dir=repos_dir,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_schema_is_v6(store: Store) -> None:
    assert store.schema_version() == SCHEMA_VERSION
    assert SCHEMA_VERSION == 6


def test_create_and_get_project(client: TestClient) -> None:
    created = client.post(
        "/v1/projects",
        json={
            "id": "orders",
            "display_name": "Orders",
            "description": "Order services",
            "repository_ids": ["example-service"],
            "default_repository": "example-service",
            "default_base_ref": "origin/main",
            "default_mode": "interactive",
            "labels": ["team-a"],
        },
    )
    assert created.status_code == 201
    assert created.headers["etag"] == '"1"'
    body = created.json()
    assert body["id"] == "orders"
    assert body["repository_ids"] == ["example-service"]
    assert "commands" not in body
    listed = client.get("/v1/projects")
    assert listed.status_code == 200
    assert listed.json()["projects"][0]["id"] == "orders"
    fetched = client.get("/v1/projects/orders")
    assert fetched.status_code == 200
    assert fetched.json()["display_name"] == "Orders"
    missing = client.get("/v1/projects/missing")
    assert missing.status_code == 404
    duplicate = client.post("/v1/projects", json={"id": "orders", "display_name": "Orders"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_project"


def test_projects_unauthenticated_remote_is_401(remote: TestClient) -> None:
    assert remote.get("/v1/projects").status_code == 401
    assert remote.post("/v1/projects", json={"display_name": "X"}).status_code == 401
    assert remote.get("/v1/projects/x").status_code == 401


def test_projects_missing_scope_is_403(store: Store, repos_dir: Path) -> None:
    limited = create_app(
        store=store,
        require_auth=True,
        auth_token=TOKEN,
        repositories_dir=repos_dir,
        operator_scopes={Scope.CONFIG_READ, Scope.SYSTEM_READ},
    )
    with TestClient(limited) as client:
        denied = client.post(
            "/v1/projects",
            json={"display_name": "X"},
            headers=AUTH,
        )
        assert denied.status_code == 403
        listed = client.get("/v1/projects", headers=AUTH)
        assert listed.status_code == 200


def test_candidate_rejects_secret_path_yaml_and_shell(client: TestClient) -> None:
    secret = client.post(
        "/v1/repositories/example-service/config-candidates",
        json={"display_name": "AKIAIOSFODNN7EXAMPLE12"},
    )
    assert secret.status_code == 422
    assert secret.json()["error"]["code"] == "validation_error"
    assert any(item["code"] == "secret" for item in secret.json()["field_errors"])

    host = client.post(
        "/v1/repositories/example-service/config-candidates",
        json={"allowed_path_patterns": ["/Users/operator/secret"]},
    )
    assert host.status_code == 422
    assert any(item["code"] == "host_path" for item in host.json()["field_errors"])

    yaml_blob = client.post(
        "/v1/repositories/example-service/config-candidates",
        json={"display_name": "---\ncommands:\n  test: rm -rf /"},
    )
    assert yaml_blob.status_code == 422
    codes = {item["code"] for item in yaml_blob.json()["field_errors"]}
    assert "yaml_blob" in codes or "shell_string" in codes

    shell = client.post(
        "/v1/repositories/example-service/config-candidates",
        json={"display_name": "ok && rm -rf /"},
    )
    assert shell.status_code == 422
    assert any(item["code"] == "shell_string" for item in shell.json()["field_errors"])

    command = client.post(
        "/v1/repositories/example-service/config-candidates",
        json={"commands": "pytest -q"},
    )
    assert command.status_code == 422


def test_display_candidate_activates_with_config_write(client: TestClient) -> None:
    baseline = client.get("/v1/repositories/example-service")
    assert baseline.status_code == 200
    etag = baseline.headers["etag"]
    candidate = client.post(
        "/v1/repositories/example-service/config-candidates",
        json={"display_name": "Friendly Example"},
    )
    assert candidate.status_code == 201
    body = candidate.json()
    assert body["status"] == "pending"
    assert body["risk_class"] == "display"
    assert body["digest"]
    assert any(item["field"] == "display_name" for item in body["redacted_diff"])
    dumped = json.dumps(body)
    assert "pytest" not in dumped
    assert "/Users/operator" not in dumped

    missing = client.post(
        "/v1/repositories/example-service/config-candidates/1/activate",
        json={},
    )
    assert missing.status_code == 412
    stale = client.post(
        "/v1/repositories/example-service/config-candidates/1/activate",
        json={},
        headers={"If-Match": '"999"'},
    )
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "stale_revision"

    activated = client.post(
        "/v1/repositories/example-service/config-candidates/1/activate",
        json={},
        headers={"If-Match": etag},
    )
    assert activated.status_code == 200
    assert activated.json()["activated"] is True
    assert activated.json()["approval_required"] is False
    viewed = client.get("/v1/repositories/example-service").json()
    assert viewed["display_name"] == "Friendly Example"
    assert viewed["revision"] == 2
    assert "pytest" not in json.dumps(viewed)
    assert "/Users/operator" not in json.dumps(viewed)
    assert "test" in viewed["gate_names"]


def test_capability_activation_requires_admin_and_digest(store: Store, repos_dir: Path) -> None:
    writer = create_app(
        store=store,
        require_auth=True,
        auth_token=TOKEN,
        repositories_dir=repos_dir,
        operator_scopes={Scope.CONFIG_READ, Scope.CONFIG_WRITE, Scope.SYSTEM_READ},
    )
    with TestClient(writer) as client:
        etag = client.get("/v1/repositories/example-service", headers=AUTH).headers["etag"]
        candidate = client.post(
            "/v1/repositories/example-service/config-candidates",
            json={"allowed_path_patterns": ["src/**", "tests/**"]},
            headers=AUTH,
        )
        assert candidate.status_code == 201
        assert candidate.json()["risk_class"] == "capability"
        digest = candidate.json()["digest"]
        denied = client.post(
            "/v1/repositories/example-service/config-candidates/1/activate",
            json={"action_digest": digest, "decision": "approve"},
            headers={**AUTH, "If-Match": etag},
        )
        assert denied.status_code == 403

    admin_only = create_app(
        store=store,
        require_auth=True,
        auth_token=TOKEN,
        repositories_dir=repos_dir,
        operator_scopes={
            Scope.CONFIG_READ,
            Scope.CONFIG_WRITE,
            Scope.ADMIN,
            Scope.SYSTEM_READ,
        },
    )
    with TestClient(admin_only) as client:
        etag = client.get("/v1/repositories/example-service", headers=AUTH).headers["etag"]
        pending = client.post(
            "/v1/repositories/example-service/config-candidates/1/activate",
            json={},
            headers={**AUTH, "If-Match": etag},
        )
        assert pending.status_code == 200
        assert pending.json()["activated"] is False
        assert pending.json()["approval_required"] is True
        assert pending.json()["approval"]["status"] == "open"
        mismatch = client.post(
            "/v1/repositories/example-service/config-candidates/1/activate",
            json={"action_digest": "deadbeef", "decision": "approve"},
            headers={**AUTH, "If-Match": etag},
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["error"]["code"] == "stale_digest"
        still_open = client.post(
            "/v1/repositories/example-service/config-candidates/1/activate",
            json={"action_digest": digest, "decision": "approve"},
            headers={**AUTH, "If-Match": etag},
        )
        assert still_open.status_code == 403

    full = create_app(
        store=store,
        require_auth=True,
        auth_token=TOKEN,
        repositories_dir=repos_dir,
    )
    with TestClient(full) as client:
        etag = client.get("/v1/repositories/example-service", headers=AUTH).headers["etag"]
        wrong = client.post(
            "/v1/repositories/example-service/config-candidates/1/activate",
            json={"action_digest": "not-the-digest", "decision": "approve"},
            headers={**AUTH, "If-Match": etag},
        )
        assert wrong.status_code == 409
        ok = client.post(
            "/v1/repositories/example-service/config-candidates/1/activate",
            json={"action_digest": digest, "decision": "approve"},
            headers={**AUTH, "If-Match": etag},
        )
        assert ok.status_code == 200
        assert ok.json()["activated"] is True
        viewed = client.get("/v1/repositories/example-service", headers=AUTH).json()
        assert viewed["allowed_path_patterns"] == ["src/**", "tests/**"]
        assert "pytest" not in json.dumps(viewed)

        changed = client.post(
            "/v1/repositories/example-service/config-candidates",
            json={"gate_names": ["test", "lint"]},
            headers=AUTH,
        )
        assert changed.status_code == 201
        new_digest = changed.json()["digest"]
        assert new_digest != digest
        etag2 = client.get("/v1/repositories/example-service", headers=AUTH).headers["etag"]
        reuse = client.post(
            f"/v1/repositories/example-service/config-candidates/{changed.json()['revision']}/activate",
            json={"action_digest": digest, "decision": "approve"},
            headers={**AUTH, "If-Match": etag2},
        )
        assert reuse.status_code == 409


def test_project_display_and_membership_activation(client: TestClient) -> None:
    created = client.post(
        "/v1/projects",
        json={"id": "shop", "display_name": "Shop", "repository_ids": ["example-service"]},
    )
    assert created.status_code == 201
    etag = created.headers["etag"]
    display = client.post(
        "/v1/projects/shop/config-candidates",
        json={"display_name": "Shopfront", "default_mode": "review-only"},
    )
    assert display.status_code == 201
    assert display.json()["risk_class"] == "display"
    activated = client.post(
        "/v1/projects/shop/config-candidates/1/activate",
        json={},
        headers={"If-Match": etag},
    )
    assert activated.status_code == 200
    assert client.get("/v1/projects/shop").json()["display_name"] == "Shopfront"

    etag2 = client.get("/v1/projects/shop").headers["etag"]
    membership = client.post(
        "/v1/projects/shop/config-candidates",
        json={"repository_ids": ["example-service"], "default_repository": "example-service"},
    )
    assert membership.status_code == 201
    assert membership.json()["risk_class"] == "capability"
    digest = membership.json()["digest"]
    pending = client.post(
        "/v1/projects/shop/config-candidates/2/activate",
        json={},
        headers={"If-Match": etag2},
    )
    assert pending.json()["activated"] is False
    done = client.post(
        "/v1/projects/shop/config-candidates/2/activate",
        json={"action_digest": digest, "decision": "approve"},
        headers={"If-Match": etag2},
    )
    assert done.status_code == 200
    assert done.json()["activated"] is True
    assert client.get("/v1/projects/shop").json()["default_repository"] == "example-service"


def test_slice2_repo_reads_stay_redacted(client: TestClient) -> None:
    listed = client.get("/v1/repositories")
    assert listed.status_code == 200
    body = client.get("/v1/repositories/example-service").json()
    dumped = json.dumps(body)
    assert "pytest" not in dumped
    assert "never-show" not in dumped
    assert "/Users/operator" not in dumped
    empty = client.get("/v1/projects")
    assert empty.json()["projects"] == []
