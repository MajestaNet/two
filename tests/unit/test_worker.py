# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline unit tests for the ACP worker (B09). No live DSH or Mac."""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from two.context.memory import TaskMemory
from two.manifest import TaskManifest
from two.scheduler import LOCAL_SLOT_COUNT, Scheduler, WorkerOutcome
from two.store import ActionStatus, Store, open_store
from two.types import LifecycleState
from two.worker import (
    CONNECT_TIMEOUT_SECONDS,
    INFERENCE_TIMEOUT_SECONDS,
    LOCAL_QWEN_WORKER_COUNT,
    STREAM_LIVENESS_SECONDS,
    AcpWorker,
    ActionLedger,
    ActionReplayError,
    RepairAction,
    SessionMode,
    ToolCallRepairPolicy,
    build_dsh_argv,
    plan_session,
)
from two.worker.timeouts import (
    CANCEL_GRACE_SECONDS,
    CHILD_HEARTBEAT_STALE_SECONDS,
)

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
FAKE_CHILD = Path(__file__).parent / "fixtures" / "acp" / "fake_acp_child.py"


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
        "time_budget_minutes": 90,
        "max_model_turns": 8,
        "max_repair_cycles": 3,
        "no_progress_limit": 2,
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


def test_local_qwen_worker_count_is_one() -> None:
    assert LOCAL_QWEN_WORKER_COUNT == 1
    assert LOCAL_QWEN_WORKER_COUNT == LOCAL_SLOT_COUNT
    assert AcpWorker.worker_count == 1


def test_timeouts_are_named_and_distinct() -> None:
    assert CONNECT_TIMEOUT_SECONDS < STREAM_LIVENESS_SECONDS
    assert STREAM_LIVENESS_SECONDS < INFERENCE_TIMEOUT_SECONDS
    assert CHILD_HEARTBEAT_STALE_SECONDS != INFERENCE_TIMEOUT_SECONDS
    assert CANCEL_GRACE_SECONDS > 0


def test_tool_call_repair_ladder() -> None:
    policy = ToolCallRepairPolicy()
    first = policy.on_invalid_json(detail="not json")
    assert first.action is RepairAction.SCHEMA_REPAIR
    second = policy.on_invalid_json(detail="still not json")
    assert second.action is RepairAction.FRESH_TURN
    third = policy.on_invalid_json(detail="again")
    assert third.action is RepairAction.ESCALATE


def test_repeated_identical_tool_call_stops() -> None:
    policy = ToolCallRepairPolicy()
    first = policy.on_tool_call("shell", {"cmd": "ls"})
    assert first.action is RepairAction.ACCEPT
    second = policy.on_tool_call("shell", {"cmd": "ls"})
    assert second.action is RepairAction.STOP
    other = ToolCallRepairPolicy()
    assert other.on_tool_call("shell", {"cmd": "ls"}).action is RepairAction.ACCEPT
    assert other.on_tool_call("shell", {"cmd": "pwd"}).action is RepairAction.ACCEPT


def test_plan_session_resumes_valid_id_same_task() -> None:
    plan = plan_session(
        task_id="task-a",
        stored_session_id="sess-live",
        objective="do the thing",
        session_is_valid=lambda sid: sid == "sess-live",
    )
    assert plan.mode is SessionMode.RESUME
    assert plan.task_id == "task-a"
    assert plan.session_id == "sess-live"


def test_plan_session_fresh_handoff_preserves_task_id() -> None:
    memory = TaskMemory(
        task_id="task-a",
        objective="Add optimistic locking to order updates",
        acceptance_criteria=["no silent overwrite"],
        plan="touch orders.py",
        current_step="implement",
        files_changed=["src/orders.py"],
    )
    plan = plan_session(
        task_id="task-a",
        stored_session_id="sess-dead",
        objective="Add optimistic locking to order updates",
        acceptance_criteria=["no silent overwrite"],
        memory=memory,
        diff_summary="1 file changed",
        session_is_valid=lambda _sid: False,
    )
    assert plan.mode is SessionMode.FRESH
    assert plan.task_id == "task-a"
    assert plan.session_id is None
    assert "task_id: task-a" in plan.prompt
    assert "no silent overwrite" in plan.prompt
    assert "Fresh review handoff" in plan.prompt
    assert "src/orders.py" in plan.prompt


def test_intent_persisted_before_fake_tool_runs(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    order: list[str] = []
    ledger = ActionLedger(store)

    def runner(intent: Mapping[str, object]) -> dict[str, object]:
        recorded = store.get_action("act-1")
        assert recorded is not None
        assert recorded.status is ActionStatus.RECORDED
        assert recorded.intent["tool"] == "echo"
        order.append("tool")
        return {"exit_code": 0, "output": "ok"}

    result = ledger.execute(
        "act-1",
        "task-a",
        {"tool": "echo"},
        runner,
        now=T0,
    )
    assert order == ["tool"]
    assert result.status is ActionStatus.EXECUTED
    assert result.result is not None
    assert result.result["exit_code"] == 0


def test_crash_before_result_reconciles_without_second_invoke(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    invokes: list[str] = []
    ledger = ActionLedger(store)

    def runner(intent: Mapping[str, object]) -> dict[str, object]:
        invokes.append(str(intent.get("tool")))
        raise RuntimeError("killed between execute and persist")

    first = ledger.execute("act-1", "task-a", {"tool": "patch"}, runner, now=T0)
    assert first.status is ActionStatus.RECONCILE
    assert invokes == ["patch"]
    events = store.list_events("task-a")
    assert any(event.type == "action_reconcile" for event in events)

    with pytest.raises(ActionReplayError) as raised:
        ledger.execute("act-1", "task-a", {"tool": "patch"}, runner, now=T0)
    assert raised.value.action_id == "act-1"
    assert invokes == ["patch"]
    assert store.get_action("act-1") is not None
    assert store.get_action("act-1").status is ActionStatus.RECONCILE  # type: ignore[union-attr]


def test_recover_recorded_action_does_not_replay(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    store.record_action("act-gap", "task-a", {"tool": "rm"}, now=T0)
    invokes: list[int] = []
    ledger = ActionLedger(store)
    recovered = ledger.recover("task-a", now=T0)
    assert len(recovered) == 1
    assert recovered[0].status is ActionStatus.RECONCILE

    def runner(_intent: Mapping[str, object]) -> dict[str, object]:
        invokes.append(1)
        return {"exit_code": 0}

    with pytest.raises(ActionReplayError):
        ledger.execute("act-gap", "task-a", {"tool": "rm"}, runner, now=T0)
    assert invokes == []


def test_build_dsh_argv_uses_pin() -> None:
    argv = build_dsh_argv("task-a", "/tmp/wt")
    assert argv[0] == "dsh"
    assert "acp" in argv
    assert "task-a" in argv
    from two.providers import DSH_PIN

    assert DSH_PIN == "dsh-v0.1.2-alpha.1"
    assert DSH_PIN in argv


def test_worker_modules_do_not_import_slack_or_set_complete() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "two" / "worker"
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "slack" not in alias.name.lower()
                    assert alias.name != "two.channels"
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "slack" not in module.lower()
                assert module != "two.channels" and not module.startswith("two.channels.")
            if isinstance(node, ast.Attribute) and node.attr == "COMPLETE":
                raise AssertionError(f"{path} references COMPLETE")


def test_acp_worker_as_scheduler_callback_does_not_complete(
    store: Store,
) -> None:
    store.insert_task(_manifest(), now=T0)
    worker = AcpWorker(
        store,
        argv=[sys.executable, str(FAKE_CHILD), "--mode", "heartbeat-once"],
    )
    scheduler = Scheduler(store, worker=worker)
    dispatched = scheduler.dispatch(now=T0)
    assert dispatched is not None
    assert dispatched.lifecycle is LifecycleState.RUNNING
    assert dispatched.id == "task-a"
    events = store.list_events("task-a")
    types = [event.type for event in events]
    assert "acp_child_started" in types
    assert "acp_session_fresh" in types
    assert dispatched.dsh_session_id == "fake-session-1"


def test_session_resume_emits_resume_event(store: Store) -> None:
    store.insert_task(_manifest(), now=T0)
    store.update_task(
        "task-a",
        dsh_session_id="sess-live",
        set_dsh_session_id=True,
        now=T0,
    )
    worker = AcpWorker(
        store,
        argv=[sys.executable, str(FAKE_CHILD), "--mode", "heartbeat-once"],
        session_is_valid=lambda sid: sid == "sess-live",
    )
    result = worker.run("task-a", now=T0)
    assert result.outcome is WorkerOutcome.CONTINUE
    types = [event.type for event in store.list_events("task-a")]
    assert "acp_session_resume" in types
    assert store.get_task("task-a") is not None
    assert store.get_task("task-a").id == "task-a"  # type: ignore[union-attr]
