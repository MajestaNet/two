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

"""Correlation, ETag, idempotency, and error-envelope helpers. No I/O besides store."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from two.projection import ErrorBody, ErrorResponse, FieldError, TaskProjection
from two.store import IdempotencyConflictError, IdempotencyInFlightError, Store
from two.types import ErrorCode

CORRELATION_HEADER = "X-Correlation-ID"
IDEMPOTENCY_HEADER = "Idempotency-Key"
IF_MATCH_HEADER = "If-Match"
ETAG_HEADER = "ETag"
MAX_CORRELATION_LEN = 128
MAX_IDEMPOTENCY_KEY_LEN = 256
_CORRELATION_OK = re.compile(rf"^[A-Za-z0-9._:-]{{1,{MAX_CORRELATION_LEN}}}$")
_IDEMPOTENCY_OK = re.compile(rf"^[A-Za-z0-9._~:-]{{1,{MAX_IDEMPOTENCY_KEY_LEN}}}$")


class IdempotencyReplay(Exception):
    """Raised to short-circuit a mutation with a stored response."""

    def __init__(
        self,
        *,
        status_code: int,
        content: Any,
        headers: dict[str, str],
    ) -> None:
        super().__init__("idempotency replay")
        self.status_code = status_code
        self.content = content
        self.headers = headers


def correlation_id_from(request: Request) -> str:
    """Return a safe correlation id from the request or a new UUID."""
    existing = getattr(request.state, "correlation_id", None)
    if isinstance(existing, str) and existing:
        return existing
    offered = request.headers.get(CORRELATION_HEADER, "").strip()
    if _CORRELATION_OK.fullmatch(offered):
        request.state.correlation_id = offered
        return offered
    generated = str(uuid.uuid4())
    request.state.correlation_id = generated
    return generated


def format_etag(revision: int) -> str:
    """Strong ETag for a monotonic resource revision."""
    return f'"{revision}"'


def etag_matches(if_match: str, revision: int) -> bool:
    """True when ``If-Match`` includes ``*`` or the current revision."""
    expected = format_etag(revision)
    for raw in if_match.split(","):
        token = raw.strip()
        if token == "*":
            return True
        if token.startswith("W/"):
            token = token[2:].strip()
        if token == expected:
            return True
    return False


def check_if_match(request: Request, revision: int) -> None:
    """Optional If-Match. Absent keeps B07/CLI behavior; mismatch is 412."""
    offered = request.headers.get(IF_MATCH_HEADER)
    if offered is None or offered.strip() == "":
        return
    if not etag_matches(offered, revision):
        raise HTTPException(status_code=412, detail="resource revision mismatch")


def request_hash(method: str, path: str, body: bytes) -> str:
    """Canonical hash of a mutation. Path excludes the query string."""
    digest = hashlib.sha256()
    digest.update(method.upper().encode("utf-8"))
    digest.update(b"\n")
    digest.update(path.encode("utf-8"))
    digest.update(b"\n")
    digest.update(body)
    return digest.hexdigest()


def error_payload(
    *,
    status_code: int,
    detail: object,
    correlation_id: str | None = None,
    field_errors: list[FieldError] | None = None,
    retry_after_seconds: int | None = None,
    message: str | None = None,
) -> ErrorResponse:
    """B07 error envelope plus optional B14 metadata."""
    resolved = (
        message if message is not None else (detail if isinstance(detail, str) else str(detail))
    )
    return ErrorResponse(
        error=ErrorBody(code=_error_code(status_code, resolved), message=resolved),
        detail=detail if isinstance(detail, list) else resolved,
        correlation_id=correlation_id,
        field_errors=field_errors,
        retry_after_seconds=retry_after_seconds,
    )


def error_response(
    *,
    status_code: int,
    detail: object,
    correlation_id: str | None = None,
    field_errors: list[FieldError] | None = None,
    retry_after_seconds: int | None = None,
    headers: dict[str, str] | None = None,
    message: str | None = None,
) -> JSONResponse:
    """JSON error with FastAPI ``detail`` retained for existing clients."""
    payload = error_payload(
        status_code=status_code,
        detail=detail,
        correlation_id=correlation_id,
        field_errors=field_errors,
        retry_after_seconds=retry_after_seconds,
        message=message,
    )
    extra = dict(headers or {})
    if retry_after_seconds is not None:
        extra["Retry-After"] = str(retry_after_seconds)
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json", exclude_none=True),
        headers=extra,
    )


def resource_response(
    projection: TaskProjection,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Serialize a task projection with its revision ETag."""
    extra = dict(headers or {})
    extra[ETAG_HEADER] = format_etag(projection.revision)
    return JSONResponse(
        status_code=status_code,
        content=projection.model_dump(mode="json"),
        headers=extra,
    )


def field_errors_from_validation(errors: list[Any]) -> list[FieldError]:
    """Map Pydantic/FastAPI validation errors to ``field_errors``."""
    mapped: list[FieldError] = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        loc = item.get("loc", ())
        parts = (
            [str(part) for part in loc if part != "body"] if isinstance(loc, (list, tuple)) else []
        )
        field = ".".join(parts) if parts else "body"
        code = item.get("type")
        msg = item.get("msg")
        mapped.append(
            FieldError(
                field=field,
                code=str(code) if code is not None else "value_error",
                message=str(msg) if msg is not None else "invalid value",
            )
        )
    return mapped


async def begin_request_idempotency(request: Request, store: Store, principal_id: str) -> None:
    """Reserve or replay an Idempotency-Key on POST /v1 mutations."""
    if request.method != "POST":
        return
    raw_key = request.headers.get(IDEMPOTENCY_HEADER)
    if raw_key is None or raw_key.strip() == "":
        return
    key = raw_key.strip()
    if not _IDEMPOTENCY_OK.fullmatch(key) or len(key) > MAX_IDEMPOTENCY_KEY_LEN:
        raise HTTPException(status_code=400, detail="invalid idempotency key")
    body = await request.body()
    digest = request_hash(request.method, request.url.path, body)
    try:
        existing = store.begin_idempotency(
            principal_id,
            key,
            method=request.method,
            path=request.url.path,
            request_hash=digest,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IdempotencyInFlightError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if existing is not None:
        content: Any
        try:
            content = json.loads(existing.response_body) if existing.response_body else None
        except json.JSONDecodeError:
            content = existing.response_body
        headers = dict(existing.response_headers)
        headers[IDEMPOTENCY_HEADER] = key
        raise IdempotencyReplay(
            status_code=existing.status_code,
            content=content,
            headers=headers,
        )
    request.state.idempotency_key = key
    request.state.idempotency_principal = principal_id


def complete_request_idempotency(
    request: Request,
    store: Store,
    *,
    status_code: int,
    body: bytes,
    headers: dict[str, str],
) -> None:
    """Store a completed mutation result, or drop a 5xx reservation."""
    key = getattr(request.state, "idempotency_key", None)
    principal_id = getattr(request.state, "idempotency_principal", None)
    if not isinstance(key, str) or not isinstance(principal_id, str):
        return
    if status_code >= 500:
        store.clear_idempotency(principal_id, key)
        return
    stored_headers = {
        name: value for name, value in headers.items() if name.lower() in {"location", "etag"}
    }
    text = body.decode("utf-8") if body else ""
    store.complete_idempotency(
        principal_id,
        key,
        status_code=status_code,
        response_body=text,
        response_headers=stored_headers,
    )


def _error_code(status: int, message: str) -> ErrorCode:
    text = message.lower()
    if status == 401:
        return ErrorCode.UNAUTHORIZED
    if status == 403:
        return ErrorCode.FORBIDDEN
    if status == 404:
        if "task" in text:
            return ErrorCode.TASK_NOT_FOUND
        return ErrorCode.NOT_FOUND
    if status == 412:
        return ErrorCode.STALE_REVISION
    if status == 409:
        if "idempotency" in text:
            return ErrorCode.IDEMPOTENCY_CONFLICT
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
        if "idempotency" in text:
            return ErrorCode.VALIDATION_ERROR
        return ErrorCode.DIGEST_REQUIRED
    if status == 422:
        return ErrorCode.VALIDATION_ERROR
    return ErrorCode.INTERNAL
