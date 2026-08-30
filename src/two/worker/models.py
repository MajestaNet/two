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

"""Worker value objects. No I/O."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from two.worker.timeouts import (
    CANCEL_COOPERATIVE_SECONDS,
    CANCEL_GRACE_SECONDS,
    CHILD_HEARTBEAT_STALE_SECONDS,
    CONNECT_TIMEOUT_SECONDS,
    INFERENCE_TIMEOUT_SECONDS,
    STREAM_LIVENESS_SECONDS,
)


class SessionMode(StrEnum):
    """Resume a valid DSH session or start fresh with the same task id."""

    RESUME = "resume"
    FRESH = "fresh"


class RepairAction(StrEnum):
    """Tool-call repair ladder (architecture §14)."""

    ACCEPT = "accept"
    SCHEMA_REPAIR = "schema_repair"
    FRESH_TURN = "fresh_turn"
    ESCALATE = "escalate"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class SessionPlan:
    """How to attach the ACP child. Task identity is always preserved."""

    mode: SessionMode
    task_id: str
    session_id: str | None
    prompt: str


@dataclass(frozen=True, slots=True)
class RepairDecision:
    """Next step after invalid or repeated tool JSON."""

    action: RepairAction
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ChildConfig:
    """Timeouts for one supervised ACP child. Tests override grace/liveness."""

    connect_timeout_seconds: float = CONNECT_TIMEOUT_SECONDS
    inference_timeout_seconds: float = INFERENCE_TIMEOUT_SECONDS
    stream_liveness_seconds: float = STREAM_LIVENESS_SECONDS
    heartbeat_stale_seconds: float = CHILD_HEARTBEAT_STALE_SECONDS
    cooperative_seconds: float = CANCEL_COOPERATIVE_SECONDS
    grace_seconds: float = CANCEL_GRACE_SECONDS


@dataclass(frozen=True, slots=True)
class CancelOutcome:
    """Result of bounded cancellation. The worktree is never discarded."""

    cooperative: bool
    killed: bool
    worktree_retained: bool
    returncode: int | None = None
