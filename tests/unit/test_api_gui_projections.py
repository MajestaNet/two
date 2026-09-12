# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline FastAPI tests for B14 slice 2 read-only GUI projections."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from two.api import create_app
from two.projection import HealthObservation
from two.store import Store, open_store
from two.types import EventType, LifecycleState, Scope

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
def client(store: Store, repos_dir: Path, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(store=store, repositories_dir=repos_dir, data_dir=tmp_path / "data")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def remote(store: Store, repos_dir: Path, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        store=store,
        require_auth=True,
        auth_token=TOKEN,
        repositories_dir=repos_dir,
        data_dir=tmp_path / "data",
    )
    with TestClient(app) as test_client:
        yield test_client


def _create(client: TestClient, headers: dict[str, str] | None = None) -> dict[str, object]:
    response = client.post("/v1/tasks", json=MANIFEST, headers=headers)
    assert response.status_code == 201
    return response.json()


def _parse_sse(body: str) -> list[tuple[str, str, dict[str, object]]]:
    events: list[tuple[str, str, dict[str, object]]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        event_name = ""
        event_id = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("id:"):
                event_id = line[3:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        payload: dict[str, object] = json.loads(data) if data else {}
        events.append((event_name, event_id, payload))
    return events


def test_conversation_pages_client_safe_kinds(client: TestClient, store: Store) -> None:
    created = _create(client)
    assert created["graph"] is None
    client.post("/v1/tasks/task-123/messages", json={"text": "please continue"})
    store.append_event(
        "task-123",
        EventType.WORKFLOW_STAGE.value,
        {"stage": "implement"},
    )
    store.append_event("task-123", EventType.TASK_GRAPH.value, {"node_id": "n1"})
    store.append_event(
        "task-123",
        EventType.QUESTION_ASKED.value,
        {"id": "q1", "reason": "which lock?", "stage": "implement"},
    )
    store.append_event(
        "task-123",
        EventType.APPROVAL_REQUESTED.value,
        {"id": "ap-1", "action_class": "lockfile"},
    )
    store.append_event(
        "task-123",
        EventType.TASK_VALIDATION.value,
        {"passed": True, "last_gate": "test", "summary": "tests passed"},
    )
    store.append_event(
        "task-123",
        EventType.WORKFLOW_COMPLETE.value,
        {"notes": "done"},
    )
    store.append_event(
        "task-123",
        EventType.ACP_CHILD_STARTED.value,
        {"command": "dsh --unsafe", "stdout": "raw trajectory", "env": {"TOKEN": "x"}},
    )
    page = client.get("/v1/tasks/task-123/conversation")
    assert page.status_code == 200
    body = page.json()
    kinds = [item["kind"] for item in body["items"]]
    assert "user_message" in kinds
    assert "stage_change" in kinds
    assert "graph_change" in kinds
    assert "question" in kinds
    assert "approval" in kinds
    assert "validation_summary" in kinds
    assert "completion_report" in kinds
    text = json.dumps(body)
    assert "raw trajectory" not in text
    assert "dsh --unsafe" not in text
    assert "TOKEN" not in text
    assert client.get("/v1/tasks/task-123").json()["graph"] is None
    first = body["items"][0]["cursor"]
    paged = client.get("/v1/tasks/task-123/conversation", params={"after": first, "limit": 2})
    assert paged.status_code == 200
    assert all(item["seq"] > int(first) for item in paged.json()["items"])
    invalid = client.get("/v1/tasks/task-123/conversation", params={"after": "not-a-cursor!"})
    assert invalid.status_code == 400
    missing = client.get("/v1/tasks/missing/conversation")
    assert missing.status_code == 404


def test_conversation_unauthenticated_remote_is_401(remote: TestClient) -> None:
    denied = remote.get("/v1/tasks/task-123/conversation")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "unauthorized"


def test_conversation_missing_scope_is_403(store: Store) -> None:
    limited = create_app(
        store=store,
        require_auth=True,
        auth_token=TOKEN,
        operator_scopes={Scope.SYSTEM_READ},
    )
    with TestClient(limited) as client:
        denied = client.get("/v1/tasks/missing/conversation", headers=AUTH)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "forbidden"


def test_sse_reconnect_reset_and_slow_consumer(store: Store, tmp_path: Path) -> None:
    app = create_app(
        store=store,
        data_dir=tmp_path / "data",
        stream_backlog_limit=1,
        stream_min_seq=3,
    )
    with TestClient(app) as client:
        _create(client)
        client.post("/v1/tasks/task-123/messages", json={"text": "one"})
        client.post("/v1/tasks/task-123/messages", json={"text": "two"})
        client.post("/v1/tasks/task-123/messages", json={"text": "three"})
        reset = client.get("/v1/tasks/task-123/stream", headers={"Last-Event-ID": "1"})
        assert reset.status_code == 200
        assert reset.headers["content-type"].startswith("text/event-stream")
        reset_events = _parse_sse(reset.text)
        assert reset_events[0][0] == "reset"
        assert reset_events[0][2]["reason"] == "retention"
        disconnect = client.get("/v1/tasks/task-123/stream")
        disconnect_events = _parse_sse(disconnect.text)
        assert disconnect_events[0][0] == "disconnect"
        assert disconnect_events[0][2]["reason"] == "slow_consumer"

    caught_up = create_app(store=store, data_dir=tmp_path / "data", stream_backlog_limit=50)
    with TestClient(caught_up) as client:
        first = client.get("/v1/tasks/task-123/stream")
        events = _parse_sse(first.text)
        assert events
        assert all(name != "reset" for name, _eid, _data in events)
        last_id = events[0][1]
        replay = client.get("/v1/tasks/task-123/stream", headers={"Last-Event-ID": last_id})
        replayed = _parse_sse(replay.text)
        assert all(item[1] != last_id for item in replayed)
        system = client.get("/v1/stream")
        assert system.status_code == 200
        assert "task-123:" in system.text
        stale_global = client.get("/v1/stream", headers={"Last-Event-ID": "nope"})
        assert _parse_sse(stale_global.text)[0][0] == "reset"


def test_sse_unauthenticated_remote_is_401(remote: TestClient) -> None:
    assert remote.get("/v1/stream").status_code == 401
    assert remote.get("/v1/tasks/task-123/stream").status_code == 401


def test_aggregate_health_does_not_claim_stale_or_missing(store: Store, tmp_path: Path) -> None:
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    stale_at = now - timedelta(seconds=30)
    app = create_app(
        store=store,
        data_dir=tmp_path / "data",
        clock=lambda: now,
        health_stale_after_ms=5_000,
        health_observations={
            "inference": HealthObservation(
                status="healthy", observed_at=stale_at, detail="alias matched"
            ),
            "worker": HealthObservation(status="degraded", observed_at=now, detail="busy"),
        },
    )
    with TestClient(app) as client:
        shallow = client.get("/health")
        assert shallow.json()["status"] == "ok"
        assert "inference" not in shallow.json()
        body = client.get("/v1/system/health").json()
        by_name = {item["name"]: item for item in body["components"]}
        assert by_name["api"]["status"] == "healthy"
        assert by_name["store"]["status"] == "healthy"
        assert by_name["inference"]["status"] == "unknown"
        assert by_name["inference"]["stale"] is True
        assert by_name["inference"]["status"] != "healthy"
        assert by_name["scheduler"]["status"] == "unknown"
        assert by_name["worker"]["status"] == "degraded"
        assert body["status"] == "degraded"
        assert body["stale"] is True


def test_system_health_and_queue_require_auth_and_scope(store: Store) -> None:
    remote = create_app(store=store, require_auth=True, auth_token=TOKEN)
    with TestClient(remote) as client:
        assert client.get("/v1/system/health").status_code == 401
        assert client.get("/v1/system/queue").status_code == 401
        listed = client.get("/v1/system/queue", headers=AUTH)
        assert listed.status_code == 200
    limited = create_app(
        store=store,
        require_auth=True,
        auth_token=TOKEN,
        operator_scopes={Scope.TASKS_READ},
    )
    with TestClient(limited) as client:
        denied = client.get("/v1/system/health", headers=AUTH)
        assert denied.status_code == 403


def test_queue_redacts_objective_and_reports_lease(client: TestClient, store: Store) -> None:
    _create(client)
    store.update_task("task-123", lifecycle=LifecycleState.RUNNING)
    store.obtain_lease("task-123", "worker-1", ttl_seconds=30)
    body = client.get("/v1/system/queue").json()
    assert body["active_task_id"] == "task-123"
    assert "objective" not in json.dumps(body)
    assert "/tmp" not in json.dumps(body)
    assert body["items"][0]["task_id"] == "task-123"
    assert body["items"][0]["lease_fresh"] is True


def test_repository_read_strips_commands_and_host_paths(client: TestClient) -> None:
    listed = client.get("/v1/repositories")
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["repositories"]}
    assert "example-service" in ids
    body = client.get("/v1/repositories/example-service").json()
    dumped = json.dumps(body)
    assert "pytest" not in dumped
    assert "ruff check" not in dumped
    assert "/Users/operator" not in dumped
    assert "never-show" not in dumped
    assert "src/**" in body["allowed_path_patterns"]
    assert "test" in body["gate_names"]
    assert body["network"]["allow_external_mutations"] is False
    missing = client.get("/v1/repositories/missing")
    assert missing.status_code == 404
    projects = client.get("/v1/projects")
    assert projects.status_code == 200
    assert projects.json()["projects"] == []
    assert client.get("/v1/projects/any").status_code == 404


def test_config_read_required_for_repositories(store: Store, repos_dir: Path) -> None:
    limited = create_app(
        store=store,
        require_auth=True,
        auth_token=TOKEN,
        repositories_dir=repos_dir,
        operator_scopes={Scope.TASKS_READ, Scope.SYSTEM_READ},
    )
    with TestClient(limited) as client:
        denied = client.get("/v1/repositories", headers=AUTH)
        assert denied.status_code == 403


def test_diff_and_artifacts_disclosure(client: TestClient, store: Store, tmp_path: Path) -> None:
    _create(client)
    store.append_event(
        "task-123",
        EventType.TASK_DIFF.value,
        {
            "files_changed": 2,
            "lines_added": 4,
            "lines_removed": 1,
            "paths": ["src/two/api.py", "/tmp/worktrees/task-123/secret.py"],
            "patch": "@@ -1 +1 @@\n+safe hunk",
        },
    )
    stats = client.get("/v1/tasks/task-123/diff").json()
    assert stats["summary"]["files_changed"] == 2
    assert stats["summary"]["paths"] == ["src/two/api.py"]
    assert "/tmp" not in json.dumps(stats)
    assert stats["patch"] is not None
    assert stats["source_included"] is True
    host = client.get("/v1/tasks/task-123/diff", params={"path": "/etc/passwd"})
    assert host.status_code == 400
    data_dir = tmp_path / "data"
    validation = data_dir / "tasks" / "task-123" / "validation"
    validation.mkdir(parents=True)
    (validation / "test.log").write_text("ok\nSECRET=should-need-source-read\n", encoding="utf-8")
    listed = client.get("/v1/tasks/task-123/artifacts")
    assert listed.status_code == 200
    assert listed.json()["artifacts"][0]["id"] == "test.log"
    body = client.get("/v1/tasks/task-123/artifacts/test.log").json()
    assert body["source_included"] is True
    assert "SECRET=should-need-source-read" in body["content"]
    traversal = client.get("/v1/tasks/task-123/artifacts/%2e%2e")
    assert traversal.status_code == 400
    path_query = client.get("/v1/tasks/task-123/artifacts", params={"path": "/tmp/x"})
    assert path_query.status_code == 400


def test_diff_without_source_read_omits_paths(store: Store, tmp_path: Path) -> None:
    app = create_app(
        store=store,
        require_auth=True,
        auth_token=TOKEN,
        data_dir=tmp_path / "data",
        operator_scopes={Scope.TASKS_READ, Scope.TASKS_CONTROL, Scope.SYSTEM_READ},
    )
    with TestClient(app) as client:
        _create(client, AUTH)
        store.append_event(
            "task-123",
            "diff",
            {"files_changed": 1, "paths": ["src/a.py"], "patch": "@@ hunk"},
        )
        body = client.get("/v1/tasks/task-123/diff", headers=AUTH).json()
        assert body["summary"]["paths"] == []
        assert body["patch"] is None
        data_dir = tmp_path / "data"
        validation = data_dir / "tasks" / "task-123" / "validation"
        validation.mkdir(parents=True)
        (validation / "test.log").write_text("gate log\n", encoding="utf-8")
        artifact = client.get("/v1/tasks/task-123/artifacts/test.log", headers=AUTH).json()
        assert artifact["content"] is None
        assert artifact["source_included"] is False


def test_network_events_are_policy_filtered(remote: TestClient, store: Store) -> None:
    _create(remote, AUTH)
    store.append_event(
        "task-123",
        EventType.WORKFLOW_WORKER.value,
        {
            "summary": "running tests",
            "stdout": "very verbose log",
            "env": {"OPENAI_API_KEY": "sk-secret"},
            "worktree_path": "/tmp/worktrees/example/task-123",
        },
    )
    events = remote.get("/v1/tasks/task-123/events", headers=AUTH).json()["events"]
    worker = [item for item in events if item["type"] == EventType.WORKFLOW_WORKER.value][0]
    assert "stdout" not in worker["payload"]
    assert "env" not in worker["payload"]
    assert "worktree_path" not in worker["payload"]
    assert "sk-secret" not in json.dumps(worker)


def test_local_events_keep_cli_payloads(client: TestClient, store: Store) -> None:
    _create(client)
    store.append_event(
        "task-123",
        EventType.WORKFLOW_WORKER.value,
        {"summary": "running tests", "stdout": "cli may still see this"},
    )
    events = client.get("/v1/tasks/task-123/events").json()["events"]
    worker = [item for item in events if item["type"] == EventType.WORKFLOW_WORKER.value][0]
    assert worker["payload"]["stdout"] == "cli may still see this"


def test_slice1_etag_and_idempotency_still_work(client: TestClient) -> None:
    created = client.post("/v1/tasks", json=MANIFEST)
    etag = created.headers["etag"]
    stale = client.post("/v1/tasks/task-123/pause", headers={"If-Match": '"999999"'})
    assert stale.status_code == 412
    paused = client.post("/v1/tasks/task-123/pause", headers={"If-Match": etag})
    assert paused.status_code == 200
    replay = client.post("/v1/tasks/task-123/resume", headers={"Idempotency-Key": "r1"})
    again = client.post("/v1/tasks/task-123/resume", headers={"Idempotency-Key": "r1"})
    assert replay.status_code == 200
    assert again.status_code == 200
    assert again.json()["revision"] == replay.json()["revision"]
