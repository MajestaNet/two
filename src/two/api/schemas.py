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

"""HTTP schemas for the channel-neutral control API. No I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from two.types import ExecutionProfile, LifecycleState, Mode, WorkflowStage


class TaskBudgets(BaseModel):
    """Budget ceilings copied from the stored manifest."""

    model_config = ConfigDict(extra="forbid")

    time_budget_minutes: int | None = None
    max_model_turns: int | None = None
    max_repair_cycles: int | None = None
    no_progress_limit: int | None = None
    max_changed_lines: int | None = None


class DiffSummary(BaseModel):
    """Diff statistics. Placeholder until the worker records a fingerprint."""

    model_config = ConfigDict(extra="forbid")

    files_changed: int | None = None
    lines_added: int | None = None
    lines_removed: int | None = None
    placeholder: bool = True


class ValidationSummary(BaseModel):
    """Latest independent validation fragment, if any."""

    model_config = ConfigDict(extra="forbid")

    passed: bool | None = None
    gates_run: int = 0
    last_gate: str | None = None
    summary: str | None = None


class QuestionView(BaseModel):
    """Durable question as projected to clients (architecture §8.4)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    stage: str
    status: str
    options: list[Any] = Field(default_factory=list)
    recommendation: str | None = None
    reason: str | None = None


class ApprovalView(BaseModel):
    """Durable approval as projected to clients (architecture §8.4)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    action_class: str
    action_digest: str
    paths: list[str] = Field(default_factory=list)
    status: str


class TaskProjection(BaseModel):
    """Authoritative task view. Clients never query the model for status."""

    model_config = ConfigDict(extra="forbid")

    id: str
    repository: str
    base_ref: str
    objective: str
    acceptance_criteria: list[str]
    mode: Mode
    execution_profile: ExecutionProfile
    lifecycle: LifecycleState
    stage: WorkflowStage
    budgets: TaskBudgets
    plan: dict[str, Any] | None = None
    todos: list[Any] = Field(default_factory=list)
    diff_summary: DiffSummary = Field(default_factory=DiffSummary)
    validation_summary: ValidationSummary = Field(default_factory=ValidationSummary)
    blockers: list[str] = Field(default_factory=list)
    questions: list[QuestionView] = Field(default_factory=list)
    approvals: list[ApprovalView] = Field(default_factory=list)
    worktree_path: str | None = None
    branch: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskMessage(BaseModel):
    """Follow-up message or answer attached to an existing task."""

    model_config = ConfigDict(extra="forbid")

    text: str
    source: str | None = None


class TaskMessageReceipt(BaseModel):
    """Durable acknowledgement after the message event commits."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    event_id: int


class QuestionAskRequest(BaseModel):
    """Ask a durable question. Sets lifecycle ``awaiting_input``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    stage: str
    reason: str
    options: list[Any] = Field(default_factory=list)
    recommendation: str | None = None
    actor: str | None = None


class QuestionAnswerRequest(BaseModel):
    """Answer one stored question. First valid principal wins."""

    model_config = ConfigDict(extra="forbid")

    answer: Any
    actor: str | None = None


class QuestionAnswerResponse(BaseModel):
    """Answer persisted. Duplicates return ``ignored: true``."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    question_id: str
    ignored: bool = False
    event_id: int
    principal: str
    status: str


class ApprovalRequest(BaseModel):
    """Request a scoped approval. Digest is stored at insert and never updated."""

    model_config = ConfigDict(extra="forbid")

    id: str
    action_class: str
    action_digest: str
    paths: list[str] = Field(default_factory=list)


class ApprovalDecideRequest(BaseModel):
    """Approve or reject one stored approval record."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    actor: str | None = None
    comment: str | None = None
    action_digest: str | None = None


class ApprovalDecideResponse(BaseModel):
    """First-writer-wins decision. Duplicates return ``ignored: true``."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    approval_id: str
    decision: Literal["approve", "reject"]
    event_id: int
    ignored: bool = False
    action_digest: str
    principal: str


class TaskReport(BaseModel):
    """Report payload. Full Stage 8 assembly is B10; this is the stable shape."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    lifecycle: LifecycleState
    stage: WorkflowStage
    objective: str
    acceptance_criteria: list[str]
    branch: str | None = None
    worktree_path: str | None = None
    diff_summary: DiffSummary = Field(default_factory=DiffSummary)
    validation_summary: ValidationSummary = Field(default_factory=ValidationSummary)
    assembled: bool = False
    notes: str = "Final report is assembled by the controller (B10); this is a placeholder."


class HealthResponse(BaseModel):
    """Process health for two-api. Not Ollama / Mac inference health."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: Literal["two-api"]
