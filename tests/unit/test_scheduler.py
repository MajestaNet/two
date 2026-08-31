# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline unit tests for the durable scheduler (B08). No network."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from two.manifest import TaskManifest
from two.runtime.health import HealthState
from two.scheduler import (
    LOCAL_SLOT_COUNT,
    Scheduler,
    SchedulerConfig,
    WorkerCallback,
    WorkerOutcome,
    WorkerResult,
    retry_delay_seconds,
)
from two.scheduler.config import EVENT_BUDGET_EXCEEDED, EVENT_MAC_UNAVAILABLE
from two.store import Store, open_store
from two.types import LifecycleState

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


@dataclass
class FakeClock:
    now: datetime = T0

    def advance(self, **kwargs: float) -> datetime:
        self.now += timedelta(**kwargs)
        return self.now


@dataclass
class FakeHealth:
    state: HealthState = HealthState.HEALTHY

    def __call__(self) -> HealthState:
        return self.state


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


def _scheduler(
    store: Store,
    *,
    health: FakeHealth | None = None,
    worker: WorkerCallback | None = None,
    config: SchedulerConfig | None = None,
) -> Scheduler:
    return Scheduler(
        store,
        health_probe=health if health is not None else FakeHealth(),
        worker=worker,
        config=config,
    )


def test_local_slot_count_is_one() -> None:
    assert LOCAL_SLOT_COUNT == 1
    assert SchedulerConfig().slot_count == 1


def test_two_tasks_only_one_running(store: Store) -> None:
    clock = FakeClock()
    health = FakeHealth()
    assigned: list[str] = []

    def fake_worker(task_id: str, *, now: datetime) -> WorkerResult | None:
        assigned.append(task_id)
        return None

    store.insert_task(_manifest(id="task-a"), now=clock.now)
    store.insert_task(_manifest(id="task-b"), now=clock.now + timedelta(seconds=1))
    scheduler = _scheduler(store, health=health, worker=fake_worker)
    first = scheduler.tick(now=clock.now)
    assert first.dispatched is not None
    assert first.dispatched.id == "task-a"
    assert first.running_id == "task-a"
    running = store.list_tasks(lifecycle=LifecycleState.RUNNING)
    queued = store.list_tasks(lifecycle=LifecycleState.QUEUED)
    assert [row.id for row in running] == ["task-a"]
    assert [row.id for row in queued] == ["task-b"]
    clock.advance(seconds=5)
    second = scheduler.tick(now=clock.now)
    assert second.dispatched is None
    assert second.running_id == "task-a"
    assert [row.id for row in store.list_tasks(lifecycle=LifecycleState.RUNNING)] == ["task-a"]
    assert [row.id for row in store.list_tasks(lifecycle=LifecycleState.QUEUED)] == ["task-b"]
    assert assigned == ["task-a"]


def test_expired_lease_reclaimed_unexpired_not(store: Store) -> None:
    health = FakeHealth()
    config = SchedulerConfig(lease_ttl_seconds=30)
    store.insert_task(_manifest(id="task-a"), now=T0)
    scheduler = _scheduler(store, health=health, config=config)
    dispatched = scheduler.dispatch(now=T0)
    assert dispatched is not None
    lease = store.get_lease("task-a")
    assert lease is not None

    still = scheduler.start(now=T0 + timedelta(seconds=10))
    assert still.reclaimed == ()
    still_running = store.get_task("task-a")
    assert still_running is not None
    assert still_running.lifecycle is LifecycleState.RUNNING

    expired = scheduler.start(now=T0 + timedelta(seconds=31))
    assert expired.reclaimed == ("task-a",)
    assert store.get_lease("task-a") is None
    requeued = store.get_task("task-a")
    assert requeued is not None
    assert requeued.lifecycle is LifecycleState.QUEUED


def test_unavailable_mac_pauses_and_leaves_worktree_untouched(store: Store) -> None:
    health = FakeHealth()
    store.insert_task(
        _manifest(id="task-a"),
        worktree_path="/tmp/worktrees/example-service/task-a",
        branch="agent/task-a",
        base_commit="abc123",
        now=T0,
    )
    scheduler = _scheduler(store, health=health)
    scheduler.tick(now=T0)
    running = store.get_task("task-a")
    assert running is not None
    assert running.lifecycle is LifecycleState.RUNNING
    health.state = HealthState.UNAVAILABLE
    result = scheduler.tick(now=T0 + timedelta(seconds=5))
    assert result.health is HealthState.UNAVAILABLE
    assert "task-a" in result.paused_ids
    paused = store.get_task("task-a")
    assert paused is not None
    assert paused.lifecycle is LifecycleState.PAUSED
    assert paused.worktree_path == "/tmp/worktrees/example-service/task-a"
    assert paused.branch == "agent/task-a"
    assert paused.base_commit == "abc123"
    assert store.get_lease("task-a") is None
    types = [event.type for event in store.list_events("task-a")]
    assert EVENT_MAC_UNAVAILABLE in types


def test_human_paused_and_awaiting_input_not_auto_started(store: Store) -> None:
    health = FakeHealth()
    store.insert_task(
        _manifest(id="paused-task"),
        lifecycle=LifecycleState.PAUSED,
        now=T0,
    )
    store.insert_task(
        _manifest(id="waiting-task"),
        lifecycle=LifecycleState.AWAITING_INPUT,
        now=T0 + timedelta(seconds=1),
    )
    store.insert_task(
        _manifest(id="blocked-task"),
        lifecycle=LifecycleState.BLOCKED,
        now=T0 + timedelta(seconds=2),
    )
    scheduler = _scheduler(store, health=health)
    result = scheduler.tick(now=T0 + timedelta(seconds=10))
    assert result.dispatched is None
    assert result.running_id is None
    paused_task = store.get_task("paused-task")
    waiting_task = store.get_task("waiting-task")
    blocked_task = store.get_task("blocked-task")
    assert paused_task is not None and paused_task.lifecycle is LifecycleState.PAUSED
    assert waiting_task is not None and waiting_task.lifecycle is LifecycleState.AWAITING_INPUT
    assert blocked_task is not None and blocked_task.lifecycle is LifecycleState.BLOCKED
    assert store.list_tasks(lifecycle=LifecycleState.RUNNING) == []


def test_cold_and_busy_leave_queued_tasks(store: Store) -> None:
    store.insert_task(_manifest(id="task-a"), now=T0)
    health = FakeHealth(HealthState.COLD)
    scheduler = _scheduler(store, health=health)
    cold = scheduler.tick(now=T0)
    assert cold.dispatched is None
    cold_task = store.get_task("task-a")
    assert cold_task is not None and cold_task.lifecycle is LifecycleState.QUEUED
    health.state = HealthState.BUSY
    busy = scheduler.tick(now=T0 + timedelta(seconds=1))
    assert busy.dispatched is None
    busy_task = store.get_task("task-a")
    assert busy_task is not None and busy_task.lifecycle is LifecycleState.QUEUED
    health.state = HealthState.HEALTHY
    ready = scheduler.tick(now=T0 + timedelta(seconds=2))
    assert ready.dispatched is not None
    assert ready.dispatched.id == "task-a"


def test_retry_wait_backoff_and_eligibility(store: Store) -> None:
    config = SchedulerConfig(lease_ttl_seconds=10_000, retry_max_attempts=5)
    assert retry_delay_seconds(1, config) == 2
    assert retry_delay_seconds(2, config) == 4
    assert retry_delay_seconds(6, config) == 60
    health = FakeHealth()
    store.insert_task(_manifest(id="task-a"), now=T0)
    scheduler = _scheduler(store, health=health, config=config)
    scheduler.tick(now=T0)
    updated = scheduler.report_transient_failure("task-a", "http_429", now=T0)
    assert updated.lifecycle is LifecycleState.RETRY_WAIT
    assert updated.retry_count == 1
    assert updated.next_attempt_at == T0 + timedelta(seconds=2)
    assert store.get_lease("task-a") is None

    too_soon = scheduler.tick(now=T0 + timedelta(seconds=1))
    assert too_soon.promoted == ()
    assert too_soon.dispatched is None
    waiting = store.get_task("task-a")
    assert waiting is not None
    assert waiting.lifecycle is LifecycleState.RETRY_WAIT

    ready = scheduler.tick(now=T0 + timedelta(seconds=2))
    assert "task-a" in ready.promoted
    assert ready.dispatched is not None
    assert ready.dispatched.id == "task-a"
    assert ready.running_id == "task-a"

    second = scheduler.report_transient_failure("task-a", "http_503", now=T0 + timedelta(seconds=2))
    assert second.retry_count == 2
    assert second.next_attempt_at == T0 + timedelta(seconds=6)


def test_retry_cap_fails_task(store: Store) -> None:
    config = SchedulerConfig(lease_ttl_seconds=10_000, retry_max_attempts=2)
    health = FakeHealth()
    store.insert_task(_manifest(id="task-a"), now=T0)
    scheduler = _scheduler(store, health=health, config=config)
    now = T0
    for _attempt in range(2):
        scheduler.tick(now=now)
        scheduler.report_transient_failure("task-a", "connection", now=now)
        task = store.get_task("task-a")
        assert task is not None
        assert task.lifecycle is LifecycleState.RETRY_WAIT
        assert task.next_attempt_at is not None
        now = task.next_attempt_at
    scheduler.tick(now=now)
    failed = scheduler.report_transient_failure("task-a", "connection", now=now)
    assert failed.lifecycle is LifecycleState.FAILED
    assert failed.retry_count == 3


def test_active_budget_pause_excludes_awaiting_input(store: Store) -> None:
    config = SchedulerConfig(lease_ttl_seconds=10_000)
    health = FakeHealth()
    store.insert_task(_manifest(id="task-a", time_budget_minutes=1), now=T0)
    scheduler = _scheduler(store, health=health, config=config)
    scheduler.tick(now=T0)
    scheduler.release_slot(
        "task-a",
        LifecycleState.AWAITING_INPUT,
        now=T0 + timedelta(seconds=10),
        reason="question",
    )
    waiting = store.get_task("task-a")
    assert waiting is not None
    assert waiting.lifecycle is LifecycleState.AWAITING_INPUT
    assert waiting.active_elapsed_ms == 10_000
    later = scheduler.tick(now=T0 + timedelta(minutes=30))
    assert later.dispatched is None
    still = store.get_task("task-a")
    assert still is not None
    assert still.lifecycle is LifecycleState.AWAITING_INPUT
    assert still.active_elapsed_ms == 10_000

    store.insert_task(_manifest(id="task-b", time_budget_minutes=1), now=T0)
    scheduler.tick(now=T0)
    over = scheduler.tick(now=T0 + timedelta(minutes=2))
    assert "task-b" in over.budget_exceeded_ids
    paused = store.get_task("task-b")
    assert paused is not None
    assert paused.lifecycle is LifecycleState.PAUSED
    assert any(event.type == EVENT_BUDGET_EXCEEDED for event in store.list_events("task-b"))


def test_degraded_stops_new_work_and_pauses_current(store: Store) -> None:
    health = FakeHealth()
    store.insert_task(_manifest(id="task-a"), now=T0)
    store.insert_task(_manifest(id="task-b"), now=T0 + timedelta(seconds=1))
    scheduler = _scheduler(store, health=health)
    scheduler.tick(now=T0)
    health.state = HealthState.DEGRADED
    result = scheduler.tick(now=T0 + timedelta(seconds=5))
    paused = store.get_task("task-a")
    queued = store.get_task("task-b")
    assert paused is not None and paused.lifecycle is LifecycleState.PAUSED
    assert queued is not None and queued.lifecycle is LifecycleState.QUEUED
    assert result.dispatched is None


def test_fake_worker_can_release_slot(store: Store) -> None:
    def fake_worker(task_id: str, *, now: datetime) -> WorkerResult | None:
        if task_id == "task-a":
            return WorkerResult(outcome=WorkerOutcome.AWAITING_INPUT, detail="need approval")
        return None

    store.insert_task(_manifest(id="task-a"), now=T0)
    store.insert_task(_manifest(id="task-b"), now=T0 + timedelta(seconds=1))
    scheduler = _scheduler(store, worker=fake_worker)
    first = scheduler.tick(now=T0)
    assert first.dispatched is not None
    assert first.dispatched.lifecycle is LifecycleState.AWAITING_INPUT
    assert first.running_id is None
    second = scheduler.tick(now=T0 + timedelta(seconds=1))
    assert second.dispatched is not None
    assert second.dispatched.id == "task-b"
    assert second.running_id == "task-b"


def test_scheduler_module_has_no_slack_acp_or_worktree_git() -> None:
    root = Path("src/two/scheduler")
    imported: list[str] = []
    for path in sorted(root.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
    assert all("slack" not in name.lower() for name in imported)
    assert all(not name.startswith("two.channels") for name in imported)
    assert all(not name.startswith("two.workspace") for name in imported)
    assert all("acp" not in name.lower() for name in imported)
    git_mentions = [name for name in imported if name == "git" or name.startswith("git.")]
    assert git_mentions == []
