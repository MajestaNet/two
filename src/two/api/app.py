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
from collections.abc import AsyncIterator, Callable, Collection, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from two import __version__
from two.api.contract import (
    CORRELATION_HEADER,
    IdempotencyReplay,
    begin_request_idempotency,
    check_if_match,
    complete_request_idempotency,
    correlation_id_from,
    error_response,
    field_errors_from_validation,
    format_etag,
    resource_response,
)
from two.api.conversation import (
    conversation_items,
    is_safe_artifact_id,
    looks_like_host_path,
    parse_task_cursor,
    redact_mapping,
    sse_chunks_for_global,
    sse_chunks_for_task,
)
from two.api.gui import (
    list_artifact_metadata,
    load_repository_views,
    project_repository_summary,
    project_system_health,
    project_system_queue,
    project_task_diff,
    read_artifact_file,
    relative_path_pattern,
    resolve_repositories_dir,
    utcnow,
)
from two.api.principal import (
    action_principal,
    authenticate_request,
    claimed_actor,
    operator_scope_values,
    require_scope,
)
from two.api.schemas import (
    DEFAULT_CONVERSATION_LIMIT,
    DEFAULT_EVENT_LIMIT,
    DEFAULT_HEALTH_STALE_AFTER_MS,
    DEFAULT_LIST_LIMIT,
    DEFAULT_STREAM_BACKLOG,
    MAX_CONVERSATION_LIMIT,
    MAX_DIFF_PATHS,
    MAX_EVENT_LIMIT,
    MAX_LIST_LIMIT,
    ApprovalDecideRequest,
    ApprovalDecideResponse,
    ApprovalRequest,
    ApprovalView,
    ArtifactContent,
    ArtifactListResponse,
    AuthCapabilities,
    ClientFeatures,
    ConversationPage,
    DiffSummary,
    EventListResponse,
    EventView,
    HealthObservation,
    HealthResponse,
    ProjectListResponse,
    QuestionAnswerRequest,
    QuestionAnswerResponse,
    QuestionAskRequest,
    QuestionView,
    RepositoryListResponse,
    SystemCapabilities,
    SystemHealth,
    SystemQueue,
    TaskBudgets,
    TaskControlRequest,
    TaskDiffView,
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
from two.graph.view import to_graph_view, todos_from_graph
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
from two.types import EventType, LifecycleState, Scope

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
    operator_scopes: Collection[Scope | str] | None = None,
    repositories_dir: Path | str | None = None,
    data_dir: Path | str | None = None,
    health_observations: Mapping[str, HealthObservation] | None = None,
    stream_backlog_limit: int = DEFAULT_STREAM_BACKLOG,
    stream_min_seq: int = 0,
    health_stale_after_ms: int = DEFAULT_HEALTH_STALE_AFTER_MS,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Build the control API. Does not bind a socket and does not call Ollama.

    When ``store`` is omitted the factory opens ``store_path`` or
    ``{TWO_DATA_DIR}/two.sqlite`` and closes it on shutdown.
    ``operator_scopes`` is a test hook; production token/local-trust callers
    receive the full operator set. Request bodies cannot add scopes.
    Health observations are injected; the API never probes Ollama or the Mac.
    """
    close_store = store is None
    opened = store if store is not None else open_store(store_path, check_same_thread=False)
    box = _StoreBox(opened)
    scopes = operator_scope_values(operator_scopes)

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
    app.state.operator_scopes = scopes
    app.state.repositories_dir = Path(repositories_dir) if repositories_dir is not None else None
    app.state.data_dir = Path(data_dir) if data_dir is not None else None
    app.state.health_observations = dict(health_observations or {})
    app.state.stream_backlog_limit = stream_backlog_limit
    app.state.stream_min_seq = stream_min_seq
    app.state.health_stale_after_ms = health_stale_after_ms
    app.state.clock = clock if clock is not None else utcnow

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error_response(
            status_code=exc.status_code,
            detail=exc.detail,
            correlation_id=correlation_id_from(request),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = list(exc.errors())
        return error_response(
            status_code=422,
            detail=errors,
            message="request validation failed",
            correlation_id=correlation_id_from(request),
            field_errors=field_errors_from_validation(errors),
        )

    @app.exception_handler(IdempotencyReplay)
    async def _idempotency_replay(_request: Request, exc: IdempotencyReplay) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.content, headers=exc.headers)

    @app.middleware("http")
    async def _contract_middleware(request: Request, call_next: Any) -> Response:
        cid = correlation_id_from(request)
        response = await call_next(request)
        media = (response.media_type or "").split(";", 1)[0].strip().lower()
        content_type = (
            str(response.headers.get("content-type", "")).split(";", 1)[0].strip().lower()
        )
        if media == "text/event-stream" or content_type == "text/event-stream":
            if not isinstance(response, Response):
                raise TypeError("streaming response is not a Response")
            response.headers[CORRELATION_HEADER] = cid
            return response
        chunks = [chunk async for chunk in response.body_iterator]
        body = b"".join(chunks)
        headers = {str(key): str(value) for key, value in response.headers.items()}
        headers.pop(CORRELATION_HEADER, None)
        headers.pop(CORRELATION_HEADER.lower(), None)
        headers[CORRELATION_HEADER] = cid
        if getattr(request.state, "idempotency_key", None):
            async with box.lock:
                complete_request_idempotency(
                    request,
                    box.store,
                    status_code=int(response.status_code),
                    body=body,
                    headers=headers,
                )
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )

    async def _authenticate(request: Request) -> None:
        principal = authenticate_request(
            request,
            require_auth=bool(request.app.state.require_auth),
            auth_token=request.app.state.auth_token,
            scopes=request.app.state.operator_scopes,
        )
        request.state.principal = principal
        async with box.lock:
            await begin_request_idempotency(request, box.store, principal.id)

    router = APIRouter(dependencies=[Depends(_authenticate)])
    router.add_api_route("/v1/system/capabilities", _get_capabilities, methods=["GET"])
    router.add_api_route("/v1/system/health", _get_system_health, methods=["GET"])
    router.add_api_route("/v1/system/queue", _get_system_queue, methods=["GET"])
    router.add_api_route("/v1/tasks", _create_task, methods=["POST"], status_code=201)
    router.add_api_route("/v1/tasks", _list_tasks, methods=["GET"])
    router.add_api_route("/v1/tasks/{task_id}", _get_task, methods=["GET"])
    router.add_api_route("/v1/tasks/{task_id}/events", _list_events, methods=["GET"])
    router.add_api_route("/v1/tasks/{task_id}/conversation", _get_conversation, methods=["GET"])
    router.add_api_route("/v1/tasks/{task_id}/stream", _stream_task, methods=["GET"])
    router.add_api_route("/v1/stream", _stream_system, methods=["GET"])
    router.add_api_route("/v1/tasks/{task_id}/diff", _get_diff, methods=["GET"])
    router.add_api_route("/v1/tasks/{task_id}/artifacts", _list_artifacts, methods=["GET"])
    router.add_api_route(
        "/v1/tasks/{task_id}/artifacts/{artifact_id}",
        _get_artifact,
        methods=["GET"],
    )
    router.add_api_route("/v1/repositories", _list_repositories, methods=["GET"])
    router.add_api_route("/v1/repositories/{repository_id}", _get_repository, methods=["GET"])
    router.add_api_route("/v1/projects", _list_projects, methods=["GET"])
    router.add_api_route("/v1/projects/{project_id}", _get_project, methods=["GET"])
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


async def _get_capabilities(request: Request) -> SystemCapabilities:
    principal = require_scope(request, Scope.SYSTEM_READ)
    return SystemCapabilities(
        principal=principal.id,
        scopes=sorted(principal.scopes),
        auth=AuthCapabilities(
            method=principal.method,
            oidc_available=False,
            mobile_ready=False,
        ),
        features=ClientFeatures(
            conversation=True,
            sse=True,
            projects=True,
            repositories=True,
            aggregate_health=True,
            queue=True,
            graph=True,
        ),
    )


async def _create_task(request: Request, manifest: TaskManifest) -> JSONResponse:
    require_scope(request, Scope.TASKS_CONTROL)
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
        projection = _require_projection(box.store, record.id)
    return resource_response(
        projection,
        status_code=201,
        headers={"Location": f"/v1/tasks/{record.id}"},
    )


async def _list_tasks(
    request: Request,
    lifecycle: LifecycleState | None = None,
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
) -> TaskListResponse:
    require_scope(request, Scope.TASKS_READ)
    box = _box(request)
    async with box.lock:
        records = box.store.list_tasks(lifecycle=lifecycle)[:limit]
        tasks = [_project(box.store, record) for record in records]
    return TaskListResponse(tasks=tasks, limit=limit)


async def _get_task(request: Request, task_id: str) -> JSONResponse:
    require_scope(request, Scope.TASKS_READ)
    box = _box(request)
    async with box.lock:
        projection = _require_projection(box.store, task_id)
    return resource_response(projection)


async def _list_events(
    request: Request,
    task_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_EVENT_LIMIT, ge=1, le=MAX_EVENT_LIMIT),
) -> EventListResponse:
    principal = require_scope(request, Scope.EVENTS_AUDIT)
    box = _box(request)
    async with box.lock:
        _require_task(box.store, task_id)
        events = [
            EventView(
                seq=event.seq,
                type=event.type,
                payload=(
                    dict(event.payload)
                    if principal.method == "local_trust"
                    else redact_mapping(event.payload)
                ),
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
) -> JSONResponse:
    require_scope(request, Scope.TASKS_MESSAGE)
    box = _box(request)
    principal = action_principal(request, message.principal)
    async with box.lock:
        record = _require_task(box.store, task_id)
        check_if_match(request, record.revision)
        payload: dict[str, object] = {"text": message.text, "principal": principal}
        if message.source is not None:
            payload["source"] = message.source
        event_id = box.store.append_event(task_id, EventType.TASK_MESSAGE.value, payload)
        updated = _require_task(box.store, task_id)
    receipt = TaskMessageReceipt(task_id=task_id, event_id=event_id, revision=updated.revision)
    return JSONResponse(
        status_code=201,
        content=receipt.model_dump(mode="json"),
        headers={"ETag": format_etag(updated.revision)},
    )


async def _pause_task(
    request: Request,
    task_id: str,
    body: TaskControlRequest | None = None,
) -> JSONResponse:
    require_scope(request, Scope.TASKS_CONTROL)
    box = _box(request)
    principal = action_principal(request, claimed_actor(body))
    async with box.lock:
        record = _require_task(box.store, task_id)
        check_if_match(request, record.revision)
        try:
            pause_task(box.store, task_id, principal=principal)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TerminalLifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return resource_response(_require_projection(box.store, task_id))


async def _resume_task(
    request: Request,
    task_id: str,
    body: TaskControlRequest | None = None,
) -> JSONResponse:
    require_scope(request, Scope.TASKS_CONTROL)
    box = _box(request)
    principal = action_principal(request, claimed_actor(body))
    async with box.lock:
        record = _require_task(box.store, task_id)
        check_if_match(request, record.revision)
        try:
            resume_task(box.store, task_id, principal=principal)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (TerminalLifecycleError, NotResumableError, OpenInputError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return resource_response(_require_projection(box.store, task_id))


async def _cancel_task(
    request: Request,
    task_id: str,
    body: TaskControlRequest | None = None,
) -> JSONResponse:
    require_scope(request, Scope.TASKS_CONTROL)
    box = _box(request)
    principal = action_principal(request, claimed_actor(body))
    async with box.lock:
        record = _require_task(box.store, task_id)
        check_if_match(request, record.revision)
        try:
            cancel_task(box.store, task_id, principal=principal)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TerminalLifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return resource_response(_require_projection(box.store, task_id))


async def _ask_question(
    request: Request,
    task_id: str,
    body: QuestionAskRequest,
) -> JSONResponse:
    require_scope(request, Scope.TASKS_CONTROL)
    box = _box(request)
    actor = action_principal(request, body.actor)
    async with box.lock:
        record = _require_task(box.store, task_id)
        check_if_match(request, record.revision)
        try:
            ask_question(
                box.store,
                task_id,
                question_id=body.id,
                stage=body.stage,
                options=body.options,
                reason=body.reason,
                recommendation=body.recommendation,
                actor=actor,
            )
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DuplicateQuestionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TerminalLifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        projection = _require_projection(box.store, task_id)
    return resource_response(
        projection,
        status_code=201,
        headers={"Location": f"/v1/tasks/{task_id}/questions/{body.id}"},
    )


async def _answer_question(
    request: Request,
    task_id: str,
    question_id: str,
    body: QuestionAnswerRequest,
) -> JSONResponse:
    require_scope(request, Scope.TASKS_MESSAGE)
    box = _box(request)
    principal = action_principal(request, body.actor)
    async with box.lock:
        record = _require_task(box.store, task_id)
        check_if_match(request, record.revision)
        try:
            result = answer_question(
                box.store,
                task_id,
                question_id,
                answer=body.answer,
                principal=principal,
            )
            updated = _require_task(box.store, task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except QuestionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TerminalLifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    payload = QuestionAnswerResponse(
        task_id=task_id,
        question_id=question_id,
        ignored=result.ignored,
        event_id=result.event_id,
        principal=result.principal,
        status=result.question.status,
    )
    return JSONResponse(
        content=payload.model_dump(mode="json"),
        headers={"ETag": format_etag(updated.revision)},
    )


async def _request_approval(
    request: Request,
    task_id: str,
    body: ApprovalRequest,
) -> JSONResponse:
    require_scope(request, Scope.TASKS_CONTROL)
    box = _box(request)
    async with box.lock:
        record = _require_task(box.store, task_id)
        check_if_match(request, record.revision)
        try:
            request_approval(
                box.store,
                task_id,
                approval_id=body.id,
                action_class=body.action_class,
                action_digest=body.action_digest,
                paths=body.paths,
            )
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DuplicateApprovalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TerminalLifecycleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        projection = _require_projection(box.store, task_id)
    return resource_response(
        projection,
        status_code=201,
        headers={"Location": f"/v1/tasks/{task_id}/approvals/{body.id}"},
    )


async def _decide_approval(
    request: Request,
    task_id: str,
    approval_id: str,
    body: ApprovalDecideRequest,
) -> JSONResponse:
    require_scope(request, Scope.APPROVALS_DECIDE)
    box = _box(request)
    principal = action_principal(request, body.actor)
    async with box.lock:
        record = _require_task(box.store, task_id)
        check_if_match(request, record.revision)
        try:
            result = decide_approval(
                box.store,
                task_id,
                approval_id,
                decision=body.decision,
                principal=principal,
                action_digest=body.action_digest,
                comment=body.comment,
            )
            updated = _require_task(box.store, task_id)
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
    payload = ApprovalDecideResponse(
        task_id=task_id,
        approval_id=approval_id,
        decision=result.decision,
        event_id=result.event_id,
        ignored=result.ignored,
        action_digest=result.approval.action_digest,
        principal=result.principal,
    )
    return JSONResponse(
        content=payload.model_dump(mode="json"),
        headers={"ETag": format_etag(updated.revision)},
    )


async def _get_report(request: Request, task_id: str) -> TaskReport:
    require_scope(request, Scope.TASKS_READ)
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


async def _get_system_health(request: Request) -> SystemHealth:
    require_scope(request, Scope.SYSTEM_READ)
    box = _box(request)
    clock = request.app.state.clock
    now = clock() if callable(clock) else utcnow()
    try:
        async with box.lock:
            box.store.schema_version()
        store_ok = True
    except Exception:
        store_ok = False
    return project_system_health(
        now=now,
        store_ok=store_ok,
        observations=request.app.state.health_observations,
        stale_after_ms=int(request.app.state.health_stale_after_ms),
    )


async def _get_system_queue(request: Request) -> SystemQueue:
    require_scope(request, Scope.SYSTEM_READ)
    box = _box(request)
    clock = request.app.state.clock
    now = clock() if callable(clock) else utcnow()
    async with box.lock:
        tasks = box.store.list_tasks()
        leases = {}
        for record in tasks:
            lease = box.store.get_lease(record.id)
            if lease is not None:
                leases[record.id] = lease
    return project_system_queue(tasks, leases, now=now)


async def _get_conversation(
    request: Request,
    task_id: str,
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_CONVERSATION_LIMIT, ge=1, le=MAX_CONVERSATION_LIMIT),
) -> ConversationPage:
    require_scope(request, Scope.TASKS_READ)
    box = _box(request)
    after_seq = 0
    if after is not None and after.strip() != "":
        parsed = parse_task_cursor(after)
        if parsed is None:
            raise HTTPException(status_code=400, detail="invalid conversation cursor")
        after_seq = parsed
    async with box.lock:
        record = _require_task(box.store, task_id)
        items = conversation_items(
            task_id,
            box.store.list_events(task_id),
            revision=record.revision,
        )
    page = [item for item in items if item.seq > after_seq][:limit]
    next_cursor = page[-1].cursor if len(page) == limit else None
    return ConversationPage(task_id=task_id, items=page, next_cursor=next_cursor, limit=limit)


async def _stream_task(request: Request, task_id: str) -> StreamingResponse:
    require_scope(request, Scope.TASKS_READ)
    box = _box(request)
    last_event_id = _stream_cursor(request)
    async with box.lock:
        record = _require_task(box.store, task_id)
        items = conversation_items(
            task_id,
            box.store.list_events(task_id),
            revision=record.revision,
        )
    chunks = sse_chunks_for_task(
        items,
        last_event_id=last_event_id,
        min_seq=int(request.app.state.stream_min_seq),
        backlog_limit=int(request.app.state.stream_backlog_limit),
    )
    return _sse_response(chunks)


async def _stream_system(request: Request) -> StreamingResponse:
    require_scope(request, Scope.TASKS_READ)
    box = _box(request)
    last_event_id = _stream_cursor(request)
    async with box.lock:
        items = []
        for record in box.store.list_tasks():
            items.extend(
                conversation_items(
                    record.id,
                    box.store.list_events(record.id),
                    revision=record.revision,
                    global_stream=True,
                )
            )
    chunks = sse_chunks_for_global(
        items,
        last_event_id=last_event_id,
        min_seq=int(request.app.state.stream_min_seq),
        backlog_limit=int(request.app.state.stream_backlog_limit),
    )
    return _sse_response(chunks)


async def _get_diff(
    request: Request,
    task_id: str,
    path: str | None = Query(default=None),
) -> TaskDiffView:
    principal = require_scope(request, Scope.TASKS_READ)
    source_read = Scope.SOURCE_READ.value in principal.scopes
    path_filter: str | None = None
    if path is not None:
        if looks_like_host_path(path):
            raise HTTPException(status_code=400, detail="host filesystem paths are not accepted")
        path_filter = relative_path_pattern(path)
        if path_filter is None:
            raise HTTPException(status_code=400, detail="host filesystem paths are not accepted")
    box = _box(request)
    async with box.lock:
        _require_task(box.store, task_id)
        events = box.store.list_events(task_id)
    return project_task_diff(task_id, events, source_read=source_read, path_filter=path_filter)


async def _list_artifacts(request: Request, task_id: str) -> ArtifactListResponse:
    require_scope(request, Scope.TASKS_READ)
    if request.query_params.get("path") is not None:
        raise HTTPException(status_code=400, detail="artifacts are addressed by server ids")
    box = _box(request)
    async with box.lock:
        _require_task(box.store, task_id)
    artifacts = list_artifact_metadata(task_id, request.app.state.data_dir)
    return ArtifactListResponse(task_id=task_id, artifacts=artifacts)


async def _get_artifact(request: Request, task_id: str, artifact_id: str) -> ArtifactContent:
    principal = require_scope(request, Scope.TASKS_READ)
    if request.query_params.get("path") is not None:
        raise HTTPException(status_code=400, detail="artifacts are addressed by server ids")
    if looks_like_host_path(artifact_id) or not is_safe_artifact_id(artifact_id):
        raise HTTPException(status_code=400, detail="artifacts are addressed by server ids")
    box = _box(request)
    async with box.lock:
        _require_task(box.store, task_id)
    loaded = read_artifact_file(task_id, artifact_id, request.app.state.data_dir)
    if loaded is None:
        raise HTTPException(status_code=404, detail=f"unknown artifact: {artifact_id}")
    metadata, content, truncated = loaded
    source_read = Scope.SOURCE_READ.value in principal.scopes
    return ArtifactContent(
        task_id=task_id,
        artifact=metadata,
        content=content if source_read else None,
        truncated=truncated if source_read else False,
        source_included=source_read,
    )


async def _list_repositories(
    request: Request,
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
) -> RepositoryListResponse:
    require_scope(request, Scope.CONFIG_READ)
    directory = resolve_repositories_dir(request.app.state.repositories_dir)
    views = load_repository_views(directory)
    summaries = [project_repository_summary(view) for view in views.values()][:limit]
    return RepositoryListResponse(repositories=summaries, limit=limit)


async def _get_repository(request: Request, repository_id: str) -> JSONResponse:
    require_scope(request, Scope.CONFIG_READ)
    directory = resolve_repositories_dir(request.app.state.repositories_dir)
    views = load_repository_views(directory)
    view = views.get(repository_id)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown repository: {repository_id}")
    return JSONResponse(content=view.model_dump(mode="json"))


async def _list_projects(
    request: Request,
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
) -> ProjectListResponse:
    require_scope(request, Scope.CONFIG_READ)
    return ProjectListResponse(projects=[], limit=limit)


async def _get_project(request: Request, project_id: str) -> JSONResponse:
    require_scope(request, Scope.CONFIG_READ)
    raise HTTPException(
        status_code=404,
        detail=f"unknown project: {project_id}",
    )


def _stream_cursor(request: Request) -> str | None:
    header = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
    if header is not None and header.strip() != "":
        return header.strip()
    offered = request.query_params.get("cursor") or request.query_params.get("after")
    if offered is not None and offered.strip() != "":
        return offered.strip()
    return None


def _sse_response(chunks: list[str]) -> StreamingResponse:
    async def generate() -> AsyncIterator[str]:
        for chunk in chunks:
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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
    stored_graph = store.load_graph(record.id)
    graph_view = to_graph_view(stored_graph) if stored_graph is not None else None
    todo_items = (
        todos_from_graph(stored_graph) if stored_graph is not None else _todos_from_items(todos)
    )
    return TaskProjection(
        id=record.id,
        revision=record.revision,
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
        todos=todo_items,
        graph=graph_view,
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
