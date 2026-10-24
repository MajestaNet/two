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

Do not import FastAPI, the store, git, or Ollama here.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from two.types import (
    EdgeKind,
    ErrorCode,
    ExecutionProfile,
    LifecycleState,
    Mode,
    NodeKind,
    NodeStatus,
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
DEFAULT_CONVERSATION_LIMIT = 50
MAX_CONVERSATION_LIMIT = 100
MAX_CONVERSATION_SUMMARY_CHARS = 1000
MAX_PATCH_CHARS = 8000
DEFAULT_STREAM_BACKLOG = 64
DEFAULT_HEALTH_STALE_AFTER_MS = 60_000
HEALTH_COMPONENT_NAMES: tuple[str, ...] = (
    "api",
    "store",
    "scheduler",
    "worker",
    "harness",
    "inference",
    "disk",
)
ConversationKind = Literal[
    "user_message",
    "agent_summary",
    "stage_change",
    "graph_change",
    "question",
    "approval",
    "validation_summary",
    "completion_report",
    "system_notice",
]
HealthStatus = Literal["healthy", "degraded", "unavailable", "unknown"]


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


class GraphNodeView(BaseModel):
    """One work-graph node as projected to clients (ADR 0014)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: NodeKind
    status: NodeStatus
    title: str
    summary: str = ""


class GraphEdgeView(BaseModel):
    """One typed connection as projected to clients (ADR 0014)."""

    model_config = ConfigDict(extra="forbid")

    kind: EdgeKind
    from_id: str
    to_id: str


class GraphView(BaseModel):
    """Persisted work graph. Null until a graph is stored for the task."""

    model_config = ConfigDict(extra="forbid")

    revision: int = 0
    cursor_node_id: str | None = None
    nodes: list[GraphNodeView] = Field(default_factory=list)
    edges: list[GraphEdgeView] = Field(default_factory=list)


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
    revision: int = 1
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
    graph: GraphView | None = None
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
    ``principal`` is an opaque actor id (for example ``cli:local``); adapters fill it.
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
    revision: int | None = None


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


class FieldError(BaseModel):
    """One request-field failure. Never used to carry secrets or host paths."""

    model_config = ConfigDict(extra="forbid")

    field: str
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Envelope alongside FastAPI ``detail`` so existing clients keep working."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorBody
    detail: str | list[Any]
    correlation_id: str | None = None
    field_errors: list[FieldError] | None = None
    retry_after_seconds: int | None = None


class AuthCapabilities(BaseModel):
    """How this caller was authenticated. OIDC is advertised, not implied."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["local_trust", "bearer_token", "edge_client"]
    oidc_available: bool = False
    mobile_ready: bool = False
    edge_available: bool = False


class ClientFeatures(BaseModel):
    """Optional GUI resources. False means not implemented on this server."""

    model_config = ConfigDict(extra="forbid")

    idempotency_keys: bool = True
    etags: bool = True
    conversation: bool = False
    sse: bool = False
    projects: bool = False
    repositories: bool = False
    aggregate_health: bool = False
    queue: bool = False
    graph: bool = True


class SystemCapabilities(BaseModel):
    """``GET /v1/system/capabilities``. Clients feature-detect from this body."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    api_versions: list[str] = Field(default_factory=lambda: ["v1"])
    principal: str
    scopes: list[str]
    allowed_harness_profiles: list[str] = Field(default_factory=list)
    auth: AuthCapabilities
    features: ClientFeatures = Field(default_factory=ClientFeatures)


class VoiceTurnRequest(BaseModel):
    """One spoken turn from a client. Text only. No audio.

    ``self-build`` is accepted by the schema so a stolen or confused client
    is rejected by authorization (403) rather than by a 422. ``chat`` is
    stored and resumed.     ``home-action`` is stored when a local climate or television
    binding is enabled (ADR 0022, ADR 0029).
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4_000)
    profile: Literal["self-build", "home-action", "chat"]


class ClimateReadbackView(BaseModel):
    """Observed climate state. Entity ids and upstream URLs stay off this body."""

    model_config = ConfigDict(extra="forbid")

    zone: str = Field(min_length=1, max_length=64)
    celsius: float | None = None
    setpoint_celsius: float | None = None
    mode: Literal["off", "heat", "cool", "auto"] | None = None
    reachable: bool


class ClimateRequestView(BaseModel):
    """The tool call waiting for an approval digest. No entity id."""

    model_config = ConfigDict(extra="forbid")

    tool: Literal["climate.read", "climate.set_setpoint", "climate.set_mode"]
    zone: str = Field(min_length=1, max_length=64)
    celsius: float | None = None
    mode: Literal["off", "heat", "cool", "auto"] | None = None


class ClimateDecisionRequest(BaseModel):
    """Approve or reject one open climate action. The digest is the whole scope."""

    model_config = ConfigDict(extra="forbid")

    action_digest: str = Field(min_length=1, max_length=80)


class TvReadbackView(BaseModel):
    """Observed television state. Addresses, app ids, and tokens stay off this body."""

    model_config = ConfigDict(extra="forbid")

    set: str = Field(min_length=1, max_length=64)
    power: Literal["on", "off"]
    active_target: str | None = None
    volume: int | None = None
    mute: bool | None = None
    reachable: bool


class TvRequestView(BaseModel):
    """The television call waiting for an approval digest. No address."""

    model_config = ConfigDict(extra="forbid")

    tool: Literal["tv.read", "tv.set_power", "tv.open", "tv.set_volume"]
    set: str = Field(min_length=1, max_length=64)
    power: Literal["on", "off"] | None = None
    target: str | None = None
    level: int | None = None
    mute: bool | None = None
    step: Literal["up", "down"] | None = None


def encode_turn_cursor(seq: int) -> str:
    """Opaque cursor for one chat turn. Encodes ``seq`` and nothing else."""
    if seq < 1:
        raise ValueError("turn seq must be positive")
    raw = base64.urlsafe_b64encode(str(seq).encode("ascii")).decode("ascii")
    return raw.rstrip("=")


class VoiceTurnReceipt(BaseModel):
    """Client-safe result of one ``chat`` or ``home-action`` turn.

    ``reply`` is set only when ``status`` is ``complete``. ``error_code`` is
    set only when ``status`` is ``failed``. ``action_digest`` and
    ``pending_action`` are set only when ``status`` is ``awaiting_approval``.
    ``climate`` is the device read-back on a completed climate action.
    ``tv`` is the device read-back on a completed television action.
    Host paths, session ids, entity ids, and tokens stay off this body.
    """

    model_config = ConfigDict(extra="forbid")

    turn_id: str = Field(min_length=1)
    profile: Literal["chat", "home-action"]
    status: Literal["queued", "running", "awaiting_approval", "complete", "failed"]
    reply: str | None = Field(default=None, min_length=1, max_length=4_000)
    error_code: ErrorCode | None = None
    climate: ClimateReadbackView | None = None
    tv: TvReadbackView | None = None
    action_digest: str | None = None
    pending_action: ClimateRequestView | None = None
    pending_tv: TvRequestView | None = None
    cursor: str = Field(min_length=1)
    revision: int = Field(ge=1)

    @model_validator(mode="after")
    def _terminal_fields(self) -> Self:
        if self.status == "complete":
            if self.reply is None or self.error_code is not None:
                raise ValueError("complete receipt has reply and no error_code")
            if self.action_digest is not None or self.pending_action is not None:
                raise ValueError("complete receipt has no pending action")
            if self.pending_tv is not None:
                raise ValueError("complete receipt has no pending action")
            if self.climate is not None and self.tv is not None:
                raise ValueError("complete receipt has one device read-back")
        elif self.status == "failed":
            if self.error_code is None or self.reply is not None:
                raise ValueError("failed receipt has error_code and no reply")
            if (
                self.climate is not None
                or self.tv is not None
                or self.action_digest is not None
                or self.pending_action is not None
                or self.pending_tv is not None
            ):
                raise ValueError("failed receipt has no device result")
        elif self.status == "awaiting_approval":
            if (
                self.reply is not None
                or self.error_code is not None
                or self.climate is not None
                or self.tv is not None
            ):
                raise ValueError("awaiting approval has no reply or device result")
            climate_pending = self.pending_action is not None
            tv_pending = self.pending_tv is not None
            if self.action_digest is None or climate_pending == tv_pending:
                raise ValueError("awaiting approval names the digest and one action")
        elif self.reply is not None or self.error_code is not None:
            raise ValueError("reply and error_code are terminal")
        elif (
            self.climate is not None
            or self.tv is not None
            or self.action_digest is not None
            or self.pending_action is not None
            or self.pending_tv is not None
        ):
            raise ValueError("queued and running receipts omit device results")
        return self


def voice_turn_receipt(
    *,
    turn_id: str,
    status: str,
    reply: str | None,
    error_code: str | None,
    seq: int,
    revision: int,
    profile: str = "chat",
    climate: ClimateReadbackView | None = None,
    tv: TvReadbackView | None = None,
    action_digest: str | None = None,
    pending_action: ClimateRequestView | None = None,
    pending_tv: TvRequestView | None = None,
) -> VoiceTurnReceipt:
    """Build a receipt. Non-terminal rows never expose reply or error_code."""
    shown_reply = reply if status == "complete" else None
    shown_error = error_code if status == "failed" else None
    shown_climate = climate if status == "complete" else None
    shown_tv = tv if status == "complete" else None
    shown_digest = action_digest if status == "awaiting_approval" else None
    shown_pending = pending_action if status == "awaiting_approval" else None
    shown_pending_tv = pending_tv if status == "awaiting_approval" else None
    if shown_reply is not None and len(shown_reply) > 4000:
        shown_reply = shown_reply[:4000]
    return VoiceTurnReceipt.model_validate(
        {
            "turn_id": turn_id,
            "profile": profile,
            "status": status,
            "reply": shown_reply,
            "error_code": shown_error,
            "climate": None if shown_climate is None else shown_climate.model_dump(mode="json"),
            "tv": None if shown_tv is None else shown_tv.model_dump(mode="json"),
            "action_digest": shown_digest,
            "pending_action": (
                None if shown_pending is None else shown_pending.model_dump(mode="json")
            ),
            "pending_tv": (
                None if shown_pending_tv is None else shown_pending_tv.model_dump(mode="json")
            ),
            "cursor": encode_turn_cursor(seq),
            "revision": revision,
        }
    )


class ConversationItem(BaseModel):
    """One client-safe conversation row. Never a raw Harness trajectory."""

    model_config = ConfigDict(extra="forbid")

    cursor: str
    seq: int
    kind: ConversationKind
    created_at: datetime
    summary: str
    task_id: str
    revision: int | None = None
    resource_id: str | None = None
    stage: str | None = None
    status: str | None = None


class ConversationPage(BaseModel):
    """``GET /v1/tasks/{id}/conversation``. Durable cursor pagination."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    task_id: str
    items: list[ConversationItem]
    next_cursor: str | None = None
    limit: int


class StreamChange(BaseModel):
    """One SSE payload. Clients refetch snapshots; this is not token streaming."""

    model_config = ConfigDict(extra="forbid")

    cursor: str
    task_id: str | None = None
    kind: str
    revision: int | None = None
    summary: str
    created_at: datetime | None = None


class HealthObservation(BaseModel):
    """Injected observed component state. Missing observations stay ``unknown``."""

    model_config = ConfigDict(extra="forbid")

    status: HealthStatus
    observed_at: datetime
    detail: str | None = None


class ComponentHealth(BaseModel):
    """One aggregate-health component. Stale observations are never ``healthy``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: HealthStatus
    observed_at: datetime | None = None
    observation_age_ms: int | None = None
    stale: bool = False
    detail: str | None = None


class SystemHealth(BaseModel):
    """``GET /v1/system/health``. Authenticated aggregate health, not ``/health``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    status: HealthStatus
    observed_at: datetime
    stale: bool = False
    components: list[ComponentHealth]


class QueueSlotView(BaseModel):
    """One redacted queue row. No objective, worktree, or host path."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    lifecycle: LifecycleState
    stage: WorkflowStage
    retry_count: int = 0
    next_attempt_at: datetime | None = None
    lease_age_ms: int | None = None
    lease_fresh: bool | None = None


class SystemQueue(BaseModel):
    """``GET /v1/system/queue``. Slot occupancy without source-bearing fields."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    depth: int
    active_task_id: str | None = None
    items: list[QueueSlotView]
    observed_at: datetime


class RepositoryNetworkView(BaseModel):
    """Redacted network flags. No remotes, credentials, or bind addresses."""

    model_config = ConfigDict(extra="forbid")

    allow_package_downloads: bool
    allow_external_mutations: bool


class RepositorySummary(BaseModel):
    """``GET /v1/repositories`` row. Commands and host paths are omitted."""

    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    language: str
    validation_profile: str
    readiness: Literal["configured", "unknown"] = "configured"
    secret_scan: bool = False
    gate_names: list[str] = Field(default_factory=list)
    config_digest: str | None = None


class RepositoryView(BaseModel):
    """``GET /v1/repositories/{id}``. Repo-relative patterns only."""

    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    language: str
    validation_profile: str
    secret_scan: bool = False
    network: RepositoryNetworkView
    gate_names: list[str] = Field(default_factory=list)
    allowed_path_patterns: list[str] = Field(default_factory=list)
    forbidden_path_patterns: list[str] = Field(default_factory=list)
    config_digest: str
    readiness: Literal["configured", "unknown"] = "configured"
    revision: int = 1
    active_candidate_revision: int | None = None


class RepositoryListResponse(BaseModel):
    """``GET /v1/repositories``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    repositories: list[RepositorySummary]
    limit: int


class ProjectSummary(BaseModel):
    """One project row from the persisted project store."""

    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    repository_ids: list[str] = Field(default_factory=list)
    active_task_count: int = 0
    revision: int = 1


class ProjectListResponse(BaseModel):
    """``GET /v1/projects``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    projects: list[ProjectSummary]
    limit: int


class ProjectCreateRequest(BaseModel):
    """``POST /v1/projects``. Typed non-secret fields only."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    repository_ids: list[str] = Field(default_factory=list)
    default_repository: str | None = None
    default_base_ref: str | None = None
    default_mode: Mode | None = None
    default_execution_profile: ExecutionProfile | None = None
    labels: list[str] = Field(default_factory=list)
    acceptance_criteria_templates: list[str] = Field(default_factory=list)


class ProjectConfigCandidateRequest(BaseModel):
    """``POST /v1/projects/{id}/config-candidates``. Partial typed overlay."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    repository_ids: list[str] | None = None
    default_repository: str | None = None
    default_base_ref: str | None = None
    default_mode: Mode | None = None
    default_execution_profile: ExecutionProfile | None = None
    labels: list[str] | None = None
    acceptance_criteria_templates: list[str] | None = None


class ProjectView(BaseModel):
    """``GET /v1/projects/{id}``. No secrets, host paths, or commands."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    id: str
    display_name: str
    description: str = ""
    repository_ids: list[str] = Field(default_factory=list)
    default_repository: str | None = None
    default_base_ref: str | None = None
    default_mode: Mode | None = None
    default_execution_profile: ExecutionProfile | None = None
    labels: list[str] = Field(default_factory=list)
    acceptance_criteria_templates: list[str] = Field(default_factory=list)
    active_candidate_revision: int | None = None
    revision: int = 1
    config_digest: str | None = None
    created_at: datetime
    updated_at: datetime


class RepositoryConfigCandidateRequest(BaseModel):
    """``POST /v1/repositories/{id}/config-candidates``. Gate names, not commands."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    language: str | None = Field(default=None, min_length=1, max_length=64)
    validation_profile: str | None = Field(default=None, min_length=1, max_length=64)
    secret_scan: bool | None = None
    gate_names: list[str] | None = None
    allowed_path_patterns: list[str] | None = None
    forbidden_path_patterns: list[str] | None = None
    network: RepositoryNetworkView | None = None


class ConfigDiffEntry(BaseModel):
    """One redacted field change. Values never include commands or secrets."""

    model_config = ConfigDict(extra="forbid")

    field: str
    before: Any = None
    after: Any = None


class ConfigCandidateView(BaseModel):
    """Immutable candidate snapshot. POST does not activate."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    subject_kind: Literal["repository", "project"]
    subject_id: str
    revision: int
    digest: str
    risk_class: Literal["display", "capability"]
    status: Literal["pending", "activated"]
    field_errors: list[FieldError] = Field(default_factory=list)
    redacted_diff: list[ConfigDiffEntry] = Field(default_factory=list)
    created_at: datetime


class ConfigApprovalView(BaseModel):
    """Digest-scoped config approval. First writer wins; silence is never approval."""

    model_config = ConfigDict(extra="forbid")

    id: str
    action_class: str
    action_digest: str
    status: Literal["open", "approved", "rejected"]
    created_at: datetime


class ConfigActivateRequest(BaseModel):
    """``POST …/config-candidates/{revision}/activate``."""

    model_config = ConfigDict(extra="forbid")

    action_digest: str | None = None
    decision: Literal["approve", "reject"] | None = None
    principal: str | None = None
    actor: str | None = None


class ConfigActivateResponse(BaseModel):
    """Activation result, or a required digest-scoped approval."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    activated: bool
    approval_required: bool = False
    subject_kind: Literal["repository", "project"]
    subject_id: str
    candidate_revision: int
    resource_revision: int
    digest: str
    risk_class: Literal["display", "capability"]
    approval: ConfigApprovalView | None = None


class TaskDiffView(BaseModel):
    """Bounded diff projection. Paths and patch require ``source:read``."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    summary: DiffSummary
    patch: str | None = None
    source_included: bool = False


class ArtifactMetadata(BaseModel):
    """Safe artifact descriptor addressed by a server id, never a host path."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    filename: str
    size_bytes: int


class ArtifactListResponse(BaseModel):
    """``GET /v1/tasks/{id}/artifacts``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    task_id: str
    artifacts: list[ArtifactMetadata]


class ArtifactContent(BaseModel):
    """``GET /v1/tasks/{id}/artifacts/{artifact_id}``. Content is optional."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PROJECTION_SCHEMA_VERSION
    task_id: str
    artifact: ArtifactMetadata
    content: str | None = None
    truncated: bool = False
    source_included: bool = False
