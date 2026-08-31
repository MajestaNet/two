# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

"""Durable queue, single local-model slot, leases, retry_wait, and Mac health.

This module does not run git, worktrees, ACP, or Slack. Worker count for
the local Qwen route is one (architecture §12.2). Automatic cloud failover
is disabled. See docs/architecture.md §6.3.G and §12.2–12.5.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from two.runtime.health import HealthState
from two.scheduler.config import (
    EVENT_BUDGET_EXCEEDED,
    EVENT_DISPATCHED,
    EVENT_LEASE_RECLAIMED,
    EVENT_MAC_DEGRADED,
    EVENT_MAC_UNAVAILABLE,
    EVENT_RETRY_EXHAUSTED,
    EVENT_RETRY_READY,
    EVENT_RETRY_WAIT,
    EVENT_SLOT_RELEASED,
    LOCAL_SLOT_COUNT,
    SchedulerConfig,
    active_budget_ms,
    retry_delay_seconds,
)
from two.scheduler.errors import SchedulerError
from two.scheduler.models import (
    HealthProbe,
    StartResult,
    TickResult,
    WorkerCallback,
    WorkerOutcome,
    WorkerResult,
)
from two.store.models import LeaseRecord, TaskRecord
from two.store.store import Store
from two.types import LifecycleState

_RELEASE_STATES = frozenset(
    {
        LifecycleState.AWAITING_INPUT,
        LifecycleState.PAUSED,
        LifecycleState.BLOCKED,
        LifecycleState.RETRY_WAIT,
        LifecycleState.COMPLETE,
        LifecycleState.FAILED,
        LifecycleState.CANCELLED,
    }
)


def _utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _healthy() -> HealthState:
    return HealthState.HEALTHY


class Scheduler:
    """Owns the single local-model slot. Pass ``now=`` for a fake clock."""

    def __init__(
        self,
        store: Store,
        *,
        health_probe: HealthProbe | None = None,
        worker: WorkerCallback | None = None,
        config: SchedulerConfig | None = None,
    ) -> None:
        self._store = store
        self._health_probe: HealthProbe = health_probe or _healthy
        self._worker = worker
        self._config = config if config is not None else SchedulerConfig()

    @property
    def config(self) -> SchedulerConfig:
        return self._config

    @property
    def worker_id(self) -> str:
        return self._config.worker_id

    def start(self, *, now: datetime | None = None) -> StartResult:
        """Reclaim expired leases only. Unexpired leases and human-paused tasks stay."""
        instant = _utc(now)
        reclaimed = tuple(self._store.reclaim_expired(now=instant))
        for task_id in reclaimed:
            task = self._store.get_task(task_id)
            if task is None:
                continue
            if task.lifecycle is LifecycleState.RUNNING:
                elapsed = _closed_active_ms(task, instant)
                self._store.update_task(
                    task_id,
                    lifecycle=LifecycleState.QUEUED,
                    active_elapsed_ms=elapsed,
                    active_started_at=None,
                    set_active_started_at=True,
                    now=instant,
                )
                self._store.append_event(
                    task_id,
                    EVENT_LEASE_RECLAIMED,
                    {"worker_id": self._config.worker_id},
                    now=instant,
                )
        return StartResult(now=instant, reclaimed=reclaimed)

    def tick(self, *, now: datetime | None = None) -> TickResult:
        """One cycle: reclaim expired, health, budgets, retry_wait, heartbeat, dispatch."""
        instant = _utc(now)
        started = self.start(now=instant)
        paused: list[str] = []
        budget_exceeded: list[str] = []
        health = self._health_probe()
        self._apply_health(health, instant, paused)
        self._enforce_budgets(instant, paused, budget_exceeded)
        promoted = self._promote_retry_wait(instant)
        self._heartbeat(instant)
        dispatched: TaskRecord | None = None
        if health is HealthState.HEALTHY and not self._slot_busy():
            dispatched = self.dispatch(now=instant)
        running = self._running_task()
        return TickResult(
            now=instant,
            health=health,
            reclaimed=started.reclaimed,
            promoted=promoted,
            dispatched=dispatched,
            running_id=None if running is None else running.id,
            paused_ids=tuple(paused),
            budget_exceeded_ids=tuple(budget_exceeded),
        )

    def dispatch(self, *, now: datetime | None = None) -> TaskRecord | None:
        """Pick the oldest eligible ``queued`` task, obtain a lease, set ``running``.

        Does nothing when the slot is occupied, Mac health is not Healthy, or
        no queued task exists. Human-paused and awaiting-input tasks are never
        selected. Does not implement git worktree logic.
        """
        instant = _utc(now)
        if self._health_probe() is not HealthState.HEALTHY:
            return None
        if self._slot_busy():
            return None
        queued = self._store.list_tasks(lifecycle=LifecycleState.QUEUED)
        if not queued:
            return None
        task = queued[0]
        lease = self._store.obtain_lease(
            task.id,
            self._config.worker_id,
            ttl_seconds=self._config.lease_ttl_seconds,
            now=instant,
        )
        if lease is None:
            return None
        updated = self._store.update_task(
            task.id,
            lifecycle=LifecycleState.RUNNING,
            next_attempt_at=None,
            set_next_attempt_at=True,
            active_started_at=instant,
            set_active_started_at=True,
            now=instant,
        )
        self._store.append_event(
            task.id,
            EVENT_DISPATCHED,
            {
                "worker_id": self._config.worker_id,
                "lease_expires_at": lease.expires_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            },
            now=instant,
        )
        if self._worker is not None:
            result = self._worker(updated.id, now=instant)
            if result is not None and result.outcome is not WorkerOutcome.CONTINUE:
                updated = self._apply_worker_result(updated, result, instant)
        return self._store.get_task(updated.id)

    def heartbeat(self, *, now: datetime | None = None) -> LeaseRecord | None:
        """Renew the running task's lease if this process owns it."""
        return self._heartbeat(_utc(now))

    def release_slot(
        self,
        task_id: str,
        lifecycle: LifecycleState,
        *,
        now: datetime | None = None,
        reason: str | None = None,
    ) -> TaskRecord:
        """Drop the local-model slot. Does not auto-start the task."""
        if lifecycle not in _RELEASE_STATES:
            raise SchedulerError(f"cannot release slot into {lifecycle.value}")
        instant = _utc(now)
        task = self._require_task(task_id)
        elapsed = _closed_active_ms(task, instant)
        updated = self._store.update_task(
            task_id,
            lifecycle=lifecycle,
            active_elapsed_ms=elapsed,
            active_started_at=None,
            set_active_started_at=True,
            now=instant,
        )
        self._store.release_lease(task_id, self._config.worker_id)
        payload: dict[str, object] = {"lifecycle": lifecycle.value}
        if reason:
            payload["reason"] = reason
        self._store.append_event(task_id, EVENT_SLOT_RELEASED, payload, now=instant)
        return updated

    def report_transient_failure(
        self,
        task_id: str,
        error_class: str,
        *,
        now: datetime | None = None,
        detail: str | None = None,
    ) -> TaskRecord:
        """Enter ``retry_wait`` with bounded exponential backoff, or fail at the cap."""
        instant = _utc(now)
        task = self._require_task(task_id)
        if task.lifecycle is not LifecycleState.RUNNING:
            raise SchedulerError(f"task {task_id} is not running")
        return self._enter_retry_wait(task, error_class, instant, detail=detail)

    def _apply_health(
        self,
        health: HealthState,
        now: datetime,
        paused: list[str],
    ) -> None:
        running = self._running_task()
        if running is None:
            return
        if health is HealthState.UNAVAILABLE:
            self._pause_running(
                running,
                now,
                event_type=EVENT_MAC_UNAVAILABLE,
                reason="mac_unavailable",
            )
            paused.append(running.id)
            return
        if health is HealthState.DEGRADED:
            # Stop new work (dispatch is gated). Pause current at a safe
            # boundary so a wrong/stalling model is not kept on the slot.
            self._pause_running(
                running,
                now,
                event_type=EVENT_MAC_DEGRADED,
                reason="mac_degraded",
            )
            paused.append(running.id)

    def _pause_running(
        self,
        task: TaskRecord,
        now: datetime,
        *,
        event_type: str,
        reason: str,
    ) -> TaskRecord:
        elapsed = _closed_active_ms(task, now)
        updated = self._store.update_task(
            task.id,
            lifecycle=LifecycleState.PAUSED,
            active_elapsed_ms=elapsed,
            active_started_at=None,
            set_active_started_at=True,
            now=now,
        )
        self._store.release_lease(task.id, self._config.worker_id)
        self._store.append_event(
            task.id,
            event_type,
            {"reason": reason, "worktree_path": task.worktree_path},
            now=now,
        )
        return updated

    def _enforce_budgets(
        self,
        now: datetime,
        paused: list[str],
        budget_exceeded: list[str],
    ) -> None:
        running = self._running_task()
        if running is None:
            return
        projected = _closed_active_ms(running, now)
        budget = active_budget_ms(running.time_budget_minutes, running.execution_profile)
        if projected <= budget:
            return
        wall_ms = max(0, int((now - running.created_at).total_seconds() * 1000))
        self._store.append_event(
            running.id,
            EVENT_BUDGET_EXCEEDED,
            {
                "active_elapsed_ms": projected,
                "wall_clock_ms": wall_ms,
                "budget_ms": budget,
            },
            now=now,
        )
        self.release_slot(
            running.id,
            LifecycleState.PAUSED,
            now=now,
            reason="budget_exceeded",
        )
        paused.append(running.id)
        budget_exceeded.append(running.id)

    def _promote_retry_wait(self, now: datetime) -> tuple[str, ...]:
        promoted: list[str] = []
        waiting = self._store.list_tasks(lifecycle=LifecycleState.RETRY_WAIT)
        for task in waiting:
            due = task.next_attempt_at
            if due is not None and now < due:
                continue
            self._store.update_task(
                task.id,
                lifecycle=LifecycleState.QUEUED,
                now=now,
            )
            self._store.append_event(
                task.id,
                EVENT_RETRY_READY,
                {"retry_count": task.retry_count},
                now=now,
            )
            promoted.append(task.id)
        return tuple(promoted)

    def _heartbeat(self, now: datetime) -> LeaseRecord | None:
        running = self._running_task()
        if running is None:
            return None
        lease = self._store.get_lease(running.id)
        if lease is None:
            return None
        if lease.worker_id != self._config.worker_id:
            return None
        if lease.expires_at < now:
            return None
        return self._store.heartbeat_lease(
            running.id,
            self._config.worker_id,
            ttl_seconds=self._config.lease_ttl_seconds,
            now=now,
        )

    def _slot_busy(self) -> bool:
        running = self._store.list_tasks(lifecycle=LifecycleState.RUNNING)
        return len(running) >= LOCAL_SLOT_COUNT

    def _running_task(self) -> TaskRecord | None:
        running = self._store.list_tasks(lifecycle=LifecycleState.RUNNING)
        if not running:
            return None
        return running[0]

    def _require_task(self, task_id: str) -> TaskRecord:
        task = self._store.get_task(task_id)
        if task is None:
            raise SchedulerError(f"unknown task: {task_id}")
        return task

    def _enter_retry_wait(
        self,
        task: TaskRecord,
        error_class: str,
        now: datetime,
        *,
        detail: str | None,
    ) -> TaskRecord:
        new_count = task.retry_count + 1
        elapsed = _closed_active_ms(task, now)
        if new_count > self._config.retry_max_attempts:
            updated = self._store.update_task(
                task.id,
                lifecycle=LifecycleState.FAILED,
                retry_count=new_count,
                active_elapsed_ms=elapsed,
                active_started_at=None,
                set_active_started_at=True,
                now=now,
            )
            self._store.release_lease(task.id, self._config.worker_id)
            payload: dict[str, object] = {
                "error_class": error_class,
                "retry_count": new_count,
            }
            if detail:
                payload["detail"] = detail
            self._store.append_event(task.id, EVENT_RETRY_EXHAUSTED, payload, now=now)
            return updated
        delay = retry_delay_seconds(new_count, self._config)
        next_attempt = now + timedelta(seconds=delay)
        updated = self._store.update_task(
            task.id,
            lifecycle=LifecycleState.RETRY_WAIT,
            retry_count=new_count,
            next_attempt_at=next_attempt,
            set_next_attempt_at=True,
            active_elapsed_ms=elapsed,
            active_started_at=None,
            set_active_started_at=True,
            now=now,
        )
        self._store.release_lease(task.id, self._config.worker_id)
        wait_payload: dict[str, object] = {
            "error_class": error_class,
            "retry_count": new_count,
            "delay_seconds": delay,
            "next_attempt_at": next_attempt.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }
        if detail:
            wait_payload["detail"] = detail
        self._store.append_event(task.id, EVENT_RETRY_WAIT, wait_payload, now=now)
        return updated

    def _apply_worker_result(
        self,
        task: TaskRecord,
        result: WorkerResult,
        now: datetime,
    ) -> TaskRecord:
        if result.outcome is WorkerOutcome.TRANSIENT_FAILURE:
            error_class = result.error_class or "connection"
            return self._enter_retry_wait(task, error_class, now, detail=result.detail)
        if result.outcome is WorkerOutcome.COMPLETE:
            # Terminal complete is controller-owned (B10 / architecture §6.3.A).
            return task
        mapping = {
            WorkerOutcome.AWAITING_INPUT: LifecycleState.AWAITING_INPUT,
            WorkerOutcome.PAUSED: LifecycleState.PAUSED,
            WorkerOutcome.BLOCKED: LifecycleState.BLOCKED,
            WorkerOutcome.FAILED: LifecycleState.FAILED,
            WorkerOutcome.CANCELLED: LifecycleState.CANCELLED,
        }
        lifecycle = mapping.get(result.outcome)
        if lifecycle is None:
            return task
        return self.release_slot(task.id, lifecycle, now=now, reason=result.detail)


def _closed_active_ms(task: TaskRecord, now: datetime) -> int:
    elapsed = task.active_elapsed_ms
    if task.active_started_at is not None:
        delta = now - task.active_started_at
        elapsed += max(0, int(delta.total_seconds() * 1000))
    return elapsed
