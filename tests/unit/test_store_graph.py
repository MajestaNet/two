# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for schema v5 work-graph persistence (B19)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from two.graph import (
    GraphProposal,
    ProposedNode,
    apply_proposal,
    compile_linear_graph,
    compile_skeleton_graph,
)
from two.graph.invariants import edge
from two.graph.models import WorkEdge, WorkGraph, WorkNode
from two.manifest import TaskManifest
from two.store import SCHEMA_VERSION, GraphCommitError, Store, open_store
from two.store.engine import connect
from two.store.schema import MIGRATIONS, current_schema_version
from two.types import (
    EdgeKind,
    ExecutionProfile,
    LifecycleState,
    NodeKind,
    NodeStatus,
    WorkflowStage,
)

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


def _manifest(**overrides: object) -> TaskManifest:
    payload: dict[str, object] = {
        "id": "task-123",
        "repository": "example-service",
        "base_ref": "origin/main",
        "objective": "Add locking",
        "acceptance_criteria": ["no silent overwrite"],
        "mode": "unattended",
        "execution_profile": "overnight",
        "cloud_allowed": False,
    }
    payload.update(overrides)
    return TaskManifest.model_validate(payload)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = open_store(tmp_path / "two.sqlite")
    try:
        yield opened
    finally:
        opened.close()


def _apply_through(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    for item, statements in MIGRATIONS:
        if item > version:
            break
        for statement in statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (item, "2026-08-30T12:00:00.000000Z"),
        )
    connection.commit()


def test_round_trip_linear_graph(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    graph = compile_linear_graph(
        "task-123",
        profile=ExecutionProfile.OVERNIGHT,
        objective="Add locking",
        acceptance_criteria=["no silent overwrite"],
    )
    committed = store.commit_graph(graph, now=T0)
    loaded = store.load_graph("task-123")
    assert loaded is not None
    assert loaded.task_id == committed.task_id
    assert [node.id for node in loaded.nodes] == [node.id for node in graph.nodes]
    assert [item.id for item in loaded.edges] == [item.id for item in graph.edges]
    assert loaded.cursor_node_id == graph.cursor_node_id
    inspect = loaded.node("task-123:inspect")
    assert inspect.kind is NodeKind.INSPECT
    assert inspect.status is NodeStatus.READY
    types = [event.type for event in store.list_events("task-123")]
    assert "task.graph" in types
    assert "graph.node" in types
    assert "graph.edge" in types


def test_round_trip_two_node_proposal(store: Store) -> None:
    store.insert_task(_manifest(id="task-9"), now=T0)
    base = compile_skeleton_graph("task-9", profile=ExecutionProfile.OVERNIGHT)
    inspect = base.node("task-9:inspect")
    plan = base.node("task-9:plan")
    progressed = base.replace_node(inspect.model_copy(update={"status": NodeStatus.DONE}))
    progressed = progressed.replace_node(plan.model_copy(update={"status": NodeStatus.DONE}))
    proposal = GraphProposal(
        nodes=[
            ProposedNode(
                id="task-9:implement:auth",
                kind=NodeKind.IMPLEMENT,
                title="Auth cookie hardening",
                files_named=["src/auth.py"],
                tests_named=["tests/test_auth.py"],
            ),
            ProposedNode(
                id="task-9:implement:session",
                kind=NodeKind.IMPLEMENT,
                title="Session store",
                depends_on=["task-9:implement:auth"],
                files_named=["src/session.py"],
                tests_named=["tests/test_session.py"],
            ),
        ]
    )
    expanded = apply_proposal(progressed, proposal, profile=ExecutionProfile.OVERNIGHT)
    loaded = store.commit_graph(expanded, now=T0)
    assert loaded.node("task-9:implement:auth").kind is NodeKind.IMPLEMENT
    assert loaded.node("task-9:implement:session").kind is NodeKind.IMPLEMENT
    deps = [(item.from_id, item.to_id) for item in loaded.edges if item.kind is EdgeKind.DEPENDS_ON]
    assert ("task-9:implement:auth", "task-9:implement:session") in deps
    again = store.load_graph("task-9")
    assert again is not None
    assert {node.id for node in again.nodes} == {node.id for node in expanded.nodes}


def test_depends_on_cycle_never_persists(store: Store) -> None:
    store.insert_task(_manifest(id="task-cycle"), now=T0)
    a = WorkNode(
        id="a",
        task_id="task-cycle",
        kind=NodeKind.IMPLEMENT,
        title="A",
        allow_writes=True,
        status=NodeStatus.READY,
    )
    b = WorkNode(
        id="b",
        task_id="task-cycle",
        kind=NodeKind.IMPLEMENT,
        title="B",
        allow_writes=True,
        status=NodeStatus.PENDING,
    )
    cyclic = WorkGraph(
        task_id="task-cycle",
        nodes=[a, b],
        edges=[
            edge("task-cycle", EdgeKind.DEPENDS_ON, "a", "b"),
            WorkEdge(
                id="depends_on:b->a",
                task_id="task-cycle",
                kind=EdgeKind.DEPENDS_ON,
                from_id="b",
                to_id="a",
            ),
        ],
        cursor_node_id="a",
    )
    with pytest.raises(GraphCommitError, match="cycle"):
        store.commit_graph(cyclic, now=T0)
    assert store.load_graph("task-cycle") is None


def test_v3_and_v4_databases_migrate_to_v5(tmp_path: Path) -> None:
    v3_path = tmp_path / "v3.sqlite"
    connection = connect(v3_path)
    try:
        _apply_through(connection, 3)
        payload = json.dumps(_manifest().model_dump(mode="json"), sort_keys=True)
        connection.execute(
            """
            INSERT INTO tasks (
                id, repository, base_ref, objective, manifest_json,
                lifecycle, stage, mode, execution_profile,
                worktree_path, branch, base_commit,
                time_budget_minutes, max_model_turns, max_repair_cycles,
                no_progress_limit, cloud_allowed, created_at, updated_at,
                dsh_session_id
            ) VALUES (
                'task-v3', 'example-service', 'origin/main', 'obj',
                ?, 'queued', 'intake', 'unattended', 'overnight',
                '/tmp/wt', 'agent/task-v3', 'abc', 480, 30, 6, 2, 0, ?, ?, 'sess-old'
            )
            """,
            (payload, "2026-08-30T12:00:00.000000Z", "2026-08-30T12:00:00.000000Z"),
        )
        connection.commit()
        assert current_schema_version(connection) == 3
    finally:
        connection.close()

    with open_store(v3_path) as opened:
        assert opened.schema_version() == SCHEMA_VERSION
        assert SCHEMA_VERSION == 5
        loaded = opened.get_task("task-v3")
        assert loaded is not None
        assert loaded.dsh_session_id == "sess-old"
        assert loaded.revision == 1
        assert opened.load_graph("task-v3") is None
        assert opened.get_idempotency("local", "missing") is None

    v4_path = tmp_path / "v4.sqlite"
    connection = connect(v4_path)
    try:
        _apply_through(connection, 4)
        payload = json.dumps(_manifest(id="task-v4").model_dump(mode="json"), sort_keys=True)
        connection.execute(
            """
            INSERT INTO tasks (
                id, repository, base_ref, objective, manifest_json,
                lifecycle, stage, mode, execution_profile,
                worktree_path, branch, base_commit,
                time_budget_minutes, max_model_turns, max_repair_cycles,
                no_progress_limit, cloud_allowed, created_at, updated_at,
                dsh_session_id, revision
            ) VALUES (
                'task-v4', 'example-service', 'origin/main', 'obj',
                ?, 'queued', 'intake', 'unattended', 'overnight',
                '/tmp/wt', 'agent/task-v4', 'abc', 480, 30, 6, 2, 0, ?, ?, NULL, 4
            )
            """,
            (payload, "2026-08-30T12:00:00.000000Z", "2026-08-30T12:00:00.000000Z"),
        )
        connection.execute(
            """
            INSERT INTO idempotency_records (
                principal, idempotency_key, method, path, request_hash,
                status_code, response_body, response_headers_json, created_at
            ) VALUES (
                'local', 'key-1', 'POST', '/v1/tasks', 'hash-1',
                201, '{"ok":true}', '{}', '2026-08-30T12:00:00.000000Z'
            )
            """
        )
        connection.commit()
        assert current_schema_version(connection) == 4
    finally:
        connection.close()

    with open_store(v4_path) as opened:
        assert opened.schema_version() == 5
        record = opened.get_idempotency("local", "key-1")
        assert record is not None
        assert record.request_hash == "hash-1"
        assert record.status_code == 201
        task = opened.get_task("task-v4")
        assert task is not None
        assert task.revision == 4
        assert opened.load_graph("task-v4") is None
        names = opened._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        tables = {str(row[0]) for row in names}
        assert "work_nodes" in tables
        assert "work_edges" in tables
        assert "idempotency_records" in tables


def test_ensure_graph_compiles_from_current_stage(store: Store) -> None:
    store.insert_task(
        _manifest(id="task-restore"),
        lifecycle=LifecycleState.RUNNING,
        stage=WorkflowStage.REVIEW,
        now=T0,
    )
    task = store.get_task("task-restore")
    assert task is not None
    graph = store.ensure_graph(task, now=T0)
    assert graph.node("task-restore:inspect").status is NodeStatus.DONE
    assert graph.node("task-restore:plan").status is NodeStatus.DONE
    assert graph.node("task-restore:implement").status is NodeStatus.DONE
    assert graph.node("task-restore:validate").status is NodeStatus.DONE
    assert graph.node("task-restore:review").status is NodeStatus.READY
    again = store.ensure_graph(task, now=T0)
    assert [node.id for node in again.nodes] == [node.id for node in graph.nodes]
