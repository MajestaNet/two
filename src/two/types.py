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

"""Shared enumerations. No I/O."""

from enum import StrEnum


class LifecycleState(StrEnum):
    """Coarse durable task lifetime. See docs/architecture.md §6.3.G."""

    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    RETRY_WAIT = "retry_wait"
    PAUSED = "paused"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStage(StrEnum):
    """Workflow stage inside a running task. See docs/architecture.md §8.2."""

    INTAKE = "intake"
    ISOLATE = "isolate"
    INSPECT = "inspect"
    PLAN = "plan"
    IMPLEMENT = "implement"
    VALIDATE = "validate"
    REPAIR = "repair"
    REVIEW = "review"
    COMPLETE = "complete"
    BLOCKED = "blocked"


class Mode(StrEnum):
    """Automation mode. See docs/architecture.md §9."""

    REVIEW_ONLY = "review-only"
    INTERACTIVE = "interactive"
    WORKSPACE_AUTO = "workspace-auto"
    UNATTENDED = "unattended"


class ExecutionProfile(StrEnum):
    """Budget profile. See docs/architecture.md §6.3.G."""

    STANDARD = "standard"
    OVERNIGHT = "overnight"


class OnHumanInputRequired(StrEnum):
    """What happens when the controller needs a human."""

    PAUSE = "pause"
    BLOCK = "block"


class InferenceProfileId(StrEnum):
    """Named Mac/Ollama profiles. 24 GB / 16K is the default, not a ceiling."""

    M24_QWEN38_16K = "m24-qwen38-16k"
    M24_QWEN38_32K = "m24-qwen38-32k"
    M36_QWEN38_32K = "m36-qwen38-32k"
    M48_QWEN38_64K = "m48-qwen38-64k"
    M64_QWEN38_PLUS = "m64-qwen38-plus"
    CUSTOM = "custom"


class DeploymentTopologyId(StrEnum):
    """Physical placement. Logical inference/execution split always holds."""

    SPLIT = "split"
    COLOCATED = "colocated"


class TodoStatus(StrEnum):
    """Todo item status as projected to clients."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ErrorCode(StrEnum):
    """Stable ``error.code`` values on /v1 responses. Additive only."""

    DUPLICATE_TASK = "duplicate_task"
    TASK_NOT_FOUND = "task_not_found"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    VALIDATION_ERROR = "validation_error"
    CONFLICT_LIFECYCLE = "conflict_lifecycle"
    STALE_DIGEST = "stale_digest"
    DIGEST_REQUIRED = "digest_required"
    OPEN_INPUT = "open_input"
    NOT_RESUMABLE = "not_resumable"
    INTERNAL = "internal"


class EventType(StrEnum):
    """Append-only controller event types stored in SQLite ``events.type``.

    Values are the strings already persisted by B07–B12. New types MUST be
    namespaced ``domain.verb`` (for example ``task.created``). Un-namespaced
    historical strings (``dispatched``, ``plan``) stay valid forever so
    existing rows keep projecting. See ``EVENT_TYPE_ALIASES``.
    """

    TASK_CREATED = "task.created"
    TASK_MESSAGE = "task.message"
    TASK_PLAN = "task.plan"
    TASK_TODOS = "task.todos"
    TASK_DIFF = "task.diff"
    TASK_VALIDATION = "task.validation"
    TASK_BLOCKER = "task.blocker"
    TASK_PAUSED = "task.paused"
    TASK_RESUMED = "task.resumed"
    TASK_CANCELLED = "task.cancelled"
    TASK_INPUT_TIMEOUT = "task.input_timeout"
    WORKFLOW_STAGE = "workflow.stage"
    WORKFLOW_INTAKE = "workflow.intake"
    WORKFLOW_ISOLATE = "workflow.isolate"
    WORKFLOW_INSPECT = "workflow.inspect"
    WORKFLOW_IMPLEMENT = "workflow.implement"
    WORKFLOW_REPAIR = "workflow.repair"
    WORKFLOW_REVIEW = "workflow.review"
    WORKFLOW_REPORT = "workflow.report"
    WORKFLOW_COMPLETE = "workflow.complete"
    WORKFLOW_BLOCKED = "workflow.blocked"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_NO_PROGRESS = "workflow.no_progress"
    WORKFLOW_WORKER = "workflow.worker"
    QUESTION_ASKED = "question.asked"
    QUESTION_ANSWERED = "question.answered"
    QUESTION_EXPIRED = "question.expired"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDE = "approval.decide"
    APPROVAL_EXPIRED = "approval.expired"
    SCHEDULER_DISPATCHED = "dispatched"
    LEASE_RECLAIMED = "lease_reclaimed"
    SLOT_RELEASED = "slot_released"
    MAC_UNAVAILABLE = "mac_unavailable"
    MAC_DEGRADED = "mac_degraded"
    RETRY_WAIT = "retry_wait"
    RETRY_READY = "retry_ready"
    RETRY_EXHAUSTED = "retry_exhausted"
    BUDGET_EXCEEDED = "budget_exceeded"
    ACP_CHILD_STARTED = "acp_child_started"
    ACP_CHILD_EXITED = "acp_child_exited"
    ACP_CHILD_CANCELLED = "acp_child_cancelled"
    ACTION_RECONCILE = "action_reconcile"
    ACP_SESSION_RESUME = "acp_session_resume"
    ACP_SESSION_FRESH = "acp_session_fresh"
    TOOL_CALL_REPAIR = "tool_call_repair"
    TOOL_CALL_ESCALATE = "tool_call_escalate"
    IDENTICAL_TOOL_CALL_STOP = "identical_tool_call_stop"
    STARTUP_RECOVERY = "startup_recovery"


# Un-namespaced strings accepted when *reading* events written before the
# catalog. Writers should emit ``EventType`` values, not these aliases.
EVENT_TYPE_ALIASES: frozenset[str] = frozenset(
    {
        "plan",
        "todos",
        "blocker",
        "diff",
        "validation",
    }
)


def is_known_event_type(value: str) -> bool:
    """True if ``value`` is an ``EventType`` or a documented read alias."""
    if value in EVENT_TYPE_ALIASES:
        return True
    try:
        EventType(value)
    except ValueError:
        return False
    return True
