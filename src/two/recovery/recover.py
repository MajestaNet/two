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

"""Development-host startup recovery (architecture §12.5 steps 1–7).

Called at scheduler boot. Does not dispatch a worker and does not construct a
new task. Human-paused tasks stay paused. The B09 action ledger is the only
replay authority: recorded-without-result actions are reconciled, never
re-issued.
"""

from __future__ import annotations

from datetime import UTC, datetime

from two.recovery.models import (
    ActionClassification,
    HarnessProbe,
    LastActionClass,
    RecoveryReport,
    WorktreeVerifier,
)
from two.recovery.worktree import verify_worktree
from two.runtime.health import HealthState
from two.scheduler.models import HealthProbe
from two.scheduler.scheduler import Scheduler
from two.store.models import ActionStatus, TaskRecord
from two.store.store import Store
from two.types import LifecycleState
from two.worker.ledger import ActionLedger

EVENT_STARTUP_RECOVERY = "startup_recovery"

_TERMINAL = frozenset(
    {
        LifecycleState.COMPLETE,
        LifecycleState.FAILED,
        LifecycleState.CANCELLED,
    }
)
_HUMAN_HOLD = frozenset(
    {
        LifecycleState.PAUSED,
        LifecycleState.AWAITING_INPUT,
        LifecycleState.BLOCKED,
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


def _harness_ok() -> bool:
    return True


def recover_startup(
    store: Store,
    *,
    now: datetime | None = None,
    health_probe: HealthProbe | None = None,
    harness_probe: HarnessProbe | None = None,
    worktree_verifier: WorktreeVerifier | None = None,
) -> RecoveryReport:
    """Run architecture §12.5 steps 1–7 and return a report.

    1. Open/verify SQLite (caller opened ``store``; this checks integrity).
    2. Reclaim expired leases only (B08 ``Scheduler.start``).
    3. Verify worktrees for non-terminal tasks.
    4. Classify last actions via B09 ``ActionLedger.recover`` (no replay).
    5. Check Mac and Harness health (injectable; default is healthy/offline).
    6. Leave human-paused / awaiting-input / blocked tasks untouched.
       Expired-lease running tasks are already requeued. This function does
       not dispatch a worker.
    7. Emit one ``startup_recovery`` event on an existing non-terminal task.
    """
    instant = _utc(now)
    schema_version = store.verify()
    mac_probe = health_probe or _healthy
    harness = harness_probe or _harness_ok
    verifier = worktree_verifier or verify_worktree

    scheduler = Scheduler(store, health_probe=mac_probe, worker=None)
    started = scheduler.start(now=instant)

    non_terminal = [task for task in store.list_tasks() if task.lifecycle not in _TERMINAL]
    worktrees = tuple(verifier(task) for task in non_terminal)
    actions = tuple(_classify_actions(store, task, now=instant) for task in non_terminal)

    mac_health = mac_probe()
    harness_ok = harness()

    paused_ids = tuple(task.id for task in non_terminal if task.lifecycle in _HUMAN_HOLD)
    runnable_ids: tuple[str, ...]
    if mac_health is HealthState.HEALTHY and harness_ok:
        runnable_ids = tuple(
            task.id
            for task in store.list_tasks(lifecycle=LifecycleState.QUEUED)
            if task.lifecycle not in _HUMAN_HOLD
        )
    else:
        runnable_ids = ()

    event_task_id: str | None = None
    event_id: int | None = None
    if non_terminal:
        event_task_id = non_terminal[0].id
        event_id = store.append_event(
            event_task_id,
            EVENT_STARTUP_RECOVERY,
            {
                "schema_version": schema_version,
                "reclaimed": list(started.reclaimed),
                "runnable": list(runnable_ids),
                "paused": list(paused_ids),
                "mac_health": mac_health.value,
                "harness_ok": harness_ok,
                "actions": [
                    {
                        "task_id": item.task_id,
                        "action_id": item.action_id,
                        "classification": item.classification.value,
                    }
                    for item in actions
                ],
                "worktrees": [
                    {
                        "task_id": item.task_id,
                        "ok": item.ok,
                        "reason": item.reason,
                    }
                    for item in worktrees
                ],
            },
            now=instant,
        )

    return RecoveryReport(
        now=instant,
        schema_version=schema_version,
        reclaimed=started.reclaimed,
        worktrees=worktrees,
        actions=actions,
        mac_health=mac_health,
        harness_ok=harness_ok,
        runnable_ids=runnable_ids,
        paused_ids=paused_ids,
        event_id=event_id,
        event_task_id=event_task_id,
    )


def _classify_actions(
    store: Store,
    task: TaskRecord,
    *,
    now: datetime,
) -> ActionClassification:
    """Reconcile ``recorded`` rows through B09; never invoke a tool runner."""
    ledger = ActionLedger(store, worktree=task.worktree_path)
    recovered = ledger.recover(task.id, now=now)
    if recovered:
        last = recovered[-1]
        return ActionClassification(
            task_id=task.id,
            action_id=last.action_id,
            classification=LastActionClass.RECONCILE,
        )
    records = store.list_actions(task.id)
    if not records:
        return ActionClassification(
            task_id=task.id,
            action_id=None,
            classification=LastActionClass.SAFE_TO_RETRY,
        )
    last_record = records[-1]
    if last_record.status is ActionStatus.EXECUTED:
        return ActionClassification(
            task_id=task.id,
            action_id=last_record.action_id,
            classification=LastActionClass.COMPLETED,
        )
    if last_record.status is ActionStatus.RECONCILE:
        return ActionClassification(
            task_id=task.id,
            action_id=last_record.action_id,
            classification=LastActionClass.RECONCILE,
        )
    return ActionClassification(
        task_id=task.id,
        action_id=last_record.action_id,
        classification=LastActionClass.SAFE_TO_RETRY,
    )
