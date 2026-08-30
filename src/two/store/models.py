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

"""Store row types. No I/O. Architecture enums stay in ``two.types``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from two.manifest import TaskManifest
from two.types import ExecutionProfile, LifecycleState, Mode, WorkflowStage


class ActionStatus(StrEnum):
    """Action-ledger status. See docs/architecture.md §6.3.G and §12.5."""

    RECORDED = "recorded"
    EXECUTED = "executed"
    RECONCILE = "reconcile"


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """Persisted task queue row plus denormalized manifest fields."""

    id: str
    repository: str
    base_ref: str
    objective: str
    manifest: TaskManifest
    lifecycle: LifecycleState
    stage: WorkflowStage
    mode: Mode
    execution_profile: ExecutionProfile
    worktree_path: str | None
    branch: str | None
    base_commit: str | None
    time_budget_minutes: int | None
    max_model_turns: int | None
    max_repair_cycles: int | None
    no_progress_limit: int | None
    cloud_allowed: bool
    created_at: datetime
    updated_at: datetime
    next_attempt_at: datetime | None = None
    retry_count: int = 0
    active_elapsed_ms: int = 0
    active_started_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LeaseRecord:
    """Time-limited worker lease. Reclaim only when ``expires_at < now``."""

    task_id: str
    worker_id: str
    expires_at: datetime
    heartbeat_at: datetime


@dataclass(frozen=True, slots=True)
class EventRecord:
    """Append-only controller event. ``seq`` is monotonic per task."""

    id: int
    task_id: str
    seq: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class QuestionRecord:
    """Durable question. Resolution policy is B11, not the store."""

    id: str
    task_id: str
    stage: str
    status: str
    options: list[Any]
    recommendation: str | None
    actor: str | None
    reason: str | None
    created_at: datetime
    resolved_at: datetime | None
    resolver: str | None


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """Durable approval. Digest is immutable once stored."""

    id: str
    task_id: str
    action_class: str
    action_digest: str
    paths: list[str]
    status: str
    created_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class ChannelBinding:
    """Task-to-channel thread binding. ``source_event_id`` is unique for dedup."""

    task_id: str
    channel: str
    thread_id: str
    source_event_id: str


@dataclass(frozen=True, slots=True)
class ActionRecord:
    """Action ledger row. Intent is recorded before execution (architecture §12.5)."""

    action_id: str
    task_id: str
    intent: dict[str, Any]
    status: ActionStatus
    result: dict[str, Any] | None
    diff_fingerprint: str | None
    created_at: datetime
    completed_at: datetime | None
