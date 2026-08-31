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

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from two import __version__
from two.api.schemas import (
    DEFAULT_EVENT_LIMIT,
    DEFAULT_LIST_LIMIT,
    MAX_DIFF_PATHS,
    MAX_EVENT_LIMIT,
    MAX_LIST_LIMIT,
    ApprovalDecideRequest,
    ApprovalDecideResponse,
    ApprovalRequest,
    ApprovalView,
    DiffSummary,
    ErrorBody,
    ErrorResponse,
    EventListResponse,
    EventView,
    HealthResponse,
    QuestionAnswerRequest,
    QuestionAnswerResponse,
    QuestionAskRequest,
    QuestionView,
    TaskBudgets,
    TaskControlRequest,
    TaskListResponse,
    TaskMessage,
    TaskMessageReceipt,
    TaskProjection,
    TaskReport,
    TodoItem,
    ValidationGateView,
    ValidationSummary,
)
from two.approvals import (
    ApprovalNotOpenError,
    DigestRequiredError,
    NotResumableError,
    OpenInputError,
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
from two.reporting import REPORT_EVENT_TYPE, format_final_report, report_from_payload
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
from two.types import ErrorCode, EventType, LifecycleState

_PLAN_EVENT_TYPES = frozenset({EventType.TASK_PLAN.value, "plan"})
_TODO_EVENT_TYPES = frozenset({EventType.TASK_TODOS.value, "todos"})
_BLOCKER_EVENT_TYPES = frozenset({EventType.TASK_BLOCKER.value, "blocker"})
_DIFF_EVENT_TYPES = frozenset({EventType.TASK_DIFF.value, "diff"})
_VALIDATION_EVENT_TYPES = frozenset({EventType.TASK_VALIDATION.value, "validation"})
_REPORT_EVENT_TYPES = frozenset({REPORT_EVENT_TYPE, EventType.WORKFLOW_REPORT.value})


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

    @app.exception_handler(HTTPException)
    async def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        message = _detail_message(exc.detail)
        payload = ErrorResponse(
            error=ErrorBody(code=_error_code(exc.status_code, message), message=message),
            detail=exc.detail if isinstance(exc.detail, list) else message,
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        payload = ErrorResponse(
            error=ErrorBody(
                code=ErrorCode.VALIDATION_ERROR,
                message="request validation failed",
            ),
            detail=list(exc.errors()),
        )
        return JSONResponse(status_code=422, content=payload.model_dump(mode="json"))

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
    router.add_api_route("/v1/tasks", _list_tasks, methods=["GET"])
    router.add_api_route("/v1/tasks/{task_id}", _get_task, methods=["GET"])
    router.add_api_route("/v1/tasks/{task_id}/events", _list_events, methods=["GET"])
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
        try:
            box.store.schema_version()
        except Exception:
            return HealthResponse(status="degraded", service="two-api", store="error")
        return HealthResponse(status="ok", service="two-api", store="ok")

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
                EventType.TASK_CREATED.value,
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


async def _list_tasks(
    request: Request,
    lifecycle: LifecycleState | None = None,
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
) -> TaskListResponse:
    box = _box(request)
    async with box.lock:
        records = box.store.list_tasks(lifecycle=lifecycle)[:limit]
        tasks = [_project(box.store, record) for record in records]
    return TaskListResponse(tasks=tasks, limit=limit)


async def _get_task(request: Request, task_id: str) -> TaskProjection:
    box = _box(request)
    async with box.lock:
        return _require_projection(box.store, task_id)


async def _list_events(
    request: Request,
    task_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_EVENT_LIMIT, ge=1, le=MAX_EVENT_LIMIT),
) -> EventListResponse:
    box = _box(request)
    async with box.lock:
        _require_task(box.store, task_id)
        events = [
            EventView(
                seq=event.seq,
                type=event.type,
                payload=dict(event.payload),
                created_at=event.created_at,
            )
            for event in box.store.list_events(task_id)
            if event.seq > after_seq
        ][:limit]
    return EventListResponse(task_id=task_id, events=events, limit=limit)


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
        if message.principal is not None:
            payload["principal"] = message.principal
        event_id = box.store.append_event(task_id, EventType.TASK_MESSAGE.value, payload)
    return TaskMessageReceipt(task_id=task_id, event_id=event_id)


def _principal(body: TaskControlRequest | None) -> str | None:
    if body is None:
        return None
    return body.principal


async def _pause_task(
    request: Request,
    task_id: str,
    body: TaskControlRequest | None = None,
) -> TaskProjection:
    box = _box(request)
    async with box.lock:
        try:
            record = pause_task(box.store, task_id, principal=_principal(body))
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TerminalLifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _project(box.store, record)


async def _resume_task(
    request: Request,
    task_id: str,
    body: TaskControlRequest | None = None,
) -> TaskProjection:
    box = _box(request)
    async with box.lock:
        try:
            record = resume_task(box.store, task_id, principal=_principal(body))
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (TerminalLifecycleError, NotResumableError, OpenInputError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _project(box.store, record)


async def _cancel_task(
    request: Request,
    task_id: str,
    body: TaskControlRequest | None = None,
) -> TaskProjection:
    box = _box(request)
    async with box.lock:
        try:
            record = cancel_task(box.store, task_id, principal=_principal(body))
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
        except DigestRequiredError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ApprovalNotOpenError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        events = box.store.list_events(task_id)
    report_event = _latest_matching(events, _REPORT_EVENT_TYPES)
    if report_event is None:
        return TaskReport(
            task_id=projection.id,
            lifecycle=projection.lifecycle,
            stage=projection.stage,
            objective=projection.objective,
            acceptance_criteria=projection.acceptance_criteria,
            branch=projection.branch,
            worktree_path=projection.worktree_path,
            base_commit=projection.base_commit,
            diff_summary=projection.diff_summary,
            validation_summary=projection.validation_summary,
            assembled=False,
        )
    assembled = report_from_payload(dict(report_event.payload))
    return TaskReport(
        task_id=projection.id,
        lifecycle=projection.lifecycle,
        stage=projection.stage,
        objective=projection.objective,
        acceptance_criteria=projection.acceptance_criteria,
        branch=projection.branch,
        worktree_path=projection.worktree_path,
        base_commit=projection.base_commit,
        diff_summary=projection.diff_summary,
        validation_summary=projection.validation_summary,
        assembled=True,
        notes=format_final_report(assembled),
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
        cloud_allowed=record.cloud_allowed,
        lifecycle=record.lifecycle,
        stage=record.stage,
        budgets=TaskBudgets(
            execution_profile=record.execution_profile,
            time_budget_minutes=record.time_budget_minutes,
            max_model_turns=record.max_model_turns,
            max_repair_cycles=record.max_repair_cycles,
            no_progress_limit=record.no_progress_limit,
            max_changed_lines=manifest.max_changed_lines,
            remaining_active_seconds=_remaining_active_seconds(record.time_budget_minutes),
        ),
        plan=plan,
        todos=_todos_from_items(todos),
        diff_summary=diff,
        validation_summary=validation,
        blockers=blockers,
        questions=questions,
        approvals=approvals,
        worktree_path=record.worktree_path,
        branch=record.branch,
        base_commit=record.base_commit,
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
        actor=record.actor,
        created_at=record.created_at,
    )


def _approval_view(record: ApprovalRecord) -> ApprovalView:
    return ApprovalView(
        id=record.id,
        action_class=record.action_class,
        action_digest=record.action_digest,
        paths=list(record.paths),
        status=record.status,
        created_at=record.created_at,
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
    gates = _gates_from_payload(payload)
    if gates_run == 0 and gates:
        gates_run = len(gates)
    return ValidationSummary(
        passed=passed,
        gates_run=gates_run,
        last_gate=last_gate,
        summary=summary,
        gates=gates,
    )


def _diff_from_events(events: list[EventRecord]) -> DiffSummary:
    event = _latest_matching(events, _DIFF_EVENT_TYPES)
    if event is None:
        return DiffSummary()
    payload = event.payload
    paths_raw = payload.get("paths")
    paths: list[str] = []
    if isinstance(paths_raw, list):
        for item in paths_raw:
            if isinstance(item, str) and item:
                paths.append(item)
            if len(paths) >= MAX_DIFF_PATHS:
                break
    return DiffSummary(
        files_changed=_optional_int(payload, "files_changed"),
        lines_added=_optional_int(payload, "lines_added"),
        lines_removed=_optional_int(payload, "lines_removed"),
        paths=paths,
        placeholder=False,
    )


def _optional_int(payload: Mapping[str, object], key: str) -> int | None:
    raw = payload.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def _remaining_active_seconds(time_budget_minutes: int | None) -> int | None:
    if time_budget_minutes is None:
        return None
    return max(0, time_budget_minutes * 60)


def _todos_from_items(items: list[Any]) -> list[TodoItem]:
    todos: list[TodoItem] = []
    for index, item in enumerate(items):
        if isinstance(item, TodoItem):
            todos.append(item)
            continue
        if isinstance(item, Mapping):
            try:
                todos.append(TodoItem.model_validate(dict(item)))
                continue
            except ValidationError:
                content = str(item.get("content", item))
                todos.append(TodoItem(id=str(index), content=content))
                continue
        todos.append(TodoItem(id=str(index), content=str(item)))
    return todos


def _gates_from_payload(payload: Mapping[str, object]) -> list[ValidationGateView]:
    raw = payload.get("gates")
    if not isinstance(raw, list):
        return []
    gates: list[ValidationGateView] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            gates.append(ValidationGateView.model_validate(dict(item)))
        except ValidationError:
            name = item.get("name")
            passed = item.get("passed")
            if isinstance(name, str) and isinstance(passed, bool):
                gates.append(ValidationGateView(name=name, passed=passed))
    return gates


def _detail_message(detail: object) -> str:
    if isinstance(detail, str):
        return detail
    return str(detail)


def _error_code(status: int, message: str) -> ErrorCode:
    text = message.lower()
    if status == 401:
        return ErrorCode.UNAUTHORIZED
    if status == 404:
        if "task" in text:
            return ErrorCode.TASK_NOT_FOUND
        return ErrorCode.NOT_FOUND
    if status == 409:
        if "already exists" in text:
            return ErrorCode.DUPLICATE_TASK
        if "stale" in text:
            return ErrorCode.STALE_DIGEST
        if "open" in text:
            return ErrorCode.OPEN_INPUT
        if "resume" in text:
            return ErrorCode.NOT_RESUMABLE
        return ErrorCode.CONFLICT_LIFECYCLE
    if status == 400:
        return ErrorCode.DIGEST_REQUIRED
    if status == 422:
        return ErrorCode.VALIDATION_ERROR
    return ErrorCode.INTERNAL
