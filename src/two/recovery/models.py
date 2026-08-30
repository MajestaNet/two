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

"""Startup-recovery report types. No I/O. Architecture §12.5."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from two.runtime.health import HealthState
from two.store.models import TaskRecord


class LastActionClass(StrEnum):
    """Classification of a task's last ledger action (architecture §12.5)."""

    COMPLETED = "completed"
    SAFE_TO_RETRY = "safe_to_retry"
    RECONCILE = "reconcile"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class WorktreeCheck:
    """Worktree verification for one non-terminal task."""

    task_id: str
    ok: bool
    path: str | None
    branch: str | None = None
    base_commit: str | None = None
    diff_fingerprint: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ActionClassification:
    """Last-action class after the B09 ledger recover hook."""

    task_id: str
    action_id: str | None
    classification: LastActionClass


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """One development-host startup recovery (architecture §12.5 steps 1–7)."""

    now: datetime
    schema_version: int
    reclaimed: tuple[str, ...]
    worktrees: tuple[WorktreeCheck, ...]
    actions: tuple[ActionClassification, ...]
    mac_health: HealthState
    harness_ok: bool
    runnable_ids: tuple[str, ...]
    paused_ids: tuple[str, ...]
    event_id: int | None
    event_task_id: str | None


class WorktreeVerifier(Protocol):
    """Injectable worktree check. Tests use a fake directory, not live git."""

    def __call__(self, task: TaskRecord) -> WorktreeCheck: ...


class HarnessProbe(Protocol):
    """Injectable Harness liveness. Tests must not launch DSH."""

    def __call__(self) -> bool: ...
