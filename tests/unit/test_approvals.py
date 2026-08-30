# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline unit tests for durable questions, approvals, and cooperative cancel."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from two.approvals import (
    DEFAULT_PRINCIPAL,
    NotResumableError,
    StaleDigestError,
    TerminalLifecycleError,
    UnsafeTimeoutDefaultError,
    answer_question,
    apply_input_timeout,
    ask_question,
    cancel_task,
    compute_action_digest,
    decide_approval,
    pause_task,
    request_approval,
    resume_task,
)
from two.manifest import TaskManifest
from two.store import Store, open_store
from two.types import LifecycleState, OnHumanInputRequired, WorkflowStage

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
WORKTREE = "/tmp/worktrees/example-service/task-123"

REPO_ROOT = Path(__file__).resolve().parents[2]
APPROVALS_DIR = REPO_ROOT / "src" / "two" / "approvals"


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
        "on_human_input_required": "pause",
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


def _seed_running(store: Store, **overrides: object) -> None:
    store.insert_task(
        _manifest(**overrides),
        lifecycle=LifecycleState.RUNNING,
        stage=WorkflowStage.PLAN,
        worktree_path=WORKTREE,
        branch="agent/task-123",
        now=T0,
    )


def test_ask_question_persists_awaiting_input(store: Store) -> None:
    _seed_running(store)
    question = ask_question(
        store,
        "task-123",
        question_id="q-1",
        stage=WorkflowStage.PLAN,
        options=["keep lock", "retry"],
        reason="ambiguous strategy",
        recommendation="keep lock",
        actor="controller",
        now=T0,
    )
    assert question.status == "open"
    task = store.get_task("task-123")
    assert task is not None
    assert task.lifecycle is LifecycleState.AWAITING_INPUT
    assert task.worktree_path == WORKTREE
    assert task.id == "task-123"
    events = store.list_events("task-123")
    assert events[-1].type == "question.asked"
    assert events[-1].payload["lifecycle"] == "awaiting_input"


def test_duplicate_decide_is_ignored(store: Store) -> None:
    _seed_running(store)
    digest = compute_action_digest(action_class="dependency_lock_change", paths=["uv.lock"])
    request_approval(
        store,
        "task-123",
        approval_id="ap-1",
        action_class="dependency_lock_change",
        paths=["uv.lock"],
        action_digest=digest,
        now=T0,
    )
    first = decide_approval(
        store,
        "task-123",
        "ap-1",
        decision="approve",
        principal="operator-a",
        action_digest=digest,
        now=T0 + timedelta(seconds=1),
    )
    assert first.ignored is False
    assert first.decision == "approve"
    assert first.approval.status == "approved"
    stored_digest = first.approval.action_digest
    second = decide_approval(
        store,
        "task-123",
        "ap-1",
        decision="reject",
        principal="operator-b",
        action_digest=digest,
        now=T0 + timedelta(seconds=2),
    )
    assert second.ignored is True
    assert second.decision == "approve"
    again = store.get_approval("ap-1")
    assert again is not None
    assert again.status == "approved"
    assert again.action_digest == stored_digest
    assert again.action_digest == digest


def test_stale_digest_is_rejected(store: Store) -> None:
    _seed_running(store)
    original = compute_action_digest(action_class="dependency_lock_change", paths=["uv.lock"])
    patched = compute_action_digest(
        action_class="dependency_lock_change",
        paths=["uv.lock", "pyproject.toml"],
    )
    assert original != patched
    request_approval(
        store,
        "task-123",
        approval_id="ap-1",
        action_class="dependency_lock_change",
        paths=["uv.lock"],
        action_digest=original,
        now=T0,
    )
    with pytest.raises(StaleDigestError, match="stale action digest"):
        decide_approval(
            store,
            "task-123",
            "ap-1",
            decision="approve",
            principal="operator",
            action_digest=patched,
        )
    row = store.get_approval("ap-1")
    assert row is not None
    assert row.status == "open"
    assert row.action_digest == original


def test_resolve_approval_does_not_update_digest(store: Store) -> None:
    _seed_running(store)
    digest = "sha256:deadbeef"
    store.insert_approval(
        "ap-1",
        "task-123",
        action_class="dependency_lock_change",
        action_digest=digest,
        paths=["uv.lock"],
        now=T0,
    )
    record, first = store.resolve_approval("ap-1", status="approved", now=T0)
    assert first is True
    assert record.action_digest == digest
    duplicate, first_again = store.resolve_approval("ap-1", status="rejected", now=T0)
    assert first_again is False
    assert duplicate.status == "approved"
    assert duplicate.action_digest == digest


def test_pause_does_not_delete_rows_or_worktree_path(store: Store) -> None:
    _seed_running(store)
    ask_question(
        store,
        "task-123",
        question_id="q-1",
        stage=WorkflowStage.PLAN,
        options=["keep lock"],
        reason="need a decision",
        now=T0,
    )
    request_approval(
        store,
        "task-123",
        approval_id="ap-1",
        action_class="dependency_lock_change",
        paths=["uv.lock"],
        now=T0,
    )
    paused = pause_task(store, "task-123", principal="operator", now=T0 + timedelta(seconds=1))
    assert paused.lifecycle is LifecycleState.PAUSED
    assert paused.worktree_path == WORKTREE
    assert paused.branch == "agent/task-123"
    assert store.get_question("q-1") is not None
    assert store.get_approval("ap-1") is not None
    assert [row.type for row in store.list_events("task-123")]
    assert store.get_task("task-123") is not None
    assert store.get_task("task-123").id == "task-123"


def test_cancelled_task_cannot_be_resumed_into_running(store: Store) -> None:
    _seed_running(store)
    cancelled = cancel_task(store, "task-123", principal="operator", now=T0)
    assert cancelled.lifecycle is LifecycleState.CANCELLED
    assert cancelled.worktree_path == WORKTREE
    with pytest.raises(TerminalLifecycleError, match="cancelled"):
        resume_task(store, "task-123")
    task = store.get_task("task-123")
    assert task is not None
    assert task.lifecycle is LifecycleState.CANCELLED
    assert task.lifecycle is not LifecycleState.RUNNING
    assert task.worktree_path == WORKTREE


def test_silence_is_never_approval(store: Store) -> None:
    _seed_running(store)
    digest = compute_action_digest(action_class="dependency_lock_change", paths=["uv.lock"])
    request_approval(
        store,
        "task-123",
        approval_id="ap-1",
        action_class="dependency_lock_change",
        paths=["uv.lock"],
        action_digest=digest,
        now=T0,
    )
    still_waiting = apply_input_timeout(store, "task-123", now=T0 + timedelta(hours=2))
    assert still_waiting.lifecycle is LifecycleState.AWAITING_INPUT
    open_row = store.get_approval("ap-1")
    assert open_row is not None
    assert open_row.status == "open"
    assert open_row.status != "approved"
    timed_out = apply_input_timeout(
        store,
        "task-123",
        now=T0 + timedelta(hours=2),
        deadline=T0 + timedelta(minutes=30),
    )
    assert timed_out.lifecycle is LifecycleState.PAUSED
    expired = store.get_approval("ap-1")
    assert expired is not None
    assert expired.status == "expired"
    assert expired.status != "approved"
    assert expired.action_digest == digest
    with pytest.raises(UnsafeTimeoutDefaultError, match="silence is never approval"):
        apply_input_timeout(
            store,
            "task-123",
            now=T0 + timedelta(hours=3),
            deadline=T0,
            safe_default="approve",
        )


def test_timeout_block_policy_is_not_approval(store: Store) -> None:
    _seed_running(store, id="task-456", on_human_input_required=OnHumanInputRequired.BLOCK.value)
    ask_question(
        store,
        "task-456",
        question_id="q-block",
        stage=WorkflowStage.PLAN,
        options=["stop"],
        reason="need a human",
        now=T0,
    )
    result = apply_input_timeout(
        store,
        "task-456",
        now=T0 + timedelta(hours=1),
        deadline=T0,
    )
    assert result.lifecycle is LifecycleState.BLOCKED
    question = store.get_question("q-block")
    assert question is not None
    assert question.status == "expired"
    assert question.resolver == "timeout"


def test_resume_from_awaiting_input_keeps_task_id(store: Store) -> None:
    _seed_running(store)
    ask_question(
        store,
        "task-123",
        question_id="q-1",
        stage=WorkflowStage.PLAN,
        options=["keep lock", "retry"],
        reason="ambiguous strategy",
        now=T0,
    )
    answered = answer_question(
        store,
        "task-123",
        "q-1",
        answer="keep lock",
        principal="operator",
        now=T0 + timedelta(seconds=1),
    )
    assert answered.ignored is False
    duplicate = answer_question(
        store,
        "task-123",
        "q-1",
        answer="retry",
        principal="someone-else",
        now=T0 + timedelta(seconds=2),
    )
    assert duplicate.ignored is True
    waiting = store.get_task("task-123")
    assert waiting is not None
    assert waiting.lifecycle is LifecycleState.AWAITING_INPUT
    resumed = resume_task(store, "task-123", principal="operator", now=T0 + timedelta(seconds=3))
    assert resumed.id == "task-123"
    assert resumed.lifecycle is LifecycleState.QUEUED
    assert resumed.lifecycle is not LifecycleState.RUNNING
    assert resumed.worktree_path == WORKTREE
    event = store.list_events("task-123")[-1]
    assert event.type == "task.resumed"
    assert event.payload["from"] == "awaiting_input"
    assert event.payload["answers"][0]["question_id"] == "q-1"


def test_resume_from_running_is_refused(store: Store) -> None:
    _seed_running(store)
    with pytest.raises(NotResumableError, match="running"):
        resume_task(store, "task-123")


def test_empty_principal_becomes_local(store: Store) -> None:
    _seed_running(store)
    ask_question(
        store,
        "task-123",
        question_id="q-1",
        stage=WorkflowStage.PLAN,
        options=["a"],
        reason="choose",
        now=T0,
    )
    result = answer_question(store, "task-123", "q-1", answer="a", principal="  ")
    assert result.principal == DEFAULT_PRINCIPAL


def test_approvals_package_cannot_reach_the_model() -> None:
    for path in sorted(APPROVALS_DIR.glob("*.py")):
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
            assert name != "subprocess"
        assert "subprocess" not in source
        assert "/v1/chat/completions" not in source
