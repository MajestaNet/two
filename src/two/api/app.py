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

"""ASGI application factory. Maps HTTP to store and ``two.approvals``. No git, no Slack."""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from two import __version__
from two.api.schemas import (
    ApprovalDecideRequest,
    ApprovalDecideResponse,
    ApprovalRequest,
    ApprovalView,
    DiffSummary,
    HealthResponse,
    QuestionAnswerRequest,
    QuestionAnswerResponse,
    QuestionAskRequest,
    QuestionView,
    TaskBudgets,
    TaskMessage,
    TaskMessageReceipt,
    TaskProjection,
    TaskReport,
    ValidationSummary,
)
from two.approvals import (
    NotResumableError,
    StaleDigestError,
    TerminalLifecycleError,
    answer_question,
    ask_question,
    cancel_task,
    decide_approval,
    pause_task,
    request_approval,
    resume_task,
)
from two.manifest import TaskManifest
from two.store import (
    ApprovalNotFoundError,
    DuplicateApprovalError,
    DuplicateQuestionError,
    DuplicateTaskError,
    QuestionNotFoundError,
    Store,
    TaskNotFoundError,
    open_store,
)
from two.store.models import ApprovalRecord, EventRecord, QuestionRecord, TaskRecord

_PLAN_EVENT_TYPES = frozenset({"plan", "task.plan"})
_TODO_EVENT_TYPES = frozenset({"todos", "task.todos"})
_BLOCKER_EVENT_TYPES = frozenset({"blocker", "task.blocker"})
_DIFF_EVENT_TYPES = frozenset({"diff", "task.diff"})
_VALIDATION_EVENT_TYPES = frozenset({"validation", "task.validation"})


class _StoreBox:
    """Single-connection store plus a lock so async routes stay on one thread."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.lock = asyncio.Lock()


def create_app(
    *,
    store: Store | None = None,
    store_path: Path | str | None = None,
    require_auth: bool = False,
    auth_token: str | None = None,
) -> FastAPI:
    """Build the control API. Does not bind a socket and does not call Ollama.

    When ``store`` is omitted the factory opens ``store_path`` or
    ``{TWO_DATA_DIR}/two.sqlite`` and closes it on shutdown.
    """
    close_store = store is None
    opened = store if store is not None else open_store(store_path, check_same_thread=False)
    box = _StoreBox(opened)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if close_store:
            opened.close()

    app = FastAPI(
        title="Majesta Two control API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.box = box
    app.state.require_auth = require_auth
    app.state.auth_token = auth_token

    async def _require_token(request: Request) -> None:
        if not bool(request.app.state.require_auth):
            return
        expected = request.app.state.auth_token
        if not isinstance(expected, str) or expected == "":
            raise HTTPException(status_code=401, detail="controller token is not configured")
        header = request.headers.get("authorization", "")
        scheme, _, offered = header.partition(" ")
        if scheme.lower() != "bearer" or not offered:
            raise HTTPException(status_code=401, detail="missing bearer token")
        if not hmac.compare_digest(offered, expected):
            raise HTTPException(status_code=401, detail="invalid token")

    router = APIRouter(dependencies=[Depends(_require_token)])
    router.add_api_route("/v1/tasks", _create_task, methods=["POST"], status_code=201)
    router.add_api_route("/v1/tasks/{task_id}", _get_task, methods=["GET"])
    router.add_api_route(
        "/v1/tasks/{task_id}/messages",
        _post_message,
        methods=["POST"],
        status_code=201,
    )
    router.add_api_route("/v1/tasks/{task_id}/pause", _pause_task, methods=["POST"])
    router.add_api_route("/v1/tasks/{task_id}/resume", _resume_task, methods=["POST"])
    router.add_api_route("/v1/tasks/{task_id}/cancel", _cancel_task, methods=["POST"])
    router.add_api_route(
        "/v1/tasks/{task_id}/questions",
        _ask_question,
        methods=["POST"],
        status_code=201,
    )
    router.add_api_route(
        "/v1/tasks/{task_id}/questions/{question_id}/answer",
        _answer_question,
        methods=["POST"],
    )
    router.add_api_route(
        "/v1/tasks/{task_id}/approvals",
        _request_approval,
        methods=["POST"],
        status_code=201,
    )
    router.add_api_route(
        "/v1/tasks/{task_id}/approvals/{approval_id}/decide",
        _decide_approval,
        methods=["POST"],
    )
    router.add_api_route("/v1/tasks/{task_id}/report", _get_report, methods=["GET"])
    app.include_router(router)

    @app.get("/health")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="two-api")

    return app


def _box(request: Request) -> _StoreBox:
    box = request.app.state.box
    if not isinstance(box, _StoreBox):
        raise HTTPException(status_code=500, detail="store is not configured")
    return box


async def _create_task(request: Request, manifest: TaskManifest) -> JSONResponse:
    box = _box(request)
    async with box.lock:
        try:
            record = box.store.insert_task(manifest)
            box.store.append_event(
                record.id,
                "task.created",
                {"objective": record.objective, "lifecycle": record.lifecycle.value},
            )
        except DuplicateTaskError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        projection = _project(box.store, record)
    return JSONResponse(
        status_code=201,
        content=projection.model_dump(mode="json"),
        headers={"Location": f"/v1/tasks/{record.id}"},
    )


async def _get_task(request: Request, task_id: str) -> TaskProjection:
    box = _box(request)
    async with box.lock:
        return _require_projection(box.store, task_id)


async def _post_message(
    request: Request,
    task_id: str,
    message: TaskMessage,
) -> TaskMessageReceipt:
    box = _box(request)
    async with box.lock:
        _require_task(box.store, task_id)
        payload: dict[str, object] = {"text": message.text}
        if message.source is not None:
            payload["source"] = message.source
        event_id = box.store.append_event(task_id, "task.message", payload)
    return TaskMessageReceipt(task_id=task_id, event_id=event_id)


async def _pause_task(request: Request, task_id: str) -> TaskProjection:
    box = _box(request)
    async with box.lock:
        try:
            record = pause_task(box.store, task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TerminalLifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _project(box.store, record)


async def _resume_task(request: Request, task_id: str) -> TaskProjection:
    box = _box(request)
    async with box.lock:
        try:
            record = resume_task(box.store, task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (TerminalLifecycleError, NotResumableError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _project(box.store, record)


async def _cancel_task(request: Request, task_id: str) -> TaskProjection:
    box = _box(request)
    async with box.lock:
        try:
            record = cancel_task(box.store, task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TerminalLifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _project(box.store, record)


async def _ask_question(
    request: Request,
    task_id: str,
    body: QuestionAskRequest,
) -> JSONResponse:
    box = _box(request)
    async with box.lock:
        try:
            ask_question(
                box.store,
                task_id,
                question_id=body.id,
                stage=body.stage,
                options=body.options,
                reason=body.reason,
                recommendation=body.recommendation,
                actor=body.actor,
            )
            record = _require_task(box.store, task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DuplicateQuestionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TerminalLifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        projection = _project(box.store, record)
    return JSONResponse(
        status_code=201,
        content=projection.model_dump(mode="json"),
        headers={"Location": f"/v1/tasks/{task_id}/questions/{body.id}"},
    )


async def _answer_question(
    request: Request,
    task_id: str,
    question_id: str,
    body: QuestionAnswerRequest,
) -> QuestionAnswerResponse:
    box = _box(request)
    async with box.lock:
        try:
            result = answer_question(
                box.store,
                task_id,
                question_id,
                answer=body.answer,
                principal=body.actor,
            )
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except QuestionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TerminalLifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return QuestionAnswerResponse(
        task_id=task_id,
        question_id=question_id,
        ignored=result.ignored,
        event_id=result.event_id,
        principal=result.principal,
        status=result.question.status,
    )


async def _request_approval(
    request: Request,
    task_id: str,
    body: ApprovalRequest,
) -> JSONResponse:
    box = _box(request)
    async with box.lock:
        try:
            request_approval(
                box.store,
                task_id,
                approval_id=body.id,
                action_class=body.action_class,
                action_digest=body.action_digest,
                paths=body.paths,
            )
            record = _require_task(box.store, task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DuplicateApprovalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TerminalLifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        projection = _project(box.store, record)
    return JSONResponse(
        status_code=201,
        content=projection.model_dump(mode="json"),
        headers={"Location": f"/v1/tasks/{task_id}/approvals/{body.id}"},
    )


async def _decide_approval(
    request: Request,
    task_id: str,
    approval_id: str,
    body: ApprovalDecideRequest,
) -> ApprovalDecideResponse:
    box = _box(request)
    async with box.lock:
        try:
            result = decide_approval(
                box.store,
                task_id,
                approval_id,
                decision=body.decision,
                principal=body.actor,
                action_digest=body.action_digest,
                comment=body.comment,
            )
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ApprovalNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StaleDigestError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApprovalDecideResponse(
        task_id=task_id,
        approval_id=approval_id,
        decision=result.decision,
        event_id=result.event_id,
        ignored=result.ignored,
        action_digest=result.approval.action_digest,
        principal=result.principal,
    )


async def _get_report(request: Request, task_id: str) -> TaskReport:
    box = _box(request)
    async with box.lock:
        projection = _require_projection(box.store, task_id)
    return TaskReport(
        task_id=projection.id,
        lifecycle=projection.lifecycle,
        stage=projection.stage,
        objective=projection.objective,
        acceptance_criteria=projection.acceptance_criteria,
        branch=projection.branch,
        worktree_path=projection.worktree_path,
        diff_summary=projection.diff_summary,
        validation_summary=projection.validation_summary,
        assembled=False,
    )


def _require_task(store: Store, task_id: str) -> TaskRecord:
    record = store.get_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown task: {task_id}")
    return record


def _require_projection(store: Store, task_id: str) -> TaskProjection:
    record = _require_task(store, task_id)
    return _project(store, record)


def _project(store: Store, record: TaskRecord) -> TaskProjection:
    events = store.list_events(record.id)
    questions = [_question_view(item) for item in store.list_questions(record.id)]
    approvals = [_approval_view(item) for item in store.list_approvals(record.id)]
    plan = _latest_object(events, _PLAN_EVENT_TYPES)
    todos = _latest_list(events, _TODO_EVENT_TYPES)
    blockers = _blocker_messages(events)
    validation = _validation_from_events(events)
    diff = _diff_from_events(events)
    manifest = record.manifest
    return TaskProjection(
        id=record.id,
        repository=record.repository,
        base_ref=record.base_ref,
        objective=record.objective,
        acceptance_criteria=list(manifest.acceptance_criteria),
        mode=record.mode,
        execution_profile=record.execution_profile,
        lifecycle=record.lifecycle,
        stage=record.stage,
        budgets=TaskBudgets(
            time_budget_minutes=record.time_budget_minutes,
            max_model_turns=record.max_model_turns,
            max_repair_cycles=record.max_repair_cycles,
            no_progress_limit=record.no_progress_limit,
            max_changed_lines=manifest.max_changed_lines,
        ),
        plan=plan,
        todos=todos,
        diff_summary=diff,
        validation_summary=validation,
        blockers=blockers,
        questions=questions,
        approvals=approvals,
        worktree_path=record.worktree_path,
        branch=record.branch,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _question_view(record: QuestionRecord) -> QuestionView:
    return QuestionView(
        id=record.id,
        stage=record.stage,
        status=record.status,
        options=list(record.options),
        recommendation=record.recommendation,
        reason=record.reason,
    )


def _approval_view(record: ApprovalRecord) -> ApprovalView:
    return ApprovalView(
        id=record.id,
        action_class=record.action_class,
        action_digest=record.action_digest,
        paths=list(record.paths),
        status=record.status,
    )


def _latest_matching(events: list[EventRecord], types: frozenset[str]) -> EventRecord | None:
    matched = [event for event in events if event.type in types]
    if not matched:
        return None
    return matched[-1]


def _latest_object(events: list[EventRecord], types: frozenset[str]) -> dict[str, Any] | None:
    event = _latest_matching(events, types)
    if event is None:
        return None
    return dict(event.payload)


def _latest_list(events: list[EventRecord], types: frozenset[str]) -> list[Any]:
    event = _latest_matching(events, types)
    if event is None:
        return []
    items = event.payload.get("items", event.payload.get("todos"))
    if isinstance(items, list):
        return list(items)
    return []


def _blocker_messages(events: list[EventRecord]) -> list[str]:
    messages: list[str] = []
    for event in events:
        if event.type not in _BLOCKER_EVENT_TYPES:
            continue
        raw = event.payload.get("message", event.payload.get("reason"))
        if isinstance(raw, str) and raw:
            messages.append(raw)
    return messages


def _validation_from_events(events: list[EventRecord]) -> ValidationSummary:
    event = _latest_matching(events, _VALIDATION_EVENT_TYPES)
    if event is None:
        return ValidationSummary()
    payload = event.payload
    passed_raw = payload.get("passed")
    passed = passed_raw if isinstance(passed_raw, bool) else None
    gates_raw = payload.get("gates_run")
    gates_run = gates_raw if isinstance(gates_raw, int) and not isinstance(gates_raw, bool) else 0
    last_gate_raw = payload.get("last_gate")
    last_gate = last_gate_raw if isinstance(last_gate_raw, str) else None
    summary_raw = payload.get("summary")
    summary = summary_raw if isinstance(summary_raw, str) else None
    return ValidationSummary(
        passed=passed,
        gates_run=gates_run,
        last_gate=last_gate,
        summary=summary,
    )


def _diff_from_events(events: list[EventRecord]) -> DiffSummary:
    event = _latest_matching(events, _DIFF_EVENT_TYPES)
    if event is None:
        return DiffSummary()
    payload = event.payload
    return DiffSummary(
        files_changed=_optional_int(payload, "files_changed"),
        lines_added=_optional_int(payload, "lines_added"),
        lines_removed=_optional_int(payload, "lines_removed"),
        placeholder=False,
    )


def _optional_int(payload: Mapping[str, object], key: str) -> int | None:
    raw = payload.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw
