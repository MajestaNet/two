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

"""Scheduler result types. No I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from two.runtime.health import HealthState
from two.store.models import TaskRecord


class WorkerOutcome(StrEnum):
    """Fake-worker (and later ACP-worker) result for one dispatched task."""

    CONTINUE = "continue"
    AWAITING_INPUT = "awaiting_input"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TRANSIENT_FAILURE = "transient_failure"


@dataclass(frozen=True, slots=True)
class WorkerResult:
    """Optional callback return. ``None`` from the callback means continue."""

    outcome: WorkerOutcome
    error_class: str | None = None
    detail: str | None = None


class HealthProbe(Protocol):
    """Injectable Mac health source. Tests must not call the network."""

    def __call__(self) -> HealthState: ...


class WorkerCallback(Protocol):
    """Injectable worker. Tests use a fake; B09 will supervise ACP."""

    def __call__(self, task_id: str, *, now: datetime) -> WorkerResult | None: ...


@dataclass(frozen=True, slots=True)
class StartResult:
    """Process-start recovery. Reclaims expired leases only (§12.5 step 2)."""

    now: datetime
    reclaimed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TickResult:
    """One scheduler cycle."""

    now: datetime
    health: HealthState
    reclaimed: tuple[str, ...]
    promoted: tuple[str, ...]
    dispatched: TaskRecord | None
    running_id: str | None
    paused_ids: tuple[str, ...]
    budget_exceeded_ids: tuple[str, ...]
