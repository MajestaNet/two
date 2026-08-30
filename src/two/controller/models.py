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

"""Controller value objects. No I/O. No Slack or Ollama clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from two.context.handoff import ReviewHandoff
from two.manifest import TaskManifest
from two.types import ExecutionProfile, WorkflowStage
from two.validation.policy import DefaultPolicy
from two.validation.results import ValidationResult
from two.worker.models import SessionPlan
from two.workspace.models import Workspace, WorkspaceStatus


class TaskClass(StrEnum):
    """Intake classification (architecture §8.2 Stage 1)."""

    ANALYSIS_ONLY = "analysis_only"
    CODE_CHANGE = "code_change"
    DEPENDENCY_CHANGE = "dependency_change"
    DATA_MIGRATION = "data_migration"
    INFRASTRUCTURE = "infrastructure"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"


class ReasoningEffort(StrEnum):
    """Phase-specific reasoning passed into the worker (architecture §7.1)."""

    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


class FindingSeverity(StrEnum):
    """Fresh-review finding severity. Blocking findings prevent ``complete``."""

    BLOCKING = "blocking"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class BoundBudgets:
    """Ceilings bound at intake. The controller must not silently extend them."""

    active_time_minutes: int
    max_model_turns: int
    max_repair_cycles: int
    no_progress_limit: int
    execution_profile: ExecutionProfile
    manifest_overrode: bool


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    """One reviewer note. ``blocking`` findings send the task back to repair or block."""

    message: str
    severity: FindingSeverity = FindingSeverity.WARNING
    path: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerInstruction:
    """Phase instruction for an injected worker. The controller does not call the model."""

    stage: WorkflowStage
    effort: ReasoningEffort
    prompt: str
    allow_writes: bool
    fresh_session: bool = False
    handoff: ReviewHandoff | None = None
    session_plan: SessionPlan | None = None


@dataclass(frozen=True, slots=True)
class WorkerPhaseResult:
    """Outcome of one worker phase. Model self-reports are ignored for completion."""

    ok: bool = True
    summary: str = ""
    plan: str = ""
    files_named: tuple[str, ...] = ()
    tests_named: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    files_changed: tuple[str, ...] = ()
    wrote_worktree: bool = False
    findings: tuple[ReviewFinding, ...] = ()
    evidence_fingerprint: str | None = None
    usage_turns: int = 1
    trajectory_ref: str | None = None
    session_id: str | None = None
    infrastructure_error: bool = False
    cloud_attempted: bool = False


@dataclass(frozen=True, slots=True)
class IntakeDecision:
    """Result of Stage 1 classification against default policy."""

    task_class: TaskClass
    forbidden_action: str | None = None
    approval_class: str | None = None


class PhaseWorker(Protocol):
    """Injectable worker. Tests use a fake; production later wraps ACP (B09)."""

    def run_phase(
        self,
        task_id: str,
        instruction: WorkerInstruction,
        *,
        now: datetime | None = None,
    ) -> WorkerPhaseResult: ...


class ValidationGate(Protocol):
    """Injectable B04 gates. Tests never run real pytest unless they opt in."""

    def run(
        self,
        workspace: Workspace,
        *,
        manifest: TaskManifest,
        policy: DefaultPolicy | None = None,
    ) -> ValidationResult: ...


class WorkspaceOps(Protocol):
    """Injectable B03 isolation. Tests may fake worktree creation."""

    def create(
        self,
        task_id: str,
        repo_path: str | Path,
        base_ref: str,
        *,
        repo_id: str | None = None,
    ) -> Workspace: ...

    def status(self, workspace: Workspace) -> WorkspaceStatus: ...


class RepositoryLocator(Protocol):
    """Map a manifest ``repository`` id to a canonical checkout path."""

    def locate(self, repository: str) -> Path: ...


@dataclass
class DriveState:
    """In-process counters for one ``drive`` call. Recoverable from events."""

    repair_cycles: int = 0
    model_turns: int = 0
    validation_runs: int = 0
    fingerprints: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    trajectory_refs: list[str] = field(default_factory=list)
    last_validation: ValidationResult | None = None
    last_handoff: ReviewHandoff | None = None
    last_plan: str = ""
    block_after_review: bool = False
    findings: list[ReviewFinding] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
