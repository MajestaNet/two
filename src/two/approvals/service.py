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

"""Durable questions, approvals, and cooperative pause/resume/cancel.

Silence is never approval (architecture §8.4). The API and CLI call this
module; it does not talk to git, Slack, or the model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from two.approvals.digest import compute_action_digest
from two.approvals.errors import (
    NotResumableError,
    PrincipalRequiredError,
    StaleDigestError,
    TerminalLifecycleError,
    UnsafeTimeoutDefaultError,
)
from two.store import ApprovalNotFoundError, QuestionNotFoundError, Store, TaskNotFoundError
from two.store.models import ApprovalRecord, QuestionRecord, TaskRecord
from two.types import LifecycleState, OnHumanInputRequired, WorkflowStage

DEFAULT_PRINCIPAL = "local"
_SAFE_TIMEOUT_DEFAULTS = frozenset({"none", "pause", "block"})
_TERMINAL = frozenset(
    {
        LifecycleState.COMPLETE,
        LifecycleState.FAILED,
        LifecycleState.CANCELLED,
    }
)
_RESUMABLE = frozenset({LifecycleState.PAUSED, LifecycleState.AWAITING_INPUT})
_DECIDED_APPROVAL = frozenset({"approved", "rejected"})


@dataclass(frozen=True, slots=True)
class AnswerResult:
    """Outcome of answering a question. Duplicates set ``ignored``."""

    question: QuestionRecord
    event_id: int
    ignored: bool
    principal: str


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """Outcome of deciding an approval. Duplicates set ``ignored``."""

    approval: ApprovalRecord
    event_id: int
    ignored: bool
    decision: Literal["approve", "reject"]
    principal: str


def normalize_principal(principal: str | None) -> str:
    """Return a non-empty principal id. Empty becomes the local user."""
    if principal is None:
        return DEFAULT_PRINCIPAL
    stripped = principal.strip()
    if stripped == "":
        return DEFAULT_PRINCIPAL
    return stripped


def require_principal(principal: str | None) -> str:
    """Normalize, then reject a still-empty id."""
    value = normalize_principal(principal)
    if value == "":
        raise PrincipalRequiredError("principal id is required")
    return value


def ask_question(
    store: Store,
    task_id: str,
    *,
    question_id: str,
    stage: WorkflowStage | str,
    options: Sequence[object],
    reason: str | None = None,
    recommendation: str | None = None,
    actor: str | None = None,
    now: datetime | None = None,
) -> QuestionRecord:
    """Insert a question, persist ``awaiting_input``, and append an event."""
    task = _require_task(store, task_id)
    _refuse_terminal(task, "ask a question")
    record = store.insert_question(
        question_id,
        task_id,
        stage=stage,
        options=options,
        recommendation=recommendation,
        actor=actor,
        reason=reason,
        now=now,
    )
    if task.lifecycle is not LifecycleState.AWAITING_INPUT:
        store.update_task(task_id, lifecycle=LifecycleState.AWAITING_INPUT, now=now)
    payload: dict[str, object] = {
        "question_id": question_id,
        "stage": record.stage,
        "status": record.status,
        "options": list(record.options),
        "lifecycle": LifecycleState.AWAITING_INPUT.value,
    }
    if reason is not None:
        payload["reason"] = reason
    if recommendation is not None:
        payload["recommendation"] = recommendation
    if actor is not None:
        payload["actor"] = actor
    store.append_event(task_id, "question.asked", payload, now=now)
    return record


def answer_question(
    store: Store,
    task_id: str,
    question_id: str,
    *,
    answer: object,
    principal: str | None = None,
    now: datetime | None = None,
) -> AnswerResult:
    """First valid authorized principal wins. Duplicates are ignored."""
    _require_task(store, task_id)
    question = store.get_question(question_id)
    if question is None or question.task_id != task_id:
        raise QuestionNotFoundError(f"unknown question: {question_id}")
    actor = require_principal(principal)
    record, first = store.resolve_question(
        question_id,
        status="answered",
        resolver=actor,
        now=now,
    )
    payload: dict[str, object] = {
        "question_id": question_id,
        "answer": answer,
        "principal": actor,
        "ignored": not first,
    }
    event_id = store.append_event(task_id, "question.answered", payload, now=now)
    return AnswerResult(question=record, event_id=event_id, ignored=not first, principal=actor)


def request_approval(
    store: Store,
    task_id: str,
    *,
    approval_id: str,
    action_class: str,
    paths: Sequence[str] = (),
    action_digest: str | None = None,
    target: str | None = None,
    payload: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> ApprovalRecord:
    """Insert an approval with an immutable digest and set ``awaiting_input``."""
    task = _require_task(store, task_id)
    _refuse_terminal(task, "request an approval")
    digest = action_digest or compute_action_digest(
        action_class=action_class,
        paths=paths,
        target=target,
        payload=payload,
    )
    record = store.insert_approval(
        approval_id,
        task_id,
        action_class=action_class,
        action_digest=digest,
        paths=paths,
        now=now,
    )
    if task.lifecycle is not LifecycleState.AWAITING_INPUT:
        store.update_task(task_id, lifecycle=LifecycleState.AWAITING_INPUT, now=now)
    event_payload: dict[str, object] = {
        "approval_id": approval_id,
        "action_class": action_class,
        "action_digest": digest,
        "paths": list(paths),
        "lifecycle": LifecycleState.AWAITING_INPUT.value,
    }
    if target is not None:
        event_payload["target"] = target
    store.append_event(task_id, "approval.requested", event_payload, now=now)
    return record


def decide_approval(
    store: Store,
    task_id: str,
    approval_id: str,
    *,
    decision: Literal["approve", "reject"],
    principal: str | None = None,
    action_digest: str | None = None,
    comment: str | None = None,
    now: datetime | None = None,
) -> DecisionResult:
    """First valid authorized principal wins. Stale digests are rejected.

    Duplicate decides against the stored digest acknowledge and ignore
    (``ignored=True``). They do not change the first writer's decision.
    """
    _require_task(store, task_id)
    approval = store.get_approval(approval_id)
    if approval is None or approval.task_id != task_id:
        raise ApprovalNotFoundError(f"unknown approval: {approval_id}")
    if action_digest is not None and action_digest != approval.action_digest:
        raise StaleDigestError(expected=approval.action_digest, offered=action_digest)
    actor = require_principal(principal)
    new_status = "approved" if decision == "approve" else "rejected"
    record, first = store.resolve_approval(approval_id, status=new_status, now=now)
    effective: Literal["approve", "reject"]
    if first:
        effective = decision
    elif record.status == "approved":
        effective = "approve"
    elif record.status == "rejected":
        effective = "reject"
    else:
        effective = decision
    payload: dict[str, object] = {
        "approval_id": approval_id,
        "decision": effective if not first else decision,
        "requested_decision": decision,
        "action_digest": approval.action_digest,
        "principal": actor,
        "ignored": not first,
    }
    if comment is not None:
        payload["comment"] = comment
    event_id = store.append_event(task_id, "approval.decide", payload, now=now)
    return DecisionResult(
        approval=record,
        event_id=event_id,
        ignored=not first,
        decision=effective,
        principal=actor,
    )


def apply_input_timeout(
    store: Store,
    task_id: str,
    *,
    now: datetime | None = None,
    deadline: datetime | None = None,
    safe_default: str | None = None,
) -> TaskRecord:
    """Expire outstanding input when a deadline has passed.

    Silence never implies approval. With no deadline the wait continues
    indefinitely (``awaiting_input`` / ``paused`` stay as they are). After a
    deadline the records expire and the task pauses, or blocks when the
    manifest says ``on_human_input_required: block``. ``safe_default`` may
    only name a non-side-effect (``none`` / ``pause`` / ``block``).
    """
    task = _require_task(store, task_id)
    if task.lifecycle in _TERMINAL:
        return task
    if safe_default is not None and safe_default not in _SAFE_TIMEOUT_DEFAULTS:
        raise UnsafeTimeoutDefaultError(
            f"timeout default {safe_default!r} is not a safe non-side-effect; "
            "silence is never approval"
        )
    if deadline is None or (now is not None and now < deadline):
        return task
    questions, approvals = store.expire_open_input(task_id, resolver="timeout", now=now)
    for question in questions:
        store.append_event(
            task_id,
            "question.expired",
            {"question_id": question.id, "status": "expired", "approved": False},
            now=now,
        )
    for approval in approvals:
        store.append_event(
            task_id,
            "approval.expired",
            {
                "approval_id": approval.id,
                "action_digest": approval.action_digest,
                "status": "expired",
                "approved": False,
            },
            now=now,
        )
    outcome = _timeout_lifecycle(task, safe_default)
    if task.lifecycle is not outcome:
        task = store.update_task(task_id, lifecycle=outcome, now=now)
        store.append_event(
            task_id,
            "task.input_timeout",
            {
                "lifecycle": outcome.value,
                "approved": False,
                "worktree_path": task.worktree_path,
            },
            now=now,
        )
    return task


def pause_task(
    store: Store,
    task_id: str,
    *,
    principal: str | None = None,
    now: datetime | None = None,
) -> TaskRecord:
    """Cooperative pause at a safe boundary. Retains rows and worktree_path."""
    task = _require_task(store, task_id)
    if task.lifecycle in _TERMINAL:
        raise TerminalLifecycleError(f"cannot pause task in lifecycle {task.lifecycle.value}")
    if task.lifecycle is LifecycleState.PAUSED:
        return task
    actor = normalize_principal(principal)
    updated = store.update_task(task_id, lifecycle=LifecycleState.PAUSED, now=now)
    store.append_event(
        task_id,
        "task.paused",
        {
            "lifecycle": LifecycleState.PAUSED.value,
            "principal": actor,
            "worktree_path": task.worktree_path,
        },
        now=now,
    )
    return updated


def resume_task(
    store: Store,
    task_id: str,
    *,
    principal: str | None = None,
    now: datetime | None = None,
) -> TaskRecord:
    """Resume the same task id from paused or awaiting_input into queued.

    Cancelled is terminal. Answers already stored as events are copied onto
    the resume event so a later worker can inject them; no new task is created.
    """
    task = _require_task(store, task_id)
    if task.lifecycle in _TERMINAL:
        raise TerminalLifecycleError(f"cannot resume task in lifecycle {task.lifecycle.value}")
    if task.lifecycle is LifecycleState.QUEUED:
        return task
    if task.lifecycle not in _RESUMABLE:
        raise NotResumableError(f"cannot resume task in lifecycle {task.lifecycle.value}")
    actor = normalize_principal(principal)
    answers = _answer_summaries(store, task_id)
    decisions = _decision_summaries(store, task_id)
    previous = task.lifecycle.value
    updated = store.update_task(task_id, lifecycle=LifecycleState.QUEUED, now=now)
    payload: dict[str, object] = {
        "lifecycle": LifecycleState.QUEUED.value,
        "from": previous,
        "principal": actor,
        "answers": answers,
        "approvals": decisions,
        "worktree_path": task.worktree_path,
    }
    store.append_event(task_id, "task.resumed", payload, now=now)
    return updated


def cancel_task(
    store: Store,
    task_id: str,
    *,
    principal: str | None = None,
    now: datetime | None = None,
) -> TaskRecord:
    """Record a cooperative cancel. Worktree path and evidence are retained."""
    task = _require_task(store, task_id)
    if task.lifecycle is LifecycleState.CANCELLED:
        return task
    if task.lifecycle is LifecycleState.COMPLETE:
        raise TerminalLifecycleError("cannot cancel a complete task")
    actor = normalize_principal(principal)
    updated = store.update_task(task_id, lifecycle=LifecycleState.CANCELLED, now=now)
    store.append_event(
        task_id,
        "task.cancelled",
        {
            "lifecycle": LifecycleState.CANCELLED.value,
            "principal": actor,
            "cooperative": True,
            "worktree_path": task.worktree_path,
        },
        now=now,
    )
    return updated


def _require_task(store: Store, task_id: str) -> TaskRecord:
    record = store.get_task(task_id)
    if record is None:
        raise TaskNotFoundError(f"unknown task: {task_id}")
    return record


def _refuse_terminal(task: TaskRecord, action: str) -> None:
    if task.lifecycle in _TERMINAL:
        raise TerminalLifecycleError(
            f"cannot {action} for task in lifecycle {task.lifecycle.value}"
        )


def _timeout_lifecycle(task: TaskRecord, safe_default: str | None) -> LifecycleState:
    if safe_default == "block":
        return LifecycleState.BLOCKED
    if task.manifest.on_human_input_required is OnHumanInputRequired.BLOCK:
        return LifecycleState.BLOCKED
    return LifecycleState.PAUSED


def _answer_summaries(store: Store, task_id: str) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for question in store.list_questions(task_id):
        if question.status != "answered":
            continue
        summaries.append(
            {
                "question_id": question.id,
                "status": question.status,
                "resolver": question.resolver,
            }
        )
    return summaries


def _decision_summaries(store: Store, task_id: str) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for approval in store.list_approvals(task_id):
        if approval.status not in _DECIDED_APPROVAL:
            continue
        summaries.append(
            {
                "approval_id": approval.id,
                "status": approval.status,
                "action_digest": approval.action_digest,
            }
        )
    return summaries
