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

"""Process entrypoints for scheduler and worker services.

``recover_startup`` runs at scheduler boot. The worker polls SQLite for a
leased running task and does not emit a second recovery event.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from two.recovery.models import HarnessProbe, WorktreeVerifier
from two.recovery.recover import recover_startup
from two.runtime.poller import mac_health_probe_from_env
from two.scheduler.config import DEFAULT_WORKER_ID, HEARTBEAT_INTERVAL_SECONDS
from two.scheduler.models import HealthProbe
from two.scheduler.scheduler import Scheduler
from two.store.models import TaskRecord
from two.store.store import Store, open_store
from two.types import LifecycleState
from two.worker.worker import AcpWorker

ShouldStop = Callable[[], bool]
SleepFn = Callable[[float], None]


def run_scheduler(
    *,
    store: Store | None = None,
    health_probe: HealthProbe | None = None,
    harness_probe: HarnessProbe | None = None,
    worktree_verifier: WorktreeVerifier | None = None,
    interval: float | None = None,
    should_stop: ShouldStop | None = None,
    sleep: SleepFn | None = None,
    recover: bool = True,
    env: Mapping[str, str] | None = None,
) -> int:
    """Verify the store, run startup recovery, then tick until stopped."""
    opened = store is None
    owned = store if store is not None else open_store()
    probe = health_probe if health_probe is not None else mac_health_probe_from_env(env)
    wait = interval if interval is not None else float(HEARTBEAT_INTERVAL_SECONDS)
    nap = sleep if sleep is not None else time.sleep
    try:
        if recover:
            recover_startup(
                owned,
                health_probe=probe,
                harness_probe=harness_probe,
                worktree_verifier=worktree_verifier,
            )
        scheduler = Scheduler(owned, health_probe=probe, worker=None)
        while True:
            if should_stop is not None and should_stop():
                return 0
            scheduler.tick()
            nap(wait)
    finally:
        if opened:
            owned.close()


def run_worker(
    *,
    store: Store | None = None,
    worker_id: str = DEFAULT_WORKER_ID,
    poll_interval: float = 1.0,
    should_stop: ShouldStop | None = None,
    sleep: SleepFn | None = None,
    now: datetime | None = None,
    worker: AcpWorker | None = None,
) -> int:
    """Poll for a running task leased to ``worker_id`` and supervise ACP."""
    opened = store is None
    owned = store if store is not None else open_store()
    nap = sleep if sleep is not None else time.sleep
    supervisor = worker if worker is not None else AcpWorker(owned)
    try:
        while True:
            if should_stop is not None and should_stop():
                return 0
            task = _leased_running(owned, worker_id)
            if task is not None:
                instant = now if now is not None else datetime.now(UTC)
                supervisor.run(task.id, now=instant)
            nap(poll_interval)
    finally:
        if opened:
            owned.close()


def _leased_running(store: Store, worker_id: str) -> TaskRecord | None:
    for task in store.list_tasks(lifecycle=LifecycleState.RUNNING):
        lease = store.get_lease(task.id)
        if lease is not None and lease.worker_id == worker_id:
            return task
    return None
