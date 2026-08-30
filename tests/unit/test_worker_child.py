# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Fake-ACP child process tests for B09. Default pytest does not launch DSH."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from two.manifest import TaskManifest
from two.scheduler import WorkerOutcome
from two.store import ActionStatus, Store, open_store
from two.worker import AcpWorker, ChildConfig, SupervisedChild

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
FAKE_CHILD = Path(__file__).parent / "fixtures" / "acp" / "fake_acp_child.py"
FAST = ChildConfig(
    connect_timeout_seconds=0.5,
    inference_timeout_seconds=2.0,
    stream_liveness_seconds=1.0,
    heartbeat_stale_seconds=8.0,
    cooperative_seconds=0.2,
    grace_seconds=0.25,
)


def _manifest(**overrides: object) -> TaskManifest:
    payload: dict[str, object] = {
        "id": "task-a",
        "repository": "example-service",
        "base_ref": "origin/main",
        "objective": "Add optimistic locking to order updates",
        "acceptance_criteria": ["Concurrent updates cannot silently overwrite"],
        "mode": "unattended",
        "execution_profile": "standard",
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


def _argv(mode: str) -> list[str]:
    return [sys.executable, str(FAKE_CHILD), "--mode", mode]


def test_fake_child_heartbeats_and_detaches_from_session() -> None:
    child = SupervisedChild(
        _argv("heartbeat"),
        task_id="task-a",
        config=FAST,
    )
    child.start()
    try:
        assert child.pid is not None
        assert child.in_new_session()
        beat = child.wait_message(types={"heartbeat"}, timeout=2.0)
        assert beat is not None
        assert beat["type"] == "heartbeat"
        session = child.wait_message(types={"session"}, timeout=2.0)
        assert session is not None
        assert session["session_id"] == "fake-session-1"
    finally:
        outcome = child.cancel()
        assert outcome.worktree_retained is True
        assert child.poll() is not None


def test_child_records_intent_before_fake_tool(store: Store, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    invoke_log = tmp_path / "invokes.log"
    store.insert_task(_manifest(), worktree_path=str(worktree), now=T0)
    worker = AcpWorker(
        store,
        argv=_argv("tool"),
        child_env={
            "TWO_FAKE_INVOKE_LOG": str(invoke_log),
            "TWO_FAKE_ACTION_ID": "act-1",
        },
        child_config=FAST,
    )
    result = worker.run("task-a", now=T0)
    assert result.outcome is WorkerOutcome.CONTINUE
    action = store.get_action("act-1")
    assert action is not None
    assert action.status is ActionStatus.EXECUTED
    assert invoke_log.read_text(encoding="utf-8").splitlines() == ["act-1"]
    assert (worktree / ".fake-acp-child").is_file()


def test_kill_between_execute_and_result_does_not_replay(store: Store, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    invoke_log = tmp_path / "invokes.log"
    store.insert_task(_manifest(), worktree_path=str(worktree), now=T0)
    worker = AcpWorker(
        store,
        argv=_argv("tool-crash"),
        child_env={
            "TWO_FAKE_INVOKE_LOG": str(invoke_log),
            "TWO_FAKE_ACTION_ID": "act-crash",
        },
        child_config=FAST,
    )
    first = worker.run("task-a", now=T0)
    assert first.outcome is WorkerOutcome.CONTINUE
    action = store.get_action("act-crash")
    assert action is not None
    assert action.status is ActionStatus.RECONCILE
    assert invoke_log.read_text(encoding="utf-8").splitlines() == ["act-crash"]

    second = worker.run("task-a", now=T0)
    assert second.outcome is WorkerOutcome.CONTINUE
    assert invoke_log.read_text(encoding="utf-8").splitlines() == ["act-crash"]
    again = store.get_action("act-crash")
    assert again is not None
    assert again.status is ActionStatus.RECONCILE
    assert store.get_task("task-a") is not None
    assert store.get_task("task-a").id == "task-a"  # type: ignore[union-attr]


def test_cancel_long_command_grace_kill_retains_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    kept = worktree / "kept.txt"
    kept.write_text("retain me\n", encoding="utf-8")
    child = SupervisedChild(
        _argv("long-command"),
        task_id="task-a",
        workspace=worktree,
        cwd=worktree,
        config=FAST,
    )
    child.start()
    beat = child.wait_message(types={"heartbeat"}, timeout=2.0)
    assert beat is not None
    outcome = child.cancel()
    assert outcome.cooperative is True
    assert outcome.killed is True
    assert outcome.worktree_retained is True
    assert kept.is_file()
    assert worktree.is_dir()
    assert child.poll() is not None


def test_invalid_tool_json_escalates_to_block(store: Store, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    store.insert_task(_manifest(), worktree_path=str(worktree), now=T0)
    worker = AcpWorker(
        store,
        argv=_argv("invalid-json"),
        child_config=FAST,
    )
    result = worker.run("task-a", now=T0)
    assert result.outcome is WorkerOutcome.BLOCKED
    assert result.detail == "tool_call_escalated"
    types = [event.type for event in store.list_events("task-a")]
    assert types.count("tool_call_repair") == 2
    assert "tool_call_escalate" in types


@pytest.mark.live_dsh
def test_live_dsh_pin_optional() -> None:
    """Opt-in: launch the pinned DSH binary. Default pytest excludes this."""
    if os.environ.get("TWO_LIVE_DSH") != "1":
        pytest.skip("set TWO_LIVE_DSH=1 to run against a real DeepSeek Harness")
    binary = shutil.which("dsh")
    if binary is None:
        pytest.skip("dsh is not on PATH")
    from two.providers import DSH_PIN

    assert DSH_PIN == "dsh-v0.1.2-alpha.1"
