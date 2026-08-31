# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline unit tests for the channel-neutral control API (B07)."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from two.api import (
    DEFAULT_BIND,
    DEFAULT_PORT,
    ApiPublicBindError,
    BindPolicyError,
    create_app,
    resolve_bind,
)
from two.api.server import serve
from two.manifest import TaskManifest
from two.store import Store, open_store
from two.types import LifecycleState, WorkflowStage

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "src" / "two" / "api"

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
def client(store: Store) -> Iterator[TestClient]:
    app = create_app(store=store)
    with TestClient(app) as test_client:
        yield test_client


def test_health_is_process_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "service": "two-api"}
    assert "ollama" not in body
    assert "qwen" not in str(body).lower()


def test_create_task_then_get_projection(client: TestClient, store: Store) -> None:
    created = client.post("/v1/tasks", json=MANIFEST)
    assert created.status_code == 201
    assert created.headers["location"] == "/v1/tasks/task-123"
    body = created.json()
    assert body["id"] == "task-123"
    assert body["objective"] == MANIFEST["objective"]
    assert body["lifecycle"] == LifecycleState.QUEUED.value
    assert body["stage"] == WorkflowStage.INTAKE.value
    assert body["plan"] is None
    assert body["todos"] == []
    assert body["diff_summary"]["placeholder"] is True
    assert body["validation_summary"]["passed"] is None
    assert body["blockers"] == []
    assert body["questions"] == []
    assert body["budgets"]["time_budget_minutes"] == 480
    persisted = store.get_task("task-123")
    assert persisted is not None
    assert persisted.lifecycle is LifecycleState.QUEUED
    fetched = client.get("/v1/tasks/task-123")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == "task-123"
    assert fetched.json()["lifecycle"] == "queued"


def test_duplicate_create_is_409(client: TestClient) -> None:
    assert client.post("/v1/tasks", json=MANIFEST).status_code == 201
    duplicate = client.post("/v1/tasks", json=MANIFEST)
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


def test_unknown_task_is_404(client: TestClient) -> None:
    assert client.get("/v1/tasks/missing").status_code == 404
    assert client.post("/v1/tasks/missing/pause").status_code == 404
    assert client.get("/v1/tasks/missing/report").status_code == 404


def test_pause_resume_cancel(client: TestClient, store: Store) -> None:
    client.post("/v1/tasks", json=MANIFEST)
    paused = client.post("/v1/tasks/task-123/pause")
    assert paused.status_code == 200
    assert paused.json()["lifecycle"] == "paused"
    assert store.get_task("task-123") is not None
    assert store.get_task("task-123").lifecycle is LifecycleState.PAUSED
    resumed = client.post("/v1/tasks/task-123/resume")
    assert resumed.status_code == 200
    assert resumed.json()["lifecycle"] == "queued"
    cancelled = client.post("/v1/tasks/task-123/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["lifecycle"] == "cancelled"
    assert client.post("/v1/tasks/task-123/pause").status_code == 409
    assert client.post("/v1/tasks/task-123/resume").status_code == 409


def test_post_message_persists_event(client: TestClient, store: Store) -> None:
    client.post("/v1/tasks", json=MANIFEST)
    response = client.post(
        "/v1/tasks/task-123/messages",
        json={"text": "prefer the lock on the row", "source": "cli"},
    )
    assert response.status_code == 201
    event_id = response.json()["event_id"]
    event = store.get_event(event_id)
    assert event is not None
    assert event.type == "task.message"
    assert event.payload["text"] == "prefer the lock on the row"


def test_report_placeholder(client: TestClient) -> None:
    client.post("/v1/tasks", json=MANIFEST)
    response = client.get("/v1/tasks/task-123/report")
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "task-123"
    assert body["assembled"] is False
    assert body["objective"] == MANIFEST["objective"]


def test_approval_decide_404_without_row(client: TestClient) -> None:
    client.post("/v1/tasks", json=MANIFEST)
    response = client.post(
        "/v1/tasks/task-123/approvals/ap-missing/decide",
        json={"decision": "approve", "action_digest": "sha256:missing"},
    )
    assert response.status_code == 404


def test_approval_decide_persists_when_row_exists(client: TestClient, store: Store) -> None:
    client.post("/v1/tasks", json=MANIFEST)
    store.insert_approval(
        "ap-1",
        "task-123",
        action_class="dependency_lock_change",
        action_digest="sha256:deadbeef",
        paths=["uv.lock"],
    )
    store.insert_question(
        "q-1",
        "task-123",
        stage=WorkflowStage.PLAN,
        options=["keep lock", "retry"],
        reason="ambiguous strategy",
    )
    projection = client.get("/v1/tasks/task-123").json()
    assert projection["questions"][0]["id"] == "q-1"
    decided = client.post(
        "/v1/tasks/task-123/approvals/ap-1/decide",
        json={"decision": "reject", "actor": "operator", "action_digest": "sha256:deadbeef"},
    )
    assert decided.status_code == 200
    body = decided.json()
    assert body["ignored"] is False
    assert body["decision"] == "reject"
    assert body["action_digest"] == "sha256:deadbeef"
    assert body["principal"] == "operator"
    assert "status" not in body or body.get("status") != "recorded"
    event = store.get_event(body["event_id"])
    assert event is not None
    assert event.type == "approval.decide"
    assert event.payload["action_digest"] == "sha256:deadbeef"
    assert event.payload["ignored"] is False
    row = store.get_approval("ap-1")
    assert row is not None
    assert row.status == "rejected"
    assert row.action_digest == "sha256:deadbeef"


def test_duplicate_decide_returns_ignored(client: TestClient, store: Store) -> None:
    client.post("/v1/tasks", json=MANIFEST)
    store.insert_approval(
        "ap-1",
        "task-123",
        action_class="dependency_lock_change",
        action_digest="sha256:deadbeef",
        paths=["uv.lock"],
    )
    first = client.post(
        "/v1/tasks/task-123/approvals/ap-1/decide",
        json={"decision": "approve", "actor": "first", "action_digest": "sha256:deadbeef"},
    )
    assert first.status_code == 200
    assert first.json()["ignored"] is False
    duplicate = client.post(
        "/v1/tasks/task-123/approvals/ap-1/decide",
        json={"decision": "reject", "actor": "second", "action_digest": "sha256:deadbeef"},
    )
    assert duplicate.status_code == 200
    body = duplicate.json()
    assert body["ignored"] is True
    assert body["decision"] == "approve"
    assert store.get_approval("ap-1").status == "approved"


def test_stale_digest_decide_is_409(client: TestClient, store: Store) -> None:
    client.post("/v1/tasks", json=MANIFEST)
    store.insert_approval(
        "ap-1",
        "task-123",
        action_class="dependency_lock_change",
        action_digest="sha256:deadbeef",
        paths=["uv.lock"],
    )
    response = client.post(
        "/v1/tasks/task-123/approvals/ap-1/decide",
        json={"decision": "approve", "action_digest": "sha256:patched"},
    )
    assert response.status_code == 409
    assert "stale" in response.json()["detail"]
    assert store.get_approval("ap-1").status == "open"


def test_missing_digest_decide_is_422(client: TestClient, store: Store) -> None:
    client.post("/v1/tasks", json=MANIFEST)
    store.insert_approval(
        "ap-1",
        "task-123",
        action_class="dependency_lock_change",
        action_digest="sha256:deadbeef",
        paths=["uv.lock"],
    )
    response = client.post(
        "/v1/tasks/task-123/approvals/ap-1/decide",
        json={"decision": "approve", "actor": "operator"},
    )
    assert response.status_code == 422
    assert store.get_approval("ap-1").status == "open"


def test_ask_question_sets_awaiting_input(client: TestClient, store: Store) -> None:
    client.post("/v1/tasks", json=MANIFEST)
    asked = client.post(
        "/v1/tasks/task-123/questions",
        json={
            "id": "q-1",
            "stage": "plan",
            "reason": "ambiguous strategy",
            "options": ["keep lock", "retry"],
            "recommendation": "keep lock",
        },
    )
    assert asked.status_code == 201
    body = asked.json()
    assert body["lifecycle"] == "awaiting_input"
    assert body["questions"][0]["id"] == "q-1"
    assert body["questions"][0]["status"] == "open"
    persisted = store.get_task("task-123")
    assert persisted is not None
    assert persisted.lifecycle is LifecycleState.AWAITING_INPUT
    answered = client.post(
        "/v1/tasks/task-123/questions/q-1/answer",
        json={"answer": "keep lock", "actor": "operator"},
    )
    assert answered.status_code == 200
    assert answered.json()["ignored"] is False
    duplicate = client.post(
        "/v1/tasks/task-123/questions/q-1/answer",
        json={"answer": "retry", "actor": "other"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["ignored"] is True
    resumed = client.post("/v1/tasks/task-123/resume")
    assert resumed.status_code == 200
    assert resumed.json()["id"] == "task-123"
    assert resumed.json()["lifecycle"] == "queued"


def test_pause_retains_worktree_and_rows(client: TestClient, store: Store) -> None:
    client.post("/v1/tasks", json=MANIFEST)
    store.update_task(
        "task-123",
        worktree_path="/tmp/worktrees/example-service/task-123",
        branch="agent/task-123",
        set_worktree_path=True,
        set_branch=True,
    )
    store.insert_question(
        "q-keep",
        "task-123",
        stage=WorkflowStage.PLAN,
        options=["a"],
        reason="keep me",
    )
    paused = client.post("/v1/tasks/task-123/pause")
    assert paused.status_code == 200
    assert paused.json()["lifecycle"] == "paused"
    assert paused.json()["worktree_path"] == "/tmp/worktrees/example-service/task-123"
    assert store.get_question("q-keep") is not None
    assert store.get_task("task-123").worktree_path == "/tmp/worktrees/example-service/task-123"


def test_cancelled_cannot_resume(client: TestClient, store: Store) -> None:
    client.post("/v1/tasks", json=MANIFEST)
    cancelled = client.post("/v1/tasks/task-123/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["lifecycle"] == "cancelled"
    resumed = client.post("/v1/tasks/task-123/resume")
    assert resumed.status_code == 409
    assert store.get_task("task-123").lifecycle is LifecycleState.CANCELLED
    assert store.get_task("task-123").lifecycle is not LifecycleState.RUNNING
    assert client.post("/v1/tasks/task-123/pause").status_code == 409


def test_creating_a_task_does_not_start_a_worker(client: TestClient, store: Store) -> None:
    client.post("/v1/tasks", json=MANIFEST)
    record = store.get_task("task-123")
    assert record is not None
    assert record.lifecycle is LifecycleState.QUEUED
    assert store.get_lease("task-123") is None


def test_non_loopback_auth_required(store: Store) -> None:
    app = create_app(store=store, require_auth=True, auth_token="secret-token")
    with TestClient(app) as client:
        denied = client.post("/v1/tasks", json=MANIFEST)
        assert denied.status_code == 401
        wrong = client.post(
            "/v1/tasks",
            json=MANIFEST,
            headers={"Authorization": "Bearer wrong"},
        )
        assert wrong.status_code == 401
        health = client.get("/health")
        assert health.status_code == 200
        created = client.post(
            "/v1/tasks",
            json=MANIFEST,
            headers={"Authorization": "Bearer secret-token"},
        )
        assert created.status_code == 201


def test_default_bind_is_loopback() -> None:
    target = resolve_bind(policy={"api": {"default_bind": "127.0.0.1", "default_port": 8741}})
    assert target.kind == "tcp"
    assert target.host == DEFAULT_BIND
    assert target.port == DEFAULT_PORT
    assert target.is_local_trust is True
    assert target.requires_auth is False


def test_unix_socket_is_local_trust() -> None:
    target = resolve_bind(socket="/tmp/two.sock", policy={})
    assert target.kind == "unix"
    assert target.socket_path == "/tmp/two.sock"
    assert target.requires_auth is False


def test_public_bind_attempt_fails() -> None:
    with pytest.raises(ApiPublicBindError, match="public"):
        resolve_bind(bind="0.0.0.0", policy={})
    with pytest.raises(ApiPublicBindError, match="public"):
        resolve_bind(bind="::", policy={})
    with pytest.raises(ApiPublicBindError, match="public"):
        resolve_bind(bind="*", policy={})
    with pytest.raises(ApiPublicBindError, match="allow_public_bind"):
        resolve_bind(
            bind="127.0.0.1",
            policy={"api": {"allow_public_bind": True, "default_bind": "127.0.0.1"}},
        )


def test_overlay_bind_requires_auth() -> None:
    target = resolve_bind(bind="100.64.1.8", port=8741, policy={})
    assert target.requires_auth is True
    assert target.is_local_trust is False


def test_invalid_port_fails() -> None:
    with pytest.raises(BindPolicyError):
        resolve_bind(bind="127.0.0.1", env={"TWO_API_PORT": "not-a-port"}, policy={})


def test_serve_refuses_public_bind(capsys: pytest.CaptureFixture[str]) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("uvicorn must not start on a public bind")

    code = serve(bind="0.0.0.0", policy={}, run=boom)
    assert code == 1
    captured = capsys.readouterr()
    assert "public" in captured.err


def test_serve_requires_token_for_overlay(capsys: pytest.CaptureFixture[str]) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("uvicorn must not start without a token")

    code = serve(bind="10.0.0.8", env={}, policy={}, run=boom)
    assert code == 1
    assert "TWO_API_TOKEN" in capsys.readouterr().err


def test_serve_loopback_does_not_bind_a_port() -> None:
    called: dict[str, object] = {}

    def fake_run(_app: object, **kwargs: object) -> None:
        called.update(kwargs)

    code = serve(bind="127.0.0.1", port=8741, env={}, policy={}, run=fake_run)
    assert code == 0
    assert called["host"] == "127.0.0.1"
    assert called["port"] == 8741


def test_access_yaml_defaults() -> None:
    target = resolve_bind(policy_path=REPO_ROOT / "config/access/remote.yaml")
    assert target.host == "127.0.0.1"
    assert target.port == 8741
    assert target.requires_auth is False


def test_api_package_cannot_reach_the_model() -> None:
    for path in sorted(API_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for name in imported:
            assert not name.startswith("two.workspace")
            assert not name.startswith("two.channels")
            assert not name.startswith("two.providers")
            assert not name.startswith("two.runtime")
            assert "slack" not in name.lower()
            assert "ollama" not in name.lower()
            assert name != "openai"
            assert name != "httpx"
            assert name != "subprocess"
        assert "MAC_QWEN" not in source
        assert "/v1/chat/completions" not in source
        assert "subprocess" not in source
    app_source = inspect.getsource(create_app)
    assert "subprocess" not in app_source


def test_cli_api_help_does_not_start_server() -> None:
    from two.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(["api", "--help"])
    assert exc_info.value.code == 0


def test_manifest_round_trip_type() -> None:
    manifest = TaskManifest.model_validate(MANIFEST)
    assert manifest.id == "task-123"
