# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline startup-recovery tests (B12 / architecture §12.5). No live Mac or DSH."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from two.controller import WorkerInstruction, WorkerPhaseResult, WorkflowController
from two.manifest import TaskManifest
from two.recovery import EVENT_STARTUP_RECOVERY, LastActionClass, recover_startup
from two.recovery.boot import run_scheduler, run_worker
from two.recovery.models import WorktreeCheck
from two.runtime.health import HealthState
from two.runtime.poller import mac_health_probe_from_env, probe_mac_health
from two.scheduler import Scheduler
from two.store import ActionStatus, Store, open_store
from two.store.models import TaskRecord
from two.types import LifecycleState, WorkflowStage
from two.validation import load_default_policy
from two.validation.results import GateResult, ValidationResult
from two.worker import ActionLedger, ActionReplayError
from two.workspace.identity import branch_for_task
from two.workspace.models import Workspace, WorkspaceStatus

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


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


def _verify(task: TaskRecord) -> WorktreeCheck:
    if not task.worktree_path:
        return WorktreeCheck(task_id=task.id, ok=True, path=None, reason="no_worktree")
    path = Path(task.worktree_path)
    return WorktreeCheck(
        task_id=task.id,
        ok=path.is_dir(),
        path=str(path),
        branch=task.branch,
        base_commit=task.base_commit,
        reason="ok" if path.is_dir() else "missing",
    )


def test_recover_reclaims_expired_lease_leaves_paused_and_does_not_replay(
    store: Store,
    tmp_path: Path,
) -> None:
    running_tree = tmp_path / "wt-run"
    paused_tree = tmp_path / "wt-pause"
    running_tree.mkdir()
    paused_tree.mkdir()

    store.insert_task(
        _manifest(id="runnable"),
        lifecycle=LifecycleState.RUNNING,
        worktree_path=str(running_tree),
        branch="agent/runnable",
        base_commit="abc123",
        now=T0,
    )
    store.obtain_lease("runnable", "local-qwen-1", ttl_seconds=30, now=T0)
    store.record_action("act-gap", "runnable", {"tool": "rm"}, now=T0)

    store.insert_task(
        _manifest(id="paused"),
        lifecycle=LifecycleState.PAUSED,
        worktree_path=str(paused_tree),
        branch="agent/paused",
        base_commit="abc123",
        now=T0 + timedelta(seconds=1),
    )
    store.record_action("act-done", "paused", {"tool": "echo"}, now=T0)
    store.complete_action(
        "act-done",
        status=ActionStatus.EXECUTED,
        result={"exit_code": 0},
        now=T0,
    )

    report = recover_startup(
        store,
        now=T0 + timedelta(seconds=31),
        health_probe=lambda: HealthState.HEALTHY,
        harness_probe=lambda: True,
        worktree_verifier=_verify,
    )

    assert store.verify() >= 1
    assert report.reclaimed == ("runnable",)
    assert store.get_lease("runnable") is None
    runnable = store.get_task("runnable")
    paused = store.get_task("paused")
    assert runnable is not None and runnable.lifecycle is LifecycleState.QUEUED
    assert paused is not None and paused.lifecycle is LifecycleState.PAUSED
    assert "paused" in report.paused_ids
    assert "runnable" in report.runnable_ids
    assert runnable.worktree_path == str(running_tree)

    gap = store.get_action("act-gap")
    assert gap is not None and gap.status is ActionStatus.RECONCILE
    by_task = {item.task_id: item for item in report.actions}
    assert by_task["runnable"].classification is LastActionClass.RECONCILE
    assert by_task["paused"].classification is LastActionClass.COMPLETED

    invokes: list[str] = []

    def runner(intent: Mapping[str, object]) -> dict[str, object]:
        invokes.append(str(intent.get("tool")))
        return {"exit_code": 0}

    ledger = ActionLedger(store)
    with pytest.raises(ActionReplayError) as raised:
        ledger.execute("act-gap", "runnable", {"tool": "rm"}, runner, now=T0)
    assert raised.value.action_id == "act-gap"
    assert invokes == []

    with pytest.raises(ActionReplayError):
        ledger.execute("act-done", "paused", {"tool": "echo"}, runner, now=T0)
    assert invokes == []

    assert report.event_id is not None
    assert report.event_task_id is not None
    recovery_events = [
        event
        for event in store.list_events(report.event_task_id)
        if event.type == EVENT_STARTUP_RECOVERY
    ]
    assert len(recovery_events) == 1

    started: list[str] = []

    def fake_worker(task_id: str, *, now: datetime) -> None:
        started.append(task_id)
        return None

    scheduler = Scheduler(
        store,
        health_probe=lambda: HealthState.HEALTHY,
        worker=fake_worker,
    )
    scheduler.tick(now=T0 + timedelta(seconds=32))
    assert started == ["runnable"]
    still_paused = store.get_task("paused")
    assert still_paused is not None and still_paused.lifecycle is LifecycleState.PAUSED


def test_recover_does_not_dispatch_worker(store: Store, tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    store.insert_task(
        _manifest(id="queued"),
        lifecycle=LifecycleState.QUEUED,
        worktree_path=str(wt),
        now=T0,
    )
    report = recover_startup(
        store,
        now=T0,
        health_probe=lambda: HealthState.HEALTHY,
        worktree_verifier=_verify,
    )
    queued = store.get_task("queued")
    assert queued is not None and queued.lifecycle is LifecycleState.QUEUED
    assert report.runnable_ids == ("queued",)
    assert store.list_tasks(lifecycle=LifecycleState.RUNNING) == []


def test_run_scheduler_calls_recover_then_stops(store: Store) -> None:
    store.insert_task(_manifest(id="task-a"), now=T0)
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return True

    slept: list[float] = []
    code = run_scheduler(
        store=store,
        health_probe=lambda: HealthState.HEALTHY,
        harness_probe=lambda: True,
        worktree_verifier=_verify,
        should_stop=stop,
        sleep=slept.append,
        interval=0.01,
    )
    assert code == 0
    assert slept == []
    types = [event.type for event in store.list_events("task-a")]
    assert EVENT_STARTUP_RECOVERY in types


class _DriveWorker:
    def run_phase(
        self,
        task_id: str,
        instruction: WorkerInstruction,
        *,
        now: object = None,
    ) -> WorkerPhaseResult:
        del task_id, now
        if instruction.stage is WorkflowStage.PLAN:
            return WorkerPhaseResult(
                ok=True,
                plan="Patch src/x.py",
                files_named=("src/x.py",),
                tests_named=("tests/test_x.py",),
                assumptions=("fixture",),
            )
        if instruction.stage is WorkflowStage.IMPLEMENT:
            return WorkerPhaseResult(
                ok=True,
                files_changed=("src/x.py",),
                wrote_worktree=True,
                summary="patched",
            )
        return WorkerPhaseResult(ok=True, summary="ok")


class _DriveValidate:
    def run(
        self,
        workspace: Workspace,
        *,
        manifest: object,
        policy: object | None = None,
    ) -> ValidationResult:
        del manifest, policy
        return ValidationResult(
            passed=True,
            gates=[GateResult(name="test", passed=True, exit_code=0, summary="ok")],
            artifact_dir=workspace.worktree,
            worktree=workspace.worktree,
            task_id=workspace.task_id,
        )


class _DriveWorkspaces:
    def __init__(self, root: Path) -> None:
        self.root = root

    def create(
        self,
        task_id: str,
        repo_path: str | Path,
        base_ref: str,
        *,
        repo_id: str | None = None,
    ) -> Workspace:
        del repo_path, base_ref
        worktree = self.root / "wt" / task_id
        worktree.mkdir(parents=True, exist_ok=True)
        return Workspace(
            task_id=task_id,
            branch=branch_for_task(task_id),
            worktree=worktree,
            base_commit="abc",
            repo_id=repo_id or "example-service",
            canonical_repo=self.root / "canonical",
        )

    def status(self, workspace: Workspace) -> WorkspaceStatus:
        return WorkspaceStatus(clean=True, head="finalhead", diff_fingerprint="fp")


def test_run_worker_drives_controller_to_complete(store: Store, tmp_path: Path) -> None:
    store.insert_task(_manifest(id="task-a"), lifecycle=LifecycleState.RUNNING, now=T0)
    store.obtain_lease("task-a", "local-qwen-1", ttl_seconds=60, now=T0)
    controller = WorkflowController(
        store,
        worker=_DriveWorker(),
        validate=_DriveValidate(),
        workspaces=_DriveWorkspaces(tmp_path),
        locate_repository=lambda _repo: tmp_path / "canonical",
        policy=load_default_policy(),
        data_dir=tmp_path / "data",
    )
    ticks = {"n": 0}

    def stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 1

    code = run_worker(
        store=store,
        controller=controller,
        should_stop=stop,
        sleep=lambda _s: None,
        now=T0,
        poll_interval=0.0,
    )
    assert code == 0
    task = store.get_task("task-a")
    assert task is not None
    assert task.lifecycle is LifecycleState.COMPLETE
    assert task.lifecycle is not LifecycleState.RUNNING


def test_poller_refuses_public_origin_without_network() -> None:
    assert probe_mac_health("http://0.0.0.0:11434") is HealthState.UNAVAILABLE
    probe = mac_health_probe_from_env({})
    assert probe() is HealthState.HEALTHY
