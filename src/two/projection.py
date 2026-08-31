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

"""Channel-neutral task projection and /v1 request bodies. No I/O.

This is the client contract for the control API, CLI (B13), optional web,
and any messenger adapter (B14). Field names match architecture §6.3.H.
``schema_version`` is additive: new optional fields may appear on /v1;
breaking changes require /v2 and an ADR.

Do not import FastAPI, the store, git, Slack, or Ollama here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from two.types import (
    ErrorCode,
    ExecutionProfile,
    LifecycleState,
    Mode,
    TodoStatus,
    WorkflowStage,
)

PROJECTION_SCHEMA_VERSION = 1
MESSAGE_TEXT_MAX_CHARS = 16384
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 100
DEFAULT_EVENT_LIMIT = 100
MAX_EVENT_LIMIT = 500
MAX_DIFF_PATHS = 50


class TaskBudgets(BaseModel):
    """Budget ceilings plus elapsed clocks. Clocks stay 0 until the scheduler fills them."""

    model_config = ConfigDict(extra="forbid")

    execution_profile: ExecutionProfile | None = None
    time_budget_minutes: int | None = None
    max_model_turns: int | None = None
    max_repair_cycles: int | None = None
    no_progress_limit: int | None = None
    max_changed_lines: int | None = None
    active_seconds: int = 0
    wall_seconds: int = 0
    remaining_active_seconds: int | None = None


class DiffSummary(BaseModel):
    """Diff statistics. Never the full patch. ``placeholder`` is true until a fingerprint exists."""

    model_config = ConfigDict(extra="forbid")

    files_changed: int | None = None
    lines_added: int | None = None
    lines_removed: int | None = None
    paths: list[str] = Field(default_factory=list)
    placeholder: bool = True


class ValidationGateView(BaseModel):
    """One independent validation gate. Full logs stay on disk."""

    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    exit_code: int | None = None
    summary: str = ""


class ValidationSummary(BaseModel):
    """Latest independent validation fragment, if any."""

    model_config = ConfigDict(extra="forbid")

    passed: bool | None = None
    gates_run: int = 0
    last_gate: str | None = None
    summary: str | None = None
    gates: list[ValidationGateView] = Field(default_factory=list)


class TodoItem(BaseModel):
    """One plan/todo row. Unknown extra keys are rejected on write."""

    model_config = ConfigDict(extra="forbid")

    id: str
    content: str
    status: TodoStatus = TodoStatus.PENDING


class QuestionView(BaseModel):
    """Durable question as projected to clients (architecture §8.4)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    stage: str
    status: str
    options: list[Any] = Field(default_factory=list)
    recommendation: str | None = None
    reason: str | None = None
    actor: str | None = None
    created_at: datetime | None = None


class ApprovalView(BaseModel):
    """Durable approval as projected to clients (architecture §8.4)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    action_class: str
    action_digest: str
    paths: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime | None = None


class TaskProjection(BaseModel):
    """Authoritative task view. Clients never query the model for status."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    id: str
    repository: str
    base_ref: str
    objective: str
    acceptance_criteria: list[str]
    mode: Mode
    execution_profile: ExecutionProfile
    cloud_allowed: bool = False
    lifecycle: LifecycleState
    stage: WorkflowStage
    budgets: TaskBudgets
    plan: dict[str, Any] | None = None
    todos: list[TodoItem] = Field(default_factory=list)
    diff_summary: DiffSummary = Field(default_factory=DiffSummary)
    validation_summary: ValidationSummary = Field(default_factory=ValidationSummary)
    blockers: list[str] = Field(default_factory=list)
    questions: list[QuestionView] = Field(default_factory=list)
    approvals: list[ApprovalView] = Field(default_factory=list)
    worktree_path: str | None = None
    branch: str | None = None
    base_commit: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    """``GET /v1/tasks`` page. Oldest-first. Additive cursor can land later on /v1."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    tasks: list[TaskProjection]
    limit: int


class EventView(BaseModel):
    """One append-only event. ``type`` is an ``EventType`` value or an alias."""

    model_config = ConfigDict(extra="forbid")

    seq: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


class EventListResponse(BaseModel):
    """``GET /v1/tasks/{id}/events``. Tail of the log, not a second state store."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    task_id: str
    events: list[EventView]
    limit: int


class TaskMessage(BaseModel):
    """Follow-up message or answer attached to an existing task.

    Persisted as event type ``task.message``. There is no messages table.
    ``principal`` is an opaque actor id (CLI user, ``slack:U…``); adapters fill it.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MESSAGE_TEXT_MAX_CHARS)
    source: str | None = None
    principal: str | None = None


class TaskMessageReceipt(BaseModel):
    """Durable acknowledgement after the message event commits."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    event_id: int


class TaskControlRequest(BaseModel):
    """Optional body for pause / resume / cancel. Empty object is valid."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None
    principal: str | None = None


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
    action_digest: str = Field(min_length=1)


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
    """Report payload assembled by the controller (B10). Placeholder until a report event exists."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    lifecycle: LifecycleState
    stage: WorkflowStage
    objective: str
    acceptance_criteria: list[str]
    branch: str | None = None
    worktree_path: str | None = None
    base_commit: str | None = None
    diff_summary: DiffSummary = Field(default_factory=DiffSummary)
    validation_summary: ValidationSummary = Field(default_factory=ValidationSummary)
    assembled: bool = False
    notes: str = "Final report is assembled by the controller (B10); this is a placeholder."


class HealthResponse(BaseModel):
    """Process health for two-api. Not Ollama / Mac inference health."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    service: Literal["two-api"]
    store: Literal["ok", "error"] = "ok"


class ErrorBody(BaseModel):
    """Machine-readable error. ``code`` is an ``ErrorCode`` value."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str


class ErrorResponse(BaseModel):
    """Envelope alongside FastAPI ``detail`` so existing clients keep working."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorBody
    detail: str | list[Any]
