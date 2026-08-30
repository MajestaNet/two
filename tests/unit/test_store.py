# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline unit tests for the SQLite WAL store (B06). No network."""

from __future__ import annotations

import ast
import inspect
import json
import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from two.manifest import TaskManifest
from two.store import (
    DEFAULT_DB_FILENAME,
    SCHEMA_VERSION,
    ActionStatus,
    DuplicateSourceEventError,
    DuplicateTaskError,
    Store,
    StoreError,
    TaskNotFoundError,
    open_store,
    resolve_db_path,
)
from two.store.engine import BUSY_TIMEOUT_MS, connect
from two.types import ExecutionProfile, LifecycleState, Mode, WorkflowStage
from two.validation.artifacts import ENV_DATA_DIR

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


def _manifest(**overrides: object) -> TaskManifest:
    payload: dict[str, object] = {
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
    payload.update(overrides)
    return TaskManifest.model_validate(payload)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "two.sqlite"


@pytest.fixture
def store(db_path: Path) -> Iterator[Store]:
    opened = open_store(db_path)
    try:
        yield opened
    finally:
        opened.close()


def test_open_store_creates_directories_and_wal(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "state" / "two.sqlite"
    with open_store(path) as opened:
        assert path.is_file()
        assert opened.schema_version() == SCHEMA_VERSION
        assert opened.path == path
    with sqlite3.connect(path) as raw:
        mode = raw.execute("PRAGMA journal_mode").fetchone()
        assert mode is not None
        assert str(mode[0]).lower() == "wal"
    with sqlite3.connect(path) as raw:
        mode = raw.execute("PRAGMA journal_mode").fetchone()
        assert mode is not None
        assert str(mode[0]).lower() == "wal"


def test_open_store_none_uses_two_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "var-two"
    monkeypatch.setenv(ENV_DATA_DIR, str(data_dir))
    expected = data_dir / DEFAULT_DB_FILENAME
    assert resolve_db_path(None) == expected
    with open_store(None) as opened:
        assert opened.path == expected
        assert expected.is_file()


def test_engine_connect_sets_pragmas(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(db_path)
    try:
        mode = connection.execute("PRAGMA journal_mode").fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
        busy = connection.execute("PRAGMA busy_timeout").fetchone()
        assert mode is not None and str(mode[0]).lower() == "wal"
        assert foreign_keys is not None and foreign_keys[0] == 1
        assert busy is not None and busy[0] == BUSY_TIMEOUT_MS
    finally:
        connection.close()


def test_insert_task_commits_before_return(db_path: Path) -> None:
    with open_store(db_path) as opened:
        record = opened.insert_task(_manifest(), now=T0)
        assert record.id == "task-123"
        assert record.lifecycle is LifecycleState.QUEUED
        assert record.stage is WorkflowStage.INTAKE
        assert record.mode is Mode.UNATTENDED
        assert record.execution_profile is ExecutionProfile.OVERNIGHT
        assert record.time_budget_minutes == 480
        assert record.cloud_allowed is False
        assert record.retry_count == 0
        assert record.next_attempt_at is None
        assert record.active_elapsed_ms == 0
        assert record.active_started_at is None
    with open_store(db_path) as reopened:
        loaded = reopened.get_task("task-123")
        assert loaded is not None
        assert loaded.objective == "Add optimistic locking to order updates"
        assert loaded.created_at == T0


def test_duplicate_task_id_rejected(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    with pytest.raises(DuplicateTaskError):
        store.insert_task(_manifest(), now=T0)


def test_crash_safety_append_event_reopen(db_path: Path) -> None:
    with open_store(db_path) as opened:
        opened.insert_task(_manifest(), now=T0)
        event_id = opened.append_event(
            "task-123",
            "stage_transition",
            {"from": "intake", "to": "isolate"},
            now=T0,
        )
        assert event_id > 0
    with open_store(db_path) as reopened:
        events = reopened.list_events("task-123")
        assert len(events) == 1
        assert events[0].id == event_id
        assert events[0].seq == 1
        assert events[0].type == "stage_transition"
        assert events[0].payload == {"from": "intake", "to": "isolate"}
        loaded = reopened.get_event(event_id)
        assert loaded is not None
        assert loaded.seq == 1


def test_append_event_monotonic_seq(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    first = store.append_event("task-123", "created", {"ok": True}, now=T0)
    second = store.append_event("task-123", "queued", {"ok": True}, now=T0)
    third = store.append_event("task-123", "started", {"ok": True}, now=T0)
    events = store.list_events("task-123")
    assert [event.id for event in events] == [first, second, third]
    assert [event.seq for event in events] == [1, 2, 3]


def test_append_event_unknown_task_raises(store: Store) -> None:
    with pytest.raises(TaskNotFoundError):
        store.append_event("missing", "created", {})


def test_events_cannot_be_updated_through_public_api(store: Store) -> None:
    public = {name for name in dir(Store) if not name.startswith("_")}
    assert "update_event" not in public
    assert "delete_event" not in public
    assert "remove_event" not in public
    source = inspect.getsource(Store)
    assert re.search(r"UPDATE\s+events\b", source, flags=re.IGNORECASE) is None
    assert re.search(r"DELETE\s+FROM\s+events\b", source, flags=re.IGNORECASE) is None
    store.insert_task(_manifest(), now=T0)
    event_id = store.append_event("task-123", "created", {"n": 1}, now=T0)
    before = store.get_event(event_id)
    assert before is not None
    store.append_event("task-123", "other", {"n": 2}, now=T0)
    after = store.get_event(event_id)
    assert after is not None
    assert after.seq == before.seq
    assert after.type == before.type
    assert after.payload == before.payload


def test_enums_stored_as_string_values(db_path: Path) -> None:
    with open_store(db_path) as opened:
        opened.insert_task(
            _manifest(),
            lifecycle=LifecycleState.QUEUED,
            stage=WorkflowStage.INTAKE,
            now=T0,
        )
    with sqlite3.connect(db_path) as raw:
        row = raw.execute(
            "SELECT lifecycle, stage, mode, execution_profile FROM tasks WHERE id = ?",
            ("task-123",),
        ).fetchone()
    assert row is not None
    assert row[0] == "queued"
    assert row[0] == LifecycleState.QUEUED.value
    assert row[1] == WorkflowStage.INTAKE.value
    assert row[2] == Mode.UNATTENDED.value
    assert row[3] == ExecutionProfile.OVERNIGHT.value


def test_lease_expire_and_reclaim(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    lease = store.obtain_lease("task-123", "worker-a", ttl_seconds=60, now=T0)
    assert lease is not None
    assert lease.worker_id == "worker-a"
    assert lease.expires_at == T0 + timedelta(seconds=60)
    at_expiry = T0 + timedelta(seconds=60)
    assert store.reclaim_expired(now=at_expiry) == []
    assert store.get_lease("task-123") is not None
    after = T0 + timedelta(seconds=61)
    assert store.reclaim_expired(now=after) == ["task-123"]
    assert store.get_lease("task-123") is None


def test_unexpired_lease_not_reclaimed(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    store.obtain_lease("task-123", "worker-a", ttl_seconds=60, now=T0)
    before = T0 + timedelta(seconds=30)
    assert store.reclaim_expired(now=before) == []
    remaining = store.get_lease("task-123")
    assert remaining is not None
    assert remaining.worker_id == "worker-a"


def test_release_lease_owned_only(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    assert store.release_lease("task-123", "worker-a") is False
    store.obtain_lease("task-123", "worker-a", ttl_seconds=60, now=T0)
    assert store.release_lease("task-123", "worker-b") is False
    assert store.get_lease("task-123") is not None
    assert store.release_lease("task-123", "worker-a") is True
    assert store.get_lease("task-123") is None


def test_schema_v2_migrates_next_attempt_columns(tmp_path: Path) -> None:
    from two.store.engine import connect
    from two.store.schema import MIGRATIONS, current_schema_version

    path = tmp_path / "legacy.sqlite"
    connection = connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        version, statements = MIGRATIONS[0]
        assert version == 1
        for statement in statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (1, "2026-08-30T12:00:00.000000Z"),
        )
        payload = json.dumps(_manifest().model_dump(mode="json"), sort_keys=True)
        connection.execute(
            """
            INSERT INTO tasks (
                id, repository, base_ref, objective, manifest_json,
                lifecycle, stage, mode, execution_profile,
                worktree_path, branch, base_commit,
                time_budget_minutes, max_model_turns, max_repair_cycles,
                no_progress_limit, cloud_allowed, created_at, updated_at
            ) VALUES (
                'task-123', 'example-service', 'origin/main', 'obj',
                ?, 'queued', 'intake', 'unattended', 'overnight',
                '/tmp/wt', 'agent/task-123', 'abc', 480, 30, 6, 2, 0, ?, ?
            )
            """,
            (payload, "2026-08-30T12:00:00.000000Z", "2026-08-30T12:00:00.000000Z"),
        )
        connection.commit()
        assert current_schema_version(connection) == 1
    finally:
        connection.close()

    with open_store(path) as opened:
        assert opened.schema_version() == SCHEMA_VERSION
        assert SCHEMA_VERSION == 2
        loaded = opened.get_task("task-123")
        assert loaded is not None
        assert loaded.worktree_path == "/tmp/wt"
        assert loaded.next_attempt_at is None
        assert loaded.retry_count == 0
        assert loaded.active_elapsed_ms == 0
        updated = opened.update_task(
            "task-123",
            next_attempt_at=T0 + timedelta(seconds=4),
            set_next_attempt_at=True,
            retry_count=1,
            now=T0,
        )
        assert updated.retry_count == 1
        assert updated.next_attempt_at == T0 + timedelta(seconds=4)


def test_obtain_lease_refuses_unexpired(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    first = store.obtain_lease("task-123", "worker-a", ttl_seconds=60, now=T0)
    assert first is not None
    assert store.obtain_lease("task-123", "worker-b", ttl_seconds=60, now=T0) is None
    assert store.obtain_lease("task-123", "worker-a", ttl_seconds=60, now=T0) is None
    stolen = store.obtain_lease(
        "task-123",
        "worker-b",
        ttl_seconds=60,
        now=T0 + timedelta(seconds=61),
    )
    assert stolen is not None
    assert stolen.worker_id == "worker-b"


def test_heartbeat_extends_unexpired_lease(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    store.obtain_lease("task-123", "worker-a", ttl_seconds=60, now=T0)
    later = T0 + timedelta(seconds=10)
    renewed = store.heartbeat_lease("task-123", "worker-a", ttl_seconds=60, now=later)
    assert renewed is not None
    assert renewed.heartbeat_at == later
    assert renewed.expires_at == later + timedelta(seconds=60)
    assert store.heartbeat_lease("task-123", "worker-b", ttl_seconds=60, now=later) is None
    expired_at = later + timedelta(seconds=61)
    assert store.heartbeat_lease("task-123", "worker-a", ttl_seconds=60, now=expired_at) is None


def test_duplicate_source_event_id_rejected(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    binding = store.bind_channel("task-123", "slack", "C123.thread", "Ev111")
    assert binding.source_event_id == "Ev111"
    with pytest.raises(DuplicateSourceEventError):
        store.bind_channel("task-123", "slack", "C123.other", "Ev111")
    store.insert_task(_manifest(id="task-456"), now=T0)
    with pytest.raises(DuplicateSourceEventError):
        store.bind_channel("task-456", "slack", "C999.thread", "Ev111")
    assert len(store.list_bindings("task-123")) == 1


def test_action_ledger_recorded_executed_reconcile(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    recorded = store.record_action(
        "act-1",
        "task-123",
        {"tool": "apply_patch", "path": "src/x.py"},
        now=T0,
    )
    assert recorded.status is ActionStatus.RECORDED
    assert recorded.result is None
    assert recorded.diff_fingerprint is None
    with sqlite3.connect(store.path) as raw:
        status = raw.execute(
            "SELECT status FROM actions WHERE action_id = ?",
            ("act-1",),
        ).fetchone()
    assert status is not None
    assert status[0] == "recorded"
    assert status[0] == ActionStatus.RECORDED.value
    executed = store.complete_action(
        "act-1",
        status=ActionStatus.EXECUTED,
        result={"exit": 0},
        diff_fingerprint="abc123",
        now=T0 + timedelta(seconds=5),
    )
    assert executed.status is ActionStatus.EXECUTED
    assert executed.result == {"exit": 0}
    assert executed.diff_fingerprint == "abc123"
    assert executed.completed_at == T0 + timedelta(seconds=5)
    store.record_action("act-2", "task-123", {"tool": "test"}, now=T0)
    reconciled = store.complete_action(
        "act-2",
        status=ActionStatus.RECONCILE,
        result={"reason": "missing result event"},
        now=T0 + timedelta(seconds=8),
    )
    assert reconciled.status is ActionStatus.RECONCILE
    assert [row.action_id for row in store.list_actions("task-123")] == ["act-1", "act-2"]


def test_questions_and_approvals_persist(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    question = store.insert_question(
        "q-1",
        "task-123",
        stage=WorkflowStage.PLAN,
        options=["keep lock", "retry"],
        recommendation="keep lock",
        actor="controller",
        reason="ambiguous strategy",
        now=T0,
    )
    assert question.stage == WorkflowStage.PLAN.value
    assert question.status == "open"
    assert question.options == ["keep lock", "retry"]
    approval = store.insert_approval(
        "ap-1",
        "task-123",
        action_class="dependency_lock_change",
        action_digest="sha256:deadbeef",
        paths=["uv.lock"],
        now=T0,
    )
    assert approval.action_digest == "sha256:deadbeef"
    assert approval.paths == ["uv.lock"]
    assert store.get_question("q-1") is not None
    assert store.get_approval("ap-1") is not None
    assert [row.id for row in store.list_questions("task-123")] == ["q-1"]
    assert [row.id for row in store.list_approvals("task-123")] == ["ap-1"]


def test_update_and_list_tasks(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    store.insert_task(_manifest(id="task-456"), now=T0 + timedelta(seconds=1))
    updated = store.update_task(
        "task-123",
        lifecycle=LifecycleState.RUNNING,
        stage=WorkflowStage.IMPLEMENT,
        worktree_path="/tmp/worktrees/example-service/task-123",
        branch="agent/task-123",
        base_commit="abc",
        set_worktree_path=True,
        set_branch=True,
        set_base_commit=True,
        now=T0 + timedelta(seconds=2),
    )
    assert updated.lifecycle is LifecycleState.RUNNING
    assert updated.worktree_path is not None
    queued = store.list_tasks(lifecycle=LifecycleState.QUEUED)
    assert [row.id for row in queued] == ["task-456"]


def test_cli_does_not_import_store() -> None:
    source = Path("src/two/cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert all(not name.startswith("two.store") for name in imported)
    assert "two.store" not in source
    assert "open_store" not in source


def test_gitignore_excludes_databases() -> None:
    text = Path(".gitignore").read_text(encoding="utf-8")
    assert "*.db" in text
    assert "*.sqlite" in text
    assert "var/" in text


def test_complete_action_rejects_recorded(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    store.record_action("act-1", "task-123", {"tool": "x"}, now=T0)
    with pytest.raises(StoreError):
        store.complete_action("act-1", status=ActionStatus.RECORDED)
